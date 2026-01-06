"""BLE-related CLI commands for direct device communication."""

import asyncio

from ruuvi_data.ble import (
    DEFAULT_HISTORY_MINS,
    RUUVI_MANUFACTURER_ID,
    download_history,
)
from ruuvi_data.devices import (
    _generate_nickname,
    build_device_lookup,
    load_devices,
    upsert_device,
)
from ruuvi_data.models import format_reading

from ..ui import DIM, RESET, Spinner, separator_line


def _parse_period(period_str: str) -> int | None:
    """Parse period string to minutes.

    Formats: 30m, 1h, 24h, 7d, 10d
    Returns None if invalid.
    """
    if not period_str:
        return None

    period_str = period_str.lower().strip()

    try:
        if period_str.endswith('m'):
            return int(period_str[:-1])
        elif period_str.endswith('h'):
            return int(period_str[:-1]) * 60
        elif period_str.endswith('d'):
            return int(period_str[:-1]) * 24 * 60
        else:
            # Try raw number as minutes for backwards compatibility
            return int(period_str)
    except ValueError:
        return None


def handle_ble(arg: str) -> None:
    """Handle BLE command with subcommands."""
    parts = arg.split(None, 1)
    subcmd = parts[0] if parts else ""
    subarg = parts[1] if len(parts) > 1 else ""

    if subcmd == "":
        _ble_status()
    elif subcmd == "scan":
        _ble_scan()
    elif subcmd == "sync":
        _ble_sync(subarg)
    elif subcmd == "history":
        _ble_history(subarg)
    elif subcmd == "listen":
        _ble_listen(store=True)
    elif subcmd == "monitor":
        _ble_listen(store=False)
    else:
        print(f"Unknown subcommand: {subcmd}")
        print("\nUsage: ble [scan|listen|monitor|sync|history]")


def _ble_status() -> None:
    """Show BLE status and available commands."""
    devices = load_devices()

    # Count devices with BLE UUID configured
    ble_devices = [d for d in devices if d.ble_uuid]

    print("BLE Status\n")

    if ble_devices:
        print(f"  Devices with BLE address: {len(ble_devices)}/{len(devices)}")
        for d in ble_devices:
            name = d.nickname or d.mac or "?"
            print(f"    {name}: {d.ble_uuid}")
    else:
        print(f"  {DIM}No BLE addresses configured{RESET}")
        print(f"  {DIM}Run 'ble scan' to discover devices{RESET}")

    print("\nSubcommands:")
    print("  ble scan                       Scan for Ruuvi devices")
    print("  ble listen                     Listen to broadcasts and store")
    print("  ble monitor                    Listen to broadcasts (no storage)")
    print("  ble sync [device] [period]     Sync history to database")
    print("  ble history [device] [period]  Display history (no storage)")
    print(f"\n{DIM}Period formats: 30m, 1h, 24h, 7d, 10d (default: 10d){RESET}")


def _ble_scan() -> None:
    """Scan for Ruuvi devices and update config."""
    try:
        from bleak import BleakScanner
    except ImportError:
        print("Error: bleak library not installed")
        print("Install with: pip install bleak")
        return

    print("Scanning for Ruuvi devices...\n")

    async def scan():
        devices = await BleakScanner.discover(
            timeout=10.0,
            return_adv=True,
        )
        return devices

    spinner = Spinner("Scanning")
    spinner.start()

    try:
        devices = asyncio.run(scan())
        spinner.stop()
    except Exception as e:
        spinner.stop()
        print(f"Scan failed: {e}")
        return

    # Filter Ruuvi devices and extract info
    ruuvi_devices = []
    for device, adv_data in devices.values():
        if not adv_data.manufacturer_data:
            continue

        # Check for Ruuvi manufacturer ID
        ruuvi_data = adv_data.manufacturer_data.get(RUUVI_MANUFACTURER_ID)
        if ruuvi_data is None:
            continue

        # Extract MAC from manufacturer data (last 6 bytes)
        if len(ruuvi_data) >= 6:
            mac_bytes = ruuvi_data[-6:]
            mac = ":".join(f"{b:02X}" for b in mac_bytes)
        else:
            mac = None

        # Determine device type from data format
        data_format = ruuvi_data[0] if ruuvi_data else None
        if data_format in (6, 225):  # 0x06 or 0xE1
            device_type = "air"
        elif data_format in (3, 5):
            device_type = "tag"
        else:
            device_type = "unknown"

        ruuvi_devices.append({
            "ble_uuid": str(device.address),  # Ensure plain string for YAML
            "name": device.name or "Unknown",
            "mac": mac,
            "type": device_type,
            "rssi": adv_data.rssi,
        })

    if not ruuvi_devices:
        print("No Ruuvi devices found.")
        print(f"\n{DIM}Make sure devices are powered on and nearby.{RESET}")
        return

    print(f"Found {len(ruuvi_devices)} Ruuvi device(s):\n")

    # Load current devices
    devices_list = load_devices()

    # Create lookup by MAC
    mac_to_config = {d.mac.upper(): d for d in devices_list}

    updated = 0
    added = 0

    for rd in ruuvi_devices:
        mac = rd["mac"]
        ble_uuid = rd["ble_uuid"]
        name = rd["name"]
        device_type = rd["type"]
        rssi = rd["rssi"]

        # Try to match with existing device by MAC
        existing = mac_to_config.get(mac.upper()) if mac else None

        if existing:
            # Update existing device with BLE UUID
            nickname = existing.nickname or mac
            print(f"  {nickname}")
            print(f"    MAC:      {mac}")
            print(f"    BLE UUID: {ble_uuid}")
            print(f"    Type:     {device_type}")
            print(f"    RSSI:     {rssi} dBm")

            if existing.ble_uuid != ble_uuid:
                # Update with new BLE UUID
                upsert_device(mac, ble_uuid=ble_uuid)
                updated += 1
                print(f"    {DIM}→ Updated BLE address{RESET}")
            else:
                print(f"    {DIM}→ Already configured{RESET}")
        else:
            # New device - add to config
            print(f"  {name} (NEW)")
            print(f"    MAC:      {mac or 'unknown'}")
            print(f"    BLE UUID: {ble_uuid}")
            print(f"    Type:     {device_type}")
            print(f"    RSSI:     {rssi} dBm")

            if mac:
                nickname = _generate_nickname(device_type)
                description = "Ruuvi Air" if device_type == "air" else "RuuviTag"
                upsert_device(mac, type=device_type, nickname=nickname, description=description, ble_uuid=ble_uuid)
                added += 1
                print(f"    {DIM}→ Added as {nickname}{RESET}")
            else:
                print(f"    {DIM}→ Skipped (no MAC available){RESET}")

        print()

    # Show summary
    if updated > 0 or added > 0:
        print(separator_line())
        print(f"\nDevices updated: {updated} updated, {added} added")
    else:
        print(f"{DIM}No changes to save.{RESET}")


def _ble_listen(store: bool = False) -> None:
    """Listen to BLE broadcasts from Ruuvi devices.

    Args:
        store: If True, store readings in database. If False, just display.
    """
    try:
        from bleak import BleakScanner
    except ImportError:
        print("Error: bleak library not installed")
        print("Install with: pip install bleak")
        return

    from datetime import datetime
    from ruuvi_data.decoder import decode_raw_data
    from ruuvi_data.models import GatewayReading, format_reading

    devices = load_devices()

    # Build lookups
    device_lookup = build_device_lookup()
    known_macs = {d.mac.upper() for d in devices if d.mac}

    # Storage setup
    storage = None
    if store:
        from ruuvi_data.config import load_config as load_typed_config
        from ruuvi_data.storage import SensorStorage
        from pathlib import Path

        config_path = Path(__file__).parent.parent.parent / "config.yaml"
        typed_config = load_typed_config(config_path)
        storage = SensorStorage(typed_config.storage.path)

    mode = "listen" if store else "monitor"
    print(f"BLE {mode} - receiving broadcasts")
    if known_macs:
        print(f"  Known devices: {len(known_macs)}")
    else:
        print(f"  {DIM}No devices configured, will show all Ruuvi devices{RESET}")
    print(f"{DIM}Press Ctrl+C to stop{RESET}\n")
    print(separator_line())

    # Track seen sequences for deduplication
    seen_sequences: dict[str, int] = {}
    count = [0]
    stored_count = [0]

    def on_advertisement(device, adv_data):
        if not adv_data.manufacturer_data:
            return

        ruuvi_data = adv_data.manufacturer_data.get(RUUVI_MANUFACTURER_ID)
        if ruuvi_data is None:
            return

        # Decode the data
        hex_data = ruuvi_data.hex()
        decoded = decode_raw_data(hex_data)
        if decoded is None:
            return

        # Get MAC from decoded data or manufacturer data
        mac = decoded.mac
        if not mac and len(ruuvi_data) >= 6:
            mac_bytes = ruuvi_data[-6:]
            mac = ":".join(f"{b:02X}" for b in mac_bytes)

        if not mac:
            return

        # Skip if not a known device (when devices are configured)
        if known_macs and mac.upper() not in known_macs:
            return

        # Deduplicate by measurement_sequence
        seq = decoded.measurement_sequence
        if seq is not None:
            last_seq = seen_sequences.get(mac)
            if last_seq == seq:
                return  # Skip duplicate
            seen_sequences[mac] = seq

        # Create reading
        reading = GatewayReading(
            device_id=mac,
            timestamp=datetime.now(),
            measurement_sequence=seq or 0,
            data_format=decoded.data_format,
            temperature=decoded.temperature,
            humidity=decoded.humidity,
            pressure=decoded.pressure,
            co2=decoded.co2,
            pm_1_0=decoded.pm_1_0,
            pm_2_5=decoded.pm_2_5,
            pm_4_0=decoded.pm_4_0,
            pm_10_0=decoded.pm_10_0,
            voc=decoded.voc,
            nox=decoded.nox,
            rssi=adv_data.rssi,
            acceleration_x=decoded.acceleration_x,
            acceleration_y=decoded.acceleration_y,
            acceleration_z=decoded.acceleration_z,
            movement_counter=decoded.movement_counter,
            battery_voltage=decoded.battery_voltage,
            tx_power=decoded.tx_power,
        )

        # Display
        print(format_reading(reading, device_lookup))
        count[0] += 1

        # Store if enabled
        if storage:
            if storage.insert(reading.to_sensor_reading()):
                stored_count[0] += 1

    async def run_scanner():
        scanner = BleakScanner(detection_callback=on_advertisement)
        await scanner.start()
        try:
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            await scanner.stop()

    try:
        asyncio.run(run_scanner())
    except KeyboardInterrupt:
        pass

    print(separator_line())
    if store:
        print(f"\nStopped. Received {count[0]} readings, stored {stored_count[0]} new.")
    else:
        print(f"\nStopped. Received {count[0]} readings.")


def _select_device(arg: str) -> dict | None:
    """Select a device from config by nickname, MAC, or index.

    Returns a dict with mac, type, nickname, ble_uuid for compatibility.
    """
    devices = load_devices()

    # Filter to devices with BLE address
    ble_devices = [d for d in devices if d.ble_uuid]

    if not ble_devices:
        print("No devices with BLE address configured.")
        print(f"Run 'ble scan' first to discover devices.")
        return None

    # If no argument, prompt user to select
    if not arg:
        print("Select a device:\n")
        for i, d in enumerate(ble_devices, 1):
            name = d.nickname or d.mac or "?"
            device_type = d.type or "unknown"
            print(f"  {i}. {name} ({device_type})")

        print()
        try:
            choice = input("Enter number or nickname: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return None

        arg = choice

    # Try to match by number
    try:
        idx = int(arg) - 1
        if 0 <= idx < len(ble_devices):
            d = ble_devices[idx]
            return {"mac": d.mac, "type": d.type, "nickname": d.nickname, "ble_uuid": d.ble_uuid}
    except ValueError:
        pass

    # Try to match by nickname or MAC
    arg_upper = arg.upper()
    for d in ble_devices:
        if d.nickname and d.nickname.upper() == arg_upper:
            return {"mac": d.mac, "type": d.type, "nickname": d.nickname, "ble_uuid": d.ble_uuid}
        if d.mac and d.mac.upper() == arg_upper:
            return {"mac": d.mac, "type": d.type, "nickname": d.nickname, "ble_uuid": d.ble_uuid}
        # Partial match on nickname
        if d.nickname and arg.lower() in d.nickname.lower():
            return {"mac": d.mac, "type": d.type, "nickname": d.nickname, "ble_uuid": d.ble_uuid}

    print(f"Device not found: {arg}")
    return None


def _format_period(minutes: int) -> str:
    """Format minutes as human-readable period."""
    if minutes >= 24 * 60:
        days = minutes // (24 * 60)
        return f"{days} day{'s' if days > 1 else ''}"
    elif minutes >= 60:
        hours = minutes // 60
        return f"{hours} hour{'s' if hours > 1 else ''}"
    else:
        return f"{minutes} minute{'s' if minutes > 1 else ''}"


def _ble_sync(arg: str) -> None:
    """Sync device history to database."""
    try:
        from bleak import BleakClient
    except ImportError:
        print("Error: bleak library not installed")
        print("Install with: pip install bleak")
        return

    # Parse argument: [device] [period]
    # Period formats: 30m, 1h, 24h, 7d, 10d
    parts = arg.split()
    device_arg = ""
    minutes = DEFAULT_HISTORY_MINS

    if len(parts) >= 1:
        # Check if first arg is a period
        period = _parse_period(parts[0])
        if period is not None:
            minutes = period
        else:
            device_arg = parts[0]
            if len(parts) >= 2:
                period = _parse_period(parts[1])
                if period is not None:
                    minutes = period

    device = _select_device(device_arg)
    if not device:
        return

    device_name = device.get("nickname") or device.get("mac", "?")
    device_type = device.get("type", "unknown")
    ble_uuid = device.get("ble_uuid")
    device_mac = device.get("mac")

    if device_type != "air":
        print(f"History sync for {device_type} devices not yet supported.")
        return

    print(f"Syncing history from {device_name}")
    print(f"  Type:    {device_type}")
    print(f"  Period:  {_format_period(minutes)}")
    print(f"  BLE:     {ble_uuid}")
    print()

    # Build nickname lookup
    device_lookup = build_device_lookup()

    spinner = Spinner("Connecting")
    spinner.start()
    connected = False

    def on_reading(reading):
        nonlocal connected
        if not connected:
            connected = True
            spinner.stop()
            print(f"Connected. Downloading history...\n")
            print(separator_line())

        print(format_reading(reading, device_lookup))

    try:
        readings = asyncio.run(download_history(
            ble_uuid=ble_uuid,
            device_mac=device_mac,
            device_type=device_type,
            minutes=minutes,
            on_reading=on_reading,
        ))

        if not connected:
            spinner.stop()
            print("Connected but no data received.\n")
        else:
            print(separator_line())

        if readings:
            # Store readings in database
            from ruuvi_data.config import load_config as load_typed_config
            from ruuvi_data.storage import SensorStorage
            from pathlib import Path

            config_path = Path(__file__).parent.parent.parent / "config.yaml"
            typed_config = load_typed_config(config_path)

            storage = SensorStorage(typed_config.storage.path)
            stored = 0
            for r in readings:
                if storage.insert(r.to_sensor_reading()):
                    stored += 1

            print(f"\nDone. Received {len(readings)} readings, stored {stored} new.")
        else:
            print("No readings received.")

    except NotImplementedError as e:
        spinner.stop()
        print(f"Error: {e}")
    except Exception as e:
        spinner.stop()
        print(f"Error: {type(e).__name__}: {e}")


def _ble_history(arg: str) -> None:
    """Display device history without storing."""
    try:
        from bleak import BleakClient
    except ImportError:
        print("Error: bleak library not installed")
        print("Install with: pip install bleak")
        return

    # Parse argument: [device] [period]
    # Period formats: 30m, 1h, 24h, 7d, 10d
    parts = arg.split()
    device_arg = ""
    minutes = DEFAULT_HISTORY_MINS

    if len(parts) >= 1:
        # Check if first arg is a period
        period = _parse_period(parts[0])
        if period is not None:
            minutes = period
        else:
            device_arg = parts[0]
            if len(parts) >= 2:
                period = _parse_period(parts[1])
                if period is not None:
                    minutes = period

    device = _select_device(device_arg)
    if not device:
        return

    device_name = device.get("nickname") or device.get("mac", "?")
    device_type = device.get("type", "unknown")
    ble_uuid = device.get("ble_uuid")
    device_mac = device.get("mac")

    if device_type != "air":
        print(f"History for {device_type} devices not yet supported.")
        return

    print(f"Reading history from {device_name}")
    print(f"  Type:    {device_type}")
    print(f"  Period:  {_format_period(minutes)}")
    print(f"  BLE:     {ble_uuid}")
    print()

    # Build nickname lookup
    device_lookup = build_device_lookup()

    spinner = Spinner("Connecting")
    spinner.start()
    connected = False

    def on_reading(reading):
        nonlocal connected
        if not connected:
            connected = True
            spinner.stop()
            print(f"Connected. Downloading history...\n")
            print(separator_line())

        print(format_reading(reading, device_lookup))

    try:
        readings = asyncio.run(download_history(
            ble_uuid=ble_uuid,
            device_mac=device_mac,
            device_type=device_type,
            minutes=minutes,
            on_reading=on_reading,
        ))

        if not connected:
            spinner.stop()
            print("Connected but no data received.\n")
        else:
            print(separator_line())

        print(f"\nDone. Received {len(readings)} readings.")

    except NotImplementedError as e:
        spinner.stop()
        print(f"Error: {e}")
    except Exception as e:
        spinner.stop()
        print(f"Error: {type(e).__name__}: {e}")
