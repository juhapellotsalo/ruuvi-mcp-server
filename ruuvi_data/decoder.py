"""Decoder for Ruuvi raw BLE advertisement data.

Supports data format E1 (225) used by Ruuvi Air.
"""

from dataclasses import dataclass


@dataclass
class DecodedData:
    """Decoded sensor values from raw BLE data."""

    data_format: int
    temperature: float | None = None  # °C
    humidity: float | None = None  # % RH
    pressure: float | None = None  # Pa
    pm_1_0: float | None = None  # µg/m³
    pm_2_5: float | None = None  # µg/m³
    pm_4_0: float | None = None  # µg/m³
    pm_10_0: float | None = None  # µg/m³
    co2: int | None = None  # ppm
    voc: int | None = None  # index
    nox: int | None = None  # index
    luminosity: float | None = None  # lux
    measurement_sequence: int | None = None
    mac: str | None = None
    # RuuviTag motion/power fields
    acceleration_x: float | None = None  # G
    acceleration_y: float | None = None  # G
    acceleration_z: float | None = None  # G
    movement_counter: int | None = None
    battery_voltage: float | None = None  # V
    tx_power: int | None = None  # dBm


def decode_raw_data(hex_data: str) -> DecodedData | None:
    """Decode raw Ruuvi BLE advertisement hex string.

    Args:
        hex_data: Hex string from cloud API 'data' field

    Returns:
        DecodedData with parsed values, or None if format unknown
    """
    try:
        data = bytes.fromhex(hex_data)
    except ValueError:
        return None

    # Find manufacturer data (FF followed by 9904 = Ruuvi)
    # Format: [len] FF 99 04 [payload...]
    try:
        # Look for Ruuvi manufacturer ID
        idx = 0
        while idx < len(data) - 4:
            if data[idx] == 0xFF and data[idx + 1] == 0x99 and data[idx + 2] == 0x04:
                # Found it, payload starts after manufacturer ID
                payload = data[idx + 3 :]
                break
            idx += 1
        else:
            # Try without the AD header (payload might start directly)
            if data[0] in (0xE1, 0x06, 0x05):
                payload = data
            else:
                return None
    except (IndexError, ValueError):
        return None

    if len(payload) < 1:
        return None

    data_format = payload[0]

    if data_format == 0xE1:  # 225 - Ruuvi Air Extended
        return _decode_e1(payload)
    elif data_format == 0x06:  # 6 - Ruuvi Air BLE4
        return _decode_06(payload)
    elif data_format == 0x05:  # 5 - RuuviTag RAWv2
        return _decode_05(payload)
    else:
        return DecodedData(data_format=data_format)


def _decode_e1(payload: bytes) -> DecodedData:
    """Decode Ruuvi Air Extended format (E1/225).

    40-byte payload layout:
    0:     data format (0xE1)
    1-2:   temperature (signed, × 0.005 °C)
    3-4:   humidity (× 0.0025 %)
    5-6:   pressure (+ 50000 Pa)
    7-8:   PM 1.0 (× 0.1 µg/m³)
    9-10:  PM 2.5 (× 0.1 µg/m³)
    11-12: PM 4.0 (× 0.1 µg/m³)
    13-14: PM 10.0 (× 0.1 µg/m³)
    15-16: CO₂ (ppm)
    17:    VOC (bits 1-8, MSB)
    18:    NOₓ (bits 1-8, MSB)
    19-21: Luminosity (× 0.01 lux)
    22-24: Reserved
    25-27: Measurement sequence
    28:    Flags (bit 6 = VOC LSB, bit 7 = NOₓ LSB)
    29-33: Reserved
    34-39: MAC address
    """
    if len(payload) < 28:
        return DecodedData(data_format=0xE1)

    def u16(offset: int) -> int:
        return (payload[offset] << 8) | payload[offset + 1]

    def s16(offset: int) -> int:
        val = u16(offset)
        return val if val < 0x8000 else val - 0x10000

    def u24(offset: int) -> int:
        return (payload[offset] << 16) | (payload[offset + 1] << 8) | payload[offset + 2]

    # Temperature (signed)
    temp_raw = s16(1)
    temperature = temp_raw * 0.005 if temp_raw != -32768 else None

    # Humidity
    hum_raw = u16(3)
    humidity = hum_raw * 0.0025 if hum_raw != 0xFFFF else None

    # Pressure
    pres_raw = u16(5)
    pressure = (pres_raw + 50000) if pres_raw != 0xFFFF else None

    # Particulate matter
    pm1_raw = u16(7)
    pm_1_0 = pm1_raw * 0.1 if pm1_raw != 0xFFFF else None

    pm25_raw = u16(9)
    pm_2_5 = pm25_raw * 0.1 if pm25_raw != 0xFFFF else None

    pm4_raw = u16(11)
    pm_4_0 = pm4_raw * 0.1 if pm4_raw != 0xFFFF else None

    pm10_raw = u16(13)
    pm_10_0 = pm10_raw * 0.1 if pm10_raw != 0xFFFF else None

    # CO2
    co2_raw = u16(15)
    co2 = co2_raw if co2_raw != 0xFFFF else None

    # VOC and NOx (9-bit values: byte is MSB, flags bit is LSB)
    # See: https://docs.ruuvi.com/communication/bluetooth-advertisements/data-format-e1
    voc_raw = payload[17]
    nox_raw = payload[18]
    flags = payload[28] if len(payload) > 28 else 0
    voc_lsb = (flags >> 6) & 1
    nox_lsb = (flags >> 7) & 1
    voc = (voc_raw << 1) | voc_lsb if voc_raw != 0xFF else None
    nox = (nox_raw << 1) | nox_lsb if nox_raw != 0xFF else None

    # Luminosity
    lum_raw = u24(19)
    luminosity = lum_raw * 0.01 if lum_raw != 0xFFFFFF else None

    # Measurement sequence
    seq_raw = u24(25) if len(payload) > 27 else None
    measurement_sequence = seq_raw if seq_raw != 0xFFFFFF else None

    # MAC address
    mac = None
    if len(payload) >= 40:
        mac_bytes = payload[34:40]
        mac = ":".join(f"{b:02X}" for b in mac_bytes)

    return DecodedData(
        data_format=0xE1,
        temperature=round(temperature, 2) if temperature else None,
        humidity=round(humidity, 2) if humidity else None,
        pressure=pressure,
        pm_1_0=round(pm_1_0, 1) if pm_1_0 else None,
        pm_2_5=round(pm_2_5, 1) if pm_2_5 else None,
        pm_4_0=round(pm_4_0, 1) if pm_4_0 else None,
        pm_10_0=round(pm_10_0, 1) if pm_10_0 else None,
        co2=co2,
        voc=voc,
        nox=nox,
        luminosity=round(luminosity, 2) if luminosity else None,
        measurement_sequence=measurement_sequence,
        mac=mac,
    )


def _decode_06(payload: bytes) -> DecodedData:
    """Decode Ruuvi Air BLE4 format (06).

    17-byte payload layout (from Android DecodeFormat6.kt):
    0:     data format (0x06)
    1-2:   temperature (signed, / 200 °C)
    3-4:   humidity (/ 400 %)
    5-6:   pressure (+ 50000 Pa)
        7-8:   PM 2.5 (/ 10 µg/m³)
    9-10:  CO₂ (ppm)
    11:    VOC (MSB, LSB in flags bit 6)
    12:    NOₓ (MSB, LSB in flags bit 7)
    13:    Luminosity (logarithmic)
    14:    dBA avg
    15:    Measurement sequence (8-bit)
    16:    Flags
    """
    if len(payload) < 16:
        return DecodedData(data_format=0x06)

    def u16(offset: int) -> int:
        return (payload[offset] << 8) | payload[offset + 1]

    def s16(offset: int) -> int:
        val = u16(offset)
        return val if val < 0x8000 else val - 0x10000

    # Temperature (signed, /200)
    temp_raw = s16(1)
    temperature = temp_raw / 200.0 if temp_raw != -32768 else None

    # Humidity (/400)
    hum_raw = u16(3)
    humidity = hum_raw / 400.0 if hum_raw != 0xFFFF else None

    # Pressure (+50000)
    pres_raw = u16(5)
    pressure = (pres_raw + 50000) if pres_raw != 0xFFFF else None

    # PM 2.5 only in format 6
    pm25_raw = u16(7)
    pm_2_5 = pm25_raw / 10.0 if pm25_raw != 0xFFFF else None

    # CO2
    co2_raw = u16(9)
    co2 = co2_raw if co2_raw != 0xFFFF else None

    # VOC and NOx (9-bit: byte is MSB, flags bit is LSB)
    flags = payload[16] if len(payload) > 16 else 0
    voc_raw = payload[11]
    nox_raw = payload[12]
    voc_lsb = (flags >> 6) & 1
    nox_lsb = (flags >> 7) & 1
    voc = (voc_raw << 1) | voc_lsb if voc_raw != 0xFF else None
    nox = (nox_raw << 1) | nox_lsb if nox_raw != 0xFF else None

    # Measurement sequence (8-bit)
    seq = payload[15] if len(payload) > 15 else None

    return DecodedData(
        data_format=0x06,
        temperature=round(temperature, 2) if temperature else None,
        humidity=round(humidity, 2) if humidity else None,
        pressure=pressure,
        pm_2_5=round(pm_2_5, 1) if pm_2_5 else None,
        co2=co2,
        voc=voc,
        nox=nox,
        measurement_sequence=seq,
    )


def _decode_05(payload: bytes) -> DecodedData:
    """Decode RuuviTag RAWv2 format (05).

    24-byte payload layout:
    0:      Data format (0x05)
    1-2:    Temperature (signed, × 0.005 °C)
    3-4:    Humidity (× 0.0025 %)
    5-6:    Pressure (+ 50000 Pa)
    7-8:    Acceleration X (signed, mG)
    9-10:   Acceleration Y (signed, mG)
    11-12:  Acceleration Z (signed, mG)
    13-14:  Battery voltage (11 bits) + TX power (5 bits)
    15:     Movement counter
    16-17:  Measurement sequence
    18-23:  MAC address
    """
    if len(payload) < 15:
        return DecodedData(data_format=0x05)

    def u16(offset: int) -> int:
        return (payload[offset] << 8) | payload[offset + 1]

    def s16(offset: int) -> int:
        val = u16(offset)
        return val if val < 0x8000 else val - 0x10000

    # Temperature (signed, 0.005 °C)
    temp_raw = s16(1)
    temperature = temp_raw * 0.005 if temp_raw != -32768 else None

    # Humidity (0.0025 %)
    hum_raw = u16(3)
    humidity = hum_raw * 0.0025 if hum_raw != 0xFFFF else None

    # Pressure (+ 50000 Pa)
    pres_raw = u16(5)
    pressure = (pres_raw + 50000) if pres_raw != 0xFFFF else None

    # Acceleration X, Y, Z (signed, mG -> G)
    acc_x_raw = s16(7)
    acc_y_raw = s16(9)
    acc_z_raw = s16(11)
    acceleration_x = acc_x_raw / 1000.0 if acc_x_raw != -32768 else None
    acceleration_y = acc_y_raw / 1000.0 if acc_y_raw != -32768 else None
    acceleration_z = acc_z_raw / 1000.0 if acc_z_raw != -32768 else None

    # Battery voltage (11 bits) + TX power (5 bits)
    power_raw = u16(13)
    battery_voltage = None
    tx_power = None
    if power_raw != 0xFFFF:
        battery_raw = power_raw >> 5  # Upper 11 bits
        tx_raw = power_raw & 0x1F  # Lower 5 bits
        battery_voltage = (battery_raw + 1600) / 1000.0  # mV -> V
        tx_power = (tx_raw * 2) - 40  # dBm

    # Movement counter
    movement_counter = None
    if len(payload) > 15:
        mc = payload[15]
        movement_counter = mc if mc != 0xFF else None

    # Measurement sequence
    measurement_sequence = None
    if len(payload) > 17:
        seq = u16(16)
        measurement_sequence = seq if seq != 0xFFFF else None

    # MAC address
    mac = None
    if len(payload) >= 24:
        mac_bytes = payload[18:24]
        mac = ":".join(f"{b:02X}" for b in mac_bytes)

    return DecodedData(
        data_format=0x05,
        temperature=round(temperature, 2) if temperature else None,
        humidity=round(humidity, 2) if humidity else None,
        pressure=pressure,
        acceleration_x=round(acceleration_x, 3) if acceleration_x is not None else None,
        acceleration_y=round(acceleration_y, 3) if acceleration_y is not None else None,
        acceleration_z=round(acceleration_z, 3) if acceleration_z is not None else None,
        battery_voltage=round(battery_voltage, 3) if battery_voltage is not None else None,
        tx_power=tx_power,
        movement_counter=movement_counter,
        measurement_sequence=measurement_sequence,
        mac=mac,
    )


if __name__ == "__main__":
    # Test with sample data
    test_data = "2BFF9904E111C64BB4B8AC0094009C009E009E03092000FFFFFFFFFFFF1C9553B8FFFFFFFFFFAABBCCDDEEFF030398FC"
    result = decode_raw_data(test_data)
    print(result)
