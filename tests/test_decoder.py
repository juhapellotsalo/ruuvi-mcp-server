"""Tests for BLE advertisement decoder."""

from ruuvi_data.decoder import decode_raw_data


class TestDecodeE1:
    """Tests for Ruuvi Air E1 format (225)."""

    # Sample E1 format data (based on gateway /history format)
    GATEWAY_SAMPLE = {
        "raw": "2BFF9904E112045944B9FE00C000CD00D100D302211C00FFFFFFFFFFFF1DE2F1F8FFFFFFFFFFAABBCCDDEEFF030398FC",
        "temperature": 23.06,
        "humidity": 57.13,
        "pressure": 97614,
        "co2": 545,
        "voc": 57,
        "nox": 1,
        "pm_2_5": 20.5,
        "mac": "AA:BB:CC:DD:EE:FF",
    }

    def test_temperature(self):
        decoded = decode_raw_data(self.GATEWAY_SAMPLE["raw"])
        assert decoded.temperature == self.GATEWAY_SAMPLE["temperature"]

    def test_humidity(self):
        decoded = decode_raw_data(self.GATEWAY_SAMPLE["raw"])
        assert decoded.humidity == self.GATEWAY_SAMPLE["humidity"]

    def test_pressure(self):
        decoded = decode_raw_data(self.GATEWAY_SAMPLE["raw"])
        assert decoded.pressure == self.GATEWAY_SAMPLE["pressure"]

    def test_co2(self):
        decoded = decode_raw_data(self.GATEWAY_SAMPLE["raw"])
        assert decoded.co2 == self.GATEWAY_SAMPLE["co2"]

    def test_voc(self):
        """VOC is 9-bit: byte 17 is MSB, flags bit 6 is LSB."""
        decoded = decode_raw_data(self.GATEWAY_SAMPLE["raw"])
        assert decoded.voc == self.GATEWAY_SAMPLE["voc"]

    def test_nox(self):
        """NOx is 9-bit: byte 18 is MSB, flags bit 7 is LSB."""
        decoded = decode_raw_data(self.GATEWAY_SAMPLE["raw"])
        assert decoded.nox == self.GATEWAY_SAMPLE["nox"]

    def test_pm_2_5(self):
        decoded = decode_raw_data(self.GATEWAY_SAMPLE["raw"])
        assert decoded.pm_2_5 == self.GATEWAY_SAMPLE["pm_2_5"]

    def test_mac(self):
        decoded = decode_raw_data(self.GATEWAY_SAMPLE["raw"])
        assert decoded.mac == self.GATEWAY_SAMPLE["mac"]

    def test_data_format(self):
        decoded = decode_raw_data(self.GATEWAY_SAMPLE["raw"])
        assert decoded.data_format == 0xE1


class TestDecodeE1EdgeCases:
    """Edge cases for 9-bit VOC/NOx decoding."""

    def test_voc_without_flag_bit(self):
        """VOC value where flags bit 6 is 0."""
        # flags = 0x38 = 0b00111000 (bit 6 = 0, bit 7 = 0)
        # voc_raw = 0x40 = 64, nox_raw = 0x01 = 1
        # Expected: voc = (64 << 1) | 0 = 128, nox = (1 << 1) | 0 = 2
        raw = "2BFF9904E112045944B9FE00C000CD00D100D302214001FFFFFFFFFFFF1DE2F138FFFFFFFFFFAABBCCDDEEFF030398FC"
        decoded = decode_raw_data(raw)
        assert decoded.voc == 128
        assert decoded.nox == 2

    def test_voc_with_flag_bit(self):
        """VOC value where flags bit 6 is 1."""
        # flags = 0x78 = 0b01111000 (bit 6 = 1, bit 7 = 0)
        # voc_raw = 0x40 = 64
        # Expected: voc = (64 << 1) | 1 = 129
        raw = "2BFF9904E112045944B9FE00C000CD00D100D302214001FFFFFFFFFFFF1DE2F178FFFFFFFFFFAABBCCDDEEFF030398FC"
        decoded = decode_raw_data(raw)
        assert decoded.voc == 129


class TestDecode06:
    """Tests for Ruuvi Air BLE4 format (06).

    Format 06 is a compact 17-byte BLE4 format used in broadcasts.
    Layout:
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

    def _make_format6(
        self,
        temperature: float = 22.5,
        humidity: float = 45.0,
        pressure: int = 101325,
        pm_2_5: float = 10.0,
        co2: int = 500,
        voc: int = 100,  # 9-bit value
        nox: int = 50,  # 9-bit value
        seq: int = 128,
    ) -> str:
        """Build a format 6 payload hex string."""
        payload = bytearray(17)

        payload[0] = 0x06

        # Temperature: signed int16, /200
        temp_raw = int(temperature * 200)
        payload[1] = (temp_raw >> 8) & 0xFF
        payload[2] = temp_raw & 0xFF

        # Humidity: uint16, /400
        hum_raw = int(humidity * 400)
        payload[3] = (hum_raw >> 8) & 0xFF
        payload[4] = hum_raw & 0xFF

        # Pressure: uint16, +50000
        pres_raw = pressure - 50000
        payload[5] = (pres_raw >> 8) & 0xFF
        payload[6] = pres_raw & 0xFF

        # PM 2.5: uint16, /10
        pm_raw = int(pm_2_5 * 10)
        payload[7] = (pm_raw >> 8) & 0xFF
        payload[8] = pm_raw & 0xFF

        # CO2: uint16
        payload[9] = (co2 >> 8) & 0xFF
        payload[10] = co2 & 0xFF

        # VOC: MSB in byte 11, LSB in flags bit 6
        payload[11] = (voc >> 1) & 0xFF

        # NOx: MSB in byte 12, LSB in flags bit 7
        payload[12] = (nox >> 1) & 0xFF

        # Luminosity (byte 13), dBA (byte 14) - not decoded
        payload[13] = 0x00
        payload[14] = 0x00

        # Measurement sequence (8-bit)
        payload[15] = seq & 0xFF

        # Flags: bit 6 = VOC LSB, bit 7 = NOx LSB
        flags = ((voc & 1) << 6) | ((nox & 1) << 7)
        payload[16] = flags

        return payload.hex()

    def test_data_format(self):
        raw = self._make_format6()
        decoded = decode_raw_data(raw)
        assert decoded.data_format == 0x06

    def test_temperature(self):
        raw = self._make_format6(temperature=22.5)
        decoded = decode_raw_data(raw)
        assert decoded.temperature == 22.5

    def test_negative_temperature(self):
        raw = self._make_format6(temperature=-5.0)
        decoded = decode_raw_data(raw)
        assert decoded.temperature == -5.0

    def test_humidity(self):
        raw = self._make_format6(humidity=45.0)
        decoded = decode_raw_data(raw)
        assert decoded.humidity == 45.0

    def test_pressure(self):
        raw = self._make_format6(pressure=101325)
        decoded = decode_raw_data(raw)
        assert decoded.pressure == 101325

    def test_pm_2_5(self):
        """Format 6 only includes PM2.5 (not PM1.0, PM4.0, PM10.0)."""
        raw = self._make_format6(pm_2_5=15.5)
        decoded = decode_raw_data(raw)
        assert decoded.pm_2_5 == 15.5
        # Other PM values should be None in format 6
        assert decoded.pm_1_0 is None
        assert decoded.pm_4_0 is None
        assert decoded.pm_10_0 is None

    def test_co2(self):
        raw = self._make_format6(co2=800)
        decoded = decode_raw_data(raw)
        assert decoded.co2 == 800

    def test_voc_even(self):
        """VOC with LSB = 0 (even value)."""
        raw = self._make_format6(voc=128)  # Binary: 10000000
        decoded = decode_raw_data(raw)
        assert decoded.voc == 128

    def test_voc_odd(self):
        """VOC with LSB = 1 (odd value)."""
        raw = self._make_format6(voc=129)  # Binary: 10000001
        decoded = decode_raw_data(raw)
        assert decoded.voc == 129

    def test_nox_even(self):
        """NOx with LSB = 0 (even value)."""
        raw = self._make_format6(nox=64)
        decoded = decode_raw_data(raw)
        assert decoded.nox == 64

    def test_nox_odd(self):
        """NOx with LSB = 1 (odd value)."""
        raw = self._make_format6(nox=65)
        decoded = decode_raw_data(raw)
        assert decoded.nox == 65

    def test_measurement_sequence_8bit(self):
        """Format 6 uses 8-bit sequence (0-255)."""
        raw = self._make_format6(seq=200)
        decoded = decode_raw_data(raw)
        assert decoded.measurement_sequence == 200

    def test_no_mac_in_format6(self):
        """Format 6 doesn't include MAC address."""
        raw = self._make_format6()
        decoded = decode_raw_data(raw)
        assert decoded.mac is None


class TestDecode05:
    """Tests for RuuviTag RAWv2 format (05).

    Format 05 is a compact format used by RuuviTag sensors.
    Layout:
    0:     data format (0x05)
    1-2:   temperature (signed, * 0.005 °C)
    3-4:   humidity (* 0.0025 %)
    5-6:   pressure (+ 50000 Pa)
    7-8:   acceleration X
    9-10:  acceleration Y
    11-12: acceleration Z
    13:    power info (battery voltage + TX power)
    14:    movement counter
    15-16: measurement sequence
    17-22: MAC address (optional)
    """

    def _make_format5(
        self,
        temperature: float = 22.5,
        humidity: float = 45.0,
        pressure: int = 101325,
    ) -> str:
        """Build a format 5 payload hex string."""
        payload = bytearray(16)  # Need at least 15 bytes for power field

        payload[0] = 0x05

        # Temperature: signed int16, * 0.005
        temp_raw = int(temperature / 0.005)
        if temp_raw < 0:
            temp_raw += 0x10000
        payload[1] = (temp_raw >> 8) & 0xFF
        payload[2] = temp_raw & 0xFF

        # Humidity: uint16, * 0.0025
        hum_raw = int(humidity / 0.0025)
        payload[3] = (hum_raw >> 8) & 0xFF
        payload[4] = hum_raw & 0xFF

        # Pressure: uint16, + 50000
        pres_raw = pressure - 50000
        payload[5] = (pres_raw >> 8) & 0xFF
        payload[6] = pres_raw & 0xFF

        # Acceleration X, Y, Z (bytes 7-12, padding)
        # Power info (bytes 13-14, padding)
        # Movement counter (byte 15, padding)

        return payload.hex()

    def test_data_format(self):
        raw = self._make_format5()
        decoded = decode_raw_data(raw)
        assert decoded.data_format == 0x05

    def test_temperature(self):
        raw = self._make_format5(temperature=22.5)
        decoded = decode_raw_data(raw)
        assert decoded.temperature == 22.5

    def test_negative_temperature(self):
        raw = self._make_format5(temperature=-5.0)
        decoded = decode_raw_data(raw)
        assert decoded.temperature == -5.0

    def test_humidity(self):
        raw = self._make_format5(humidity=45.0)
        decoded = decode_raw_data(raw)
        assert decoded.humidity == 45.0

    def test_pressure(self):
        raw = self._make_format5(pressure=101325)
        decoded = decode_raw_data(raw)
        assert decoded.pressure == 101325

    def test_no_air_quality_fields(self):
        """Format 05 is RuuviTag - no CO2, PM, VOC, NOx."""
        raw = self._make_format5()
        decoded = decode_raw_data(raw)
        assert decoded.co2 is None
        assert decoded.pm_1_0 is None
        assert decoded.pm_2_5 is None
        assert decoded.voc is None
        assert decoded.nox is None


class TestDecodeInvalid:
    """Tests for invalid input handling."""

    def test_empty_string(self):
        assert decode_raw_data("") is None

    def test_garbage(self):
        assert decode_raw_data("not hex") is None

    def test_too_short(self):
        assert decode_raw_data("FF9904E1") is None

    def test_wrong_manufacturer(self):
        # Different manufacturer ID (not 9904)
        assert decode_raw_data("2BFF1234E112045944B9FE") is None
