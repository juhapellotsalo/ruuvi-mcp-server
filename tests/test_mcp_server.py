"""Tests for MCP server response formatting.

Verifies all data points are present and correctly populated from source data.
"""

from datetime import datetime
from unittest.mock import patch

import pytest

from ruuvi_data.models import SensorReading
from ruuvi_mcp.server import (
    _format_reading,
    _format_current_reading,
    _calculate_summary,
    _bucket_aggregate,
    get_current,
    query,
)


# --- Fixtures: Complete readings with all fields ---


def make_tag_reading(**overrides) -> SensorReading:
    """Create a RuuviTag reading with all fields populated."""
    defaults = {
        "device_id": "AA:BB:CC:DD:EE:FF",
        "timestamp": datetime(2025, 1, 15, 12, 0, 0),
        "data_format": 5,
        "temperature": 20.5,
        "humidity": 65.0,
        "pressure": 101325,  # Pa
        "acceleration_x": -0.048,
        "acceleration_y": 0.028,
        "acceleration_z": 1.04,
        "battery_voltage": 2.995,
        "movement_counter": 42,
        "tx_power": 4,
        "rssi": -70,
        "measurement_sequence": 12345,
    }
    defaults.update(overrides)
    return SensorReading(**defaults)


def make_air_reading(**overrides) -> SensorReading:
    """Create a Ruuvi Air reading with all fields populated."""
    defaults = {
        "device_id": "11:22:33:44:55:66",
        "timestamp": datetime(2025, 1, 15, 12, 0, 0),
        "data_format": 0xE1,
        "temperature": 22.0,
        "humidity": 55.0,
        "pressure": 101500,  # Pa
        "co2": 800,
        "pm_1_0": 5.2,
        "pm_2_5": 10.5,
        "pm_4_0": 15.3,
        "pm_10_0": 20.1,
        "voc": 105,
        "nox": 50,
        "luminosity": 250.5,
        "rssi": -65,
        "measurement_sequence": 67890,
    }
    defaults.update(overrides)
    return SensorReading(**defaults)


# --- Tests for _format_reading (compact query format) ---


class TestFormatReadingTag:
    """Test _format_reading output for RuuviTag readings."""

    def test_all_fields_present(self):
        reading = make_tag_reading()
        result = _format_reading(reading, include_device=False)

        assert "t" in result
        assert "temperature" in result
        assert "humidity" in result
        assert "pressure" in result
        assert "accel" in result
        assert "battery" in result
        assert "movement" in result
        assert "tx_power" in result
        assert "rssi" in result

    def test_acceleration_is_xyz_array(self):
        reading = make_tag_reading()
        result = _format_reading(reading, include_device=False)

        assert isinstance(result["accel"], list)
        assert len(result["accel"]) == 3
        assert result["accel"][0] == -0.048  # x
        assert result["accel"][1] == 0.028  # y
        assert result["accel"][2] == 1.04  # z

    def test_pressure_converted_to_hpa(self):
        reading = make_tag_reading(pressure=101325)
        result = _format_reading(reading, include_device=False)

        assert result["pressure"] == 1013.2  # Pa / 100 = hPa

    def test_battery_rounded_to_2_decimals(self):
        reading = make_tag_reading(battery_voltage=2.9876)
        result = _format_reading(reading, include_device=False)

        assert result["battery"] == 2.99

    def test_no_air_fields(self):
        """Tag readings should not have air quality fields."""
        reading = make_tag_reading()
        result = _format_reading(reading, include_device=False)

        assert "co2" not in result
        assert "pm_1_0" not in result
        assert "pm_2_5" not in result
        assert "voc" not in result
        assert "nox" not in result


class TestFormatReadingAir:
    """Test _format_reading output for Ruuvi Air readings."""

    def test_all_fields_present(self):
        reading = make_air_reading()
        result = _format_reading(reading, include_device=False)

        assert "t" in result
        assert "temperature" in result
        assert "humidity" in result
        assert "pressure" in result
        assert "co2" in result
        assert "pm_1_0" in result
        assert "pm_2_5" in result
        assert "pm_4_0" in result
        assert "pm_10_0" in result
        assert "voc" in result
        assert "nox" in result
        assert "rssi" in result

    def test_no_tag_fields(self):
        """Air readings should not have motion/power fields."""
        reading = make_air_reading()
        result = _format_reading(reading, include_device=False)

        assert "accel" not in result
        assert "battery" not in result
        assert "movement" not in result
        assert "tx_power" not in result


# --- Tests for _format_current_reading (verbose get_current format) ---


class TestFormatCurrentReadingTag:
    """Test _format_current_reading output for RuuviTag."""

    def test_all_fields_present(self):
        reading = make_tag_reading()
        result = _format_current_reading(reading)

        assert "timestamp" in result
        assert "device_id" in result
        assert "device_type" in result
        assert "temperature" in result
        assert "humidity" in result
        assert "pressure" in result
        assert "acceleration" in result
        assert "battery" in result
        assert "movement_counter" in result
        assert "tx_power" in result
        assert "rssi" in result

    def test_acceleration_has_xyz_and_unit(self):
        reading = make_tag_reading()
        result = _format_current_reading(reading)

        accel = result["acceleration"]
        assert accel["x"] == -0.048
        assert accel["y"] == 0.028
        assert accel["z"] == 1.04
        assert accel["unit"] == "G"

    def test_battery_has_value_and_unit(self):
        reading = make_tag_reading()
        result = _format_current_reading(reading)

        assert result["battery"]["value"] == 3.0
        assert result["battery"]["unit"] == "V"

    def test_humidity_has_health_status(self):
        reading = make_tag_reading(humidity=65.0)
        result = _format_current_reading(reading)

        assert "status" in result["humidity"]
        assert result["humidity"]["status"] == "good"

    def test_device_type_is_tag(self):
        reading = make_tag_reading()
        result = _format_current_reading(reading)

        assert result["device_type"] == "tag"


class TestFormatCurrentReadingAir:
    """Test _format_current_reading output for Ruuvi Air."""

    def test_all_fields_present(self):
        reading = make_air_reading()
        result = _format_current_reading(reading)

        assert "co2" in result
        assert "pm_1_0" in result
        assert "pm_2_5" in result
        assert "pm_4_0" in result
        assert "pm_10_0" in result
        assert "voc" in result
        assert "nox" in result

    def test_co2_has_health_status(self):
        reading = make_air_reading(co2=800)
        result = _format_current_reading(reading)

        assert result["co2"]["status"] == "good"

    def test_co2_elevated_status(self):
        reading = make_air_reading(co2=950)  # 801-1000 is elevated
        result = _format_current_reading(reading)

        assert result["co2"]["status"] == "elevated"

    def test_co2_poor_status(self):
        reading = make_air_reading(co2=1600)
        result = _format_current_reading(reading)

        assert result["co2"]["status"] == "poor"

    def test_device_type_is_air(self):
        reading = make_air_reading()
        result = _format_current_reading(reading)

        assert result["device_type"] == "air"


# --- Tests for _calculate_summary ---


class TestCalculateSummary:
    """Test summary statistics calculation."""

    def test_tag_summary_includes_battery(self):
        readings = [
            make_tag_reading(battery_voltage=3.0),
            make_tag_reading(battery_voltage=2.9),
            make_tag_reading(battery_voltage=2.95),
        ]
        result = _calculate_summary(readings)

        assert "battery" in result
        assert result["battery"]["min"] == 2.9
        assert result["battery"]["max"] == 3.0
        assert result["battery"]["unit"] == "V"

    def test_tag_summary_includes_movement_range(self):
        readings = [
            make_tag_reading(movement_counter=40),
            make_tag_reading(movement_counter=42),
            make_tag_reading(movement_counter=45),
        ]
        result = _calculate_summary(readings)

        assert "movement" in result
        assert result["movement"]["min"] == 40
        assert result["movement"]["max"] == 45

    def test_air_summary_includes_co2_stats(self):
        readings = [
            make_air_reading(co2=700),
            make_air_reading(co2=900),
            make_air_reading(co2=800),
        ]
        result = _calculate_summary(readings)

        assert "co2" in result
        assert result["co2"]["min"] == 700
        assert result["co2"]["max"] == 900
        assert result["co2"]["avg"] == 800

    def test_empty_readings(self):
        result = _calculate_summary([])
        assert result == {}


# --- Tests for _bucket_aggregate ---


class TestBucketAggregate:
    """Test time bucket aggregation."""

    def test_tag_bucket_includes_accel_array(self):
        readings = [
            make_tag_reading(acceleration_x=-0.05, acceleration_y=0.03, acceleration_z=1.0),
            make_tag_reading(acceleration_x=-0.04, acceleration_y=0.02, acceleration_z=1.02),
        ]
        result = _bucket_aggregate(readings, bucket_seconds=3600)

        assert len(result) == 1
        bucket = result[0]
        assert "accel" in bucket
        assert isinstance(bucket["accel"], list)
        assert len(bucket["accel"]) == 3

    def test_tag_bucket_includes_battery(self):
        readings = [make_tag_reading(), make_tag_reading()]
        result = _bucket_aggregate(readings, bucket_seconds=3600)

        assert "battery" in result[0]

    def test_tag_bucket_movement_is_max(self):
        """Movement counter should use max within bucket (it's cumulative)."""
        readings = [
            make_tag_reading(movement_counter=40),
            make_tag_reading(movement_counter=45),
        ]
        result = _bucket_aggregate(readings, bucket_seconds=3600)

        assert result[0]["movement"] == 45

    def test_air_bucket_includes_all_pm_values(self):
        readings = [make_air_reading(), make_air_reading()]
        result = _bucket_aggregate(readings, bucket_seconds=3600)

        bucket = result[0]
        assert "co2" in bucket
        assert "pm_1_0" in bucket
        assert "pm_2_5" in bucket
        assert "pm_4_0" in bucket
        assert "pm_10_0" in bucket
        assert "voc" in bucket
        assert "nox" in bucket


# --- Integration tests with mocked storage ---


class TestGetCurrentIntegration:
    """Test get_current() with mocked storage."""

    @patch("ruuvi_mcp.server.storage")
    @patch("ruuvi_mcp.server.get_device")
    def test_returns_all_tag_fields(self, mock_get_device, mock_storage):
        reading = make_tag_reading()
        mock_storage.get_latest.return_value = reading
        mock_get_device.return_value = None

        result = get_current("AA:BB:CC:DD:EE:FF")

        assert "acceleration" in result
        assert "battery" in result
        assert "movement_counter" in result
        assert "tx_power" in result

    @patch("ruuvi_mcp.server.storage")
    @patch("ruuvi_mcp.server.get_device")
    def test_returns_all_air_fields(self, mock_get_device, mock_storage):
        reading = make_air_reading()
        mock_storage.get_latest.return_value = reading
        mock_get_device.return_value = None

        result = get_current("11:22:33:44:55:66")

        assert "co2" in result
        assert "pm_2_5" in result
        assert "voc" in result


class TestQueryIntegration:
    """Test query() with mocked storage."""

    @patch("ruuvi_mcp.server.storage")
    @patch("ruuvi_mcp.server.get_device")
    @patch("ruuvi_mcp.server.get_device_by_nickname")
    def test_returns_all_tag_fields_in_data(
        self, mock_get_nickname, mock_get_device, mock_storage
    ):
        readings = [make_tag_reading(), make_tag_reading()]
        mock_storage.query.return_value = readings
        mock_storage.get_devices.return_value = ["AA:BB:CC:DD:EE:FF"]
        mock_get_device.return_value = None
        mock_get_nickname.return_value = None

        result = query(start="-1h", device="AA:BB:CC:DD:EE:FF", resolution="raw")

        assert "data" in result
        assert len(result["data"]) > 0
        data_point = result["data"][0]
        assert "accel" in data_point
        assert "battery" in data_point
        assert "movement" in data_point

    @patch("ruuvi_mcp.server.storage")
    @patch("ruuvi_mcp.server.get_device")
    @patch("ruuvi_mcp.server.get_device_by_nickname")
    def test_summary_includes_battery_stats(
        self, mock_get_nickname, mock_get_device, mock_storage
    ):
        readings = [
            make_tag_reading(battery_voltage=3.0),
            make_tag_reading(battery_voltage=2.9),
        ]
        mock_storage.query.return_value = readings
        mock_get_device.return_value = None
        mock_get_nickname.return_value = None

        result = query(start="-1h", device="AA:BB:CC:DD:EE:FF")

        assert "summary" in result
        assert "battery" in result["summary"]
