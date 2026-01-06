"""BLE client for direct Ruuvi device communication.

Supports reading history logs from RuuviTag and Ruuvi Air devices
via Nordic UART Service (NUS) over Bluetooth Low Energy.
"""

import asyncio
import struct
from datetime import datetime, timezone

from .models import GatewayReading

# Nordic UART Service UUIDs
NUS_SERVICE = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
NUS_RX = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
NUS_TX = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"

# Device Info Service
INFO_SERVICE = "0000180a-0000-1000-8000-00805f9b34fb"
MODEL_CHAR = "00002a24-0000-1000-8000-00805f9b34fb"
FIRMWARE_CHAR = "00002a26-0000-1000-8000-00805f9b34fb"

# Ruuvi manufacturer ID
RUUVI_MANUFACTURER_ID = 0x0499

# Ruuvi Air history command and end marker
AIR_READ_CMD = bytes([0x3B, 0x00, 0x21])
AIR_END_MARKER = "003b200026"

# Default history period: 10 days (full device memory)
DEFAULT_HISTORY_MINS = 10 * 24 * 60  # 14400 minutes


def decode_air_record(data: bytes, device_mac: str) -> GatewayReading | None:
    """Decode a Ruuvi Air history record.

    Air sends 33-byte records with all fields in one struct.

    Args:
        data: 33-byte record from history packet
        device_mac: Device MAC address for the reading

    Returns:
        GatewayReading or None if invalid
    """
    if len(data) < 33:
        return None

    try:
        timestamp = struct.unpack(">I", data[0:4])[0]
        # Validate timestamp is reasonable (2020-2030)
        if not (1577836800 < timestamp < 1893456000):
            return None

        data_format = data[4]
        temperature = struct.unpack(">h", data[5:7])[0] / 200.0
        humidity = struct.unpack(">H", data[7:9])[0] / 400.0
        pressure = struct.unpack(">H", data[9:11])[0] + 50000
        pm_1_0 = struct.unpack(">H", data[11:13])[0] / 10.0
        pm_2_5 = struct.unpack(">H", data[13:15])[0] / 10.0
        pm_4_0 = struct.unpack(">H", data[15:17])[0] / 10.0
        pm_10_0 = struct.unpack(">H", data[17:19])[0] / 10.0
        co2 = struct.unpack(">H", data[19:21])[0]
        voc = data[21]
        nox = data[22]
        seq = (data[29] << 16) | (data[30] << 8) | data[31]

        return GatewayReading(
            device_id=device_mac,
            timestamp=datetime.fromtimestamp(timestamp),
            measurement_sequence=seq,
            data_format=data_format,
            temperature=round(temperature, 2),
            humidity=round(humidity, 2),
            pressure=pressure,
            co2=co2,
            pm_1_0=pm_1_0,
            pm_2_5=pm_2_5,
            pm_4_0=pm_4_0,
            pm_10_0=pm_10_0,
            voc=voc,
            nox=nox,
        )
    except Exception:
        return None


async def download_history(
    ble_uuid: str,
    device_mac: str,
    device_type: str,
    minutes: int = DEFAULT_HISTORY_MINS,
    on_reading: callable = None,
) -> list[GatewayReading]:
    """Download history from a Ruuvi device via BLE.

    Connects to the device and retrieves historical sensor readings
    using the Nordic UART Service protocol.

    Args:
        ble_uuid: BLE address to connect to
        device_mac: MAC address for the reading
        device_type: 'air' or 'tag'
        minutes: How many minutes of history to request
        on_reading: Optional callback for each reading

    Returns:
        List of readings

    Raises:
        ImportError: If bleak library not installed
        NotImplementedError: If device_type not supported
    """
    from bleak import BleakClient

    # Only Air devices supported for now
    if device_type != "air":
        raise NotImplementedError(f"History sync for {device_type} not yet supported")

    readings = []
    done_event = asyncio.Event()
    last_data_time = [asyncio.get_event_loop().time()]
    seen_timestamps = set()

    def on_notify(_, data: bytearray):
        nonlocal readings
        last_data_time[0] = asyncio.get_event_loop().time()
        hex_str = data.hex().lower()

        # Check for end marker
        if hex_str.endswith(AIR_END_MARKER):
            done_event.set()
            return

        # Skip heartbeat packets
        if len(data) > 0 and data[0] == 0xE0:
            return

        # Parse complete records from packet
        if len(data) >= 5:
            records_count = data[3]
            record_length = data[4]

            if records_count > 0 and record_length > 0:
                for i in range(records_count):
                    start_idx = 5 + i * record_length
                    end_idx = start_idx + record_length
                    if end_idx <= len(data):
                        record = data[start_idx:end_idx]
                        reading = decode_air_record(bytes(record), device_mac)
                        if reading:
                            ts_key = reading.timestamp.timestamp()
                            if ts_key not in seen_timestamps:
                                seen_timestamps.add(ts_key)
                                readings.append(reading)
                                if on_reading:
                                    on_reading(reading)

    async with BleakClient(ble_uuid, timeout=30.0) as client:
        # Read device info (optional, for debugging)
        try:
            await client.read_gatt_char(MODEL_CHAR)
            await client.read_gatt_char(FIRMWARE_CHAR)
        except Exception:
            pass

        # Request MTU 512 (like Android does)
        try:
            if hasattr(client, "request_mtu"):
                await client.request_mtu(512)
        except Exception:
            pass

        # Enable notifications
        await client.start_notify(NUS_TX, on_notify)

        # Build and send command
        now = int(datetime.now(timezone.utc).timestamp())
        start = now - (minutes * 60)
        cmd = AIR_READ_CMD + struct.pack(">I", now) + struct.pack(">I", start)

        await client.write_gatt_char(NUS_RX, cmd)

        # Wait for data with timeouts
        idle_timeout = 5
        total_timeout = 120
        start_time = asyncio.get_event_loop().time()

        while True:
            elapsed = asyncio.get_event_loop().time() - start_time
            idle = asyncio.get_event_loop().time() - last_data_time[0]

            if done_event.is_set():
                break
            if elapsed > total_timeout:
                break
            if len(readings) > 0 and idle > idle_timeout:
                break

            await asyncio.sleep(0.1)

        # Stop notifications before disconnect
        try:
            await client.stop_notify(NUS_TX)
        except Exception:
            pass

        # Small delay for clean disconnect
        await asyncio.sleep(0.5)

    return readings
