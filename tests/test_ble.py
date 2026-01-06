"""Tests for BLE utility functions."""

import struct
from datetime import datetime

import pytest

from cli.commands.ble import _format_period, _parse_period
from ruuvi_data.ble import decode_air_record


class TestParsePeriod:
    """Tests for period string parsing."""

    def test_minutes(self):
        assert _parse_period("30m") == 30
        assert _parse_period("1m") == 1
        assert _parse_period("120m") == 120

    def test_hours(self):
        assert _parse_period("1h") == 60
        assert _parse_period("24h") == 24 * 60
        assert _parse_period("12h") == 12 * 60

    def test_days(self):
        assert _parse_period("1d") == 24 * 60
        assert _parse_period("7d") == 7 * 24 * 60
        assert _parse_period("10d") == 10 * 24 * 60

    def test_uppercase(self):
        assert _parse_period("30M") == 30
        assert _parse_period("1H") == 60
        assert _parse_period("7D") == 7 * 24 * 60

    def test_raw_number_as_minutes(self):
        """Raw numbers should be interpreted as minutes."""
        assert _parse_period("30") == 30
        assert _parse_period("1440") == 1440

    def test_whitespace(self):
        assert _parse_period("  30m  ") == 30
        assert _parse_period(" 1h ") == 60

    def test_empty(self):
        assert _parse_period("") is None
        assert _parse_period(None) is None

    def test_invalid(self):
        assert _parse_period("abc") is None
        assert _parse_period("30x") is None
        assert _parse_period("h") is None


class TestFormatPeriod:
    """Tests for period formatting."""

    def test_minutes(self):
        assert _format_period(1) == "1 minute"
        assert _format_period(30) == "30 minutes"
        assert _format_period(59) == "59 minutes"

    def test_hours(self):
        assert _format_period(60) == "1 hour"
        assert _format_period(120) == "2 hours"
        assert _format_period(180) == "3 hours"
        assert _format_period(23 * 60) == "23 hours"

    def test_days(self):
        assert _format_period(24 * 60) == "1 day"
        assert _format_period(2 * 24 * 60) == "2 days"
        assert _format_period(7 * 24 * 60) == "7 days"
        assert _format_period(10 * 24 * 60) == "10 days"

    def test_partial_days_show_as_hours(self):
        """Partial days should round down to hours."""
        assert _format_period(25 * 60) == "1 day"  # 1 day 1 hour -> 1 day


class TestDecodeAirRecord:
    """Tests for Ruuvi Air history record decoding."""

    def _make_record(
        self,
        timestamp: int = 1700000000,
        data_format: int = 6,
        temperature: float = 22.5,
        humidity: float = 45.0,
        pressure: int = 101325,
        pm_1_0: float = 5.0,
        pm_2_5: float = 10.0,
        pm_4_0: float = 15.0,
        pm_10_0: float = 20.0,
        co2: int = 500,
        voc: int = 100,
        nox: int = 50,
        seq: int = 12345,
    ) -> bytes:
        """Build a test record with the given values."""
        record = bytearray(33)

        # Timestamp (big-endian uint32)
        struct.pack_into(">I", record, 0, timestamp)

        # Data format
        record[4] = data_format

        # Temperature (big-endian int16, * 200)
        temp_raw = int(temperature * 200)
        struct.pack_into(">h", record, 5, temp_raw)

        # Humidity (big-endian uint16, * 400)
        hum_raw = int(humidity * 400)
        struct.pack_into(">H", record, 7, hum_raw)

        # Pressure (big-endian uint16, - 50000)
        pres_raw = pressure - 50000
        struct.pack_into(">H", record, 9, pres_raw)

        # PM values (big-endian uint16, * 10)
        struct.pack_into(">H", record, 11, int(pm_1_0 * 10))
        struct.pack_into(">H", record, 13, int(pm_2_5 * 10))
        struct.pack_into(">H", record, 15, int(pm_4_0 * 10))
        struct.pack_into(">H", record, 17, int(pm_10_0 * 10))

        # CO2 (big-endian uint16)
        struct.pack_into(">H", record, 19, co2)

        # VOC and NOx (8-bit each)
        record[21] = voc
        record[22] = nox

        # Measurement sequence (3 bytes at offset 29-31)
        record[29] = (seq >> 16) & 0xFF
        record[30] = (seq >> 8) & 0xFF
        record[31] = seq & 0xFF

        return bytes(record)

    def test_basic_decode(self):
        """Test basic decoding of a valid record."""
        mac = "AA:BB:CC:DD:EE:FF"
        record = self._make_record(
            timestamp=1700000000,
            temperature=22.5,
            humidity=45.0,
            pressure=101325,
            co2=500,
        )

        result = decode_air_record(record, mac)

        assert result is not None
        assert result.device_id == mac
        assert result.temperature == 22.5
        assert result.humidity == 45.0
        assert result.pressure == 101325
        assert result.co2 == 500

    def test_timestamp_conversion(self):
        """Test that Unix timestamp is correctly converted to datetime."""
        mac = "AA:BB:CC:DD:EE:FF"
        timestamp = 1700000000  # 2023-11-14 22:13:20 UTC
        record = self._make_record(timestamp=timestamp)

        result = decode_air_record(record, mac)

        assert result is not None
        expected_dt = datetime.fromtimestamp(timestamp)
        assert result.timestamp == expected_dt

    def test_pm_values(self):
        """Test PM1.0, PM2.5, PM4.0, PM10.0 decoding."""
        mac = "AA:BB:CC:DD:EE:FF"
        record = self._make_record(
            pm_1_0=5.5,
            pm_2_5=10.3,
            pm_4_0=15.7,
            pm_10_0=20.1,
        )

        result = decode_air_record(record, mac)

        assert result is not None
        assert result.pm_1_0 == 5.5
        assert result.pm_2_5 == 10.3
        assert result.pm_4_0 == 15.7
        assert result.pm_10_0 == 20.1

    def test_voc_nox(self):
        """Test VOC and NOx index decoding."""
        mac = "AA:BB:CC:DD:EE:FF"
        record = self._make_record(voc=128, nox=64)

        result = decode_air_record(record, mac)

        assert result is not None
        assert result.voc == 128
        assert result.nox == 64

    def test_measurement_sequence(self):
        """Test 24-bit measurement sequence decoding."""
        mac = "AA:BB:CC:DD:EE:FF"
        record = self._make_record(seq=0x123456)

        result = decode_air_record(record, mac)

        assert result is not None
        assert result.measurement_sequence == 0x123456

    def test_negative_temperature(self):
        """Test negative temperature values."""
        mac = "AA:BB:CC:DD:EE:FF"
        record = self._make_record(temperature=-5.5)

        result = decode_air_record(record, mac)

        assert result is not None
        assert result.temperature == -5.5

    def test_too_short(self):
        """Test that records that are too short return None."""
        result = decode_air_record(b"\x00" * 10, "AA:BB:CC:DD:EE:FF")
        assert result is None

    def test_invalid_timestamp_too_old(self):
        """Test that timestamps before 2020 are rejected."""
        mac = "AA:BB:CC:DD:EE:FF"
        record = self._make_record(timestamp=1500000000)  # 2017

        result = decode_air_record(record, mac)

        assert result is None

    def test_invalid_timestamp_too_new(self):
        """Test that timestamps after 2030 are rejected."""
        mac = "AA:BB:CC:DD:EE:FF"
        record = self._make_record(timestamp=2000000000)  # 2033

        result = decode_air_record(record, mac)

        assert result is None


class TestParsePeriodRoundTrip:
    """Test that parse and format are consistent."""

    def test_round_trip_days(self):
        """Parsing a formatted period should give the same value."""
        for days in [1, 2, 7, 10]:
            minutes = days * 24 * 60
            formatted = _format_period(minutes)
            # Extract number from "X day(s)"
            num = int(formatted.split()[0])
            assert num == days

    def test_round_trip_hours(self):
        """Parsing a formatted period should give the same value."""
        for hours in [1, 2, 12, 23]:
            minutes = hours * 60
            formatted = _format_period(minutes)
            num = int(formatted.split()[0])
            assert num == hours
