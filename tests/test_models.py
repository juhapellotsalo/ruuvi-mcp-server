"""Tests for data models and formatting."""

from datetime import datetime

from ruuvi_data.models import (
    SensorReading,
    GatewayReading,
    format_reading,
    get_sensor_type,
)


class TestSensorType:
    """Tests for sensor type detection."""

    def test_format_5_is_tag(self):
        assert get_sensor_type(5) == "tag"

    def test_format_225_is_air(self):
        assert get_sensor_type(225) == "air"

    def test_format_e1_is_air(self):
        assert get_sensor_type(0xE1) == "air"

    def test_format_6_is_air(self):
        assert get_sensor_type(6) == "air"

    def test_unknown_format(self):
        assert get_sensor_type(99) == "unknown"

    def test_none_format(self):
        assert get_sensor_type(None) == "unknown"


class TestFormatMetrics:
    """Tests for SensorReading.format_metrics()."""

    def test_all_fields(self):
        reading = SensorReading(
            device_id="test",
            timestamp=datetime.now(),
            temperature=23.0,
            humidity=55.0,
            pressure=97600,
            co2=550,
            pm_2_5=15.5,
            voc=88,
            nox=1,
        )

        metrics = reading.format_metrics()

        assert "T:23.0°C" in metrics
        assert "H:55%" in metrics
        assert "P:976hPa" in metrics
        assert "CO2:550" in metrics
        assert "PM2.5:15.5" in metrics
        assert "VOC:88" in metrics
        assert "NOx:1" in metrics

    def test_partial_fields(self):
        """Should only include non-None fields."""
        reading = SensorReading(
            device_id="test",
            timestamp=datetime.now(),
            temperature=23.0,
            humidity=55.0,
            # No pressure, co2, etc.
        )

        metrics = reading.format_metrics()

        assert "T:23.0°C" in metrics
        assert "H:55%" in metrics
        assert "P:" not in metrics
        assert "CO2:" not in metrics

    def test_pressure_conversion(self):
        """Pressure should be converted from Pa to hPa."""
        reading = SensorReading(
            device_id="test",
            timestamp=datetime.now(),
            pressure=101325,  # Pa
        )

        metrics = reading.format_metrics()

        assert "P:1013hPa" in metrics


class TestFormatReading:
    """Tests for format_reading() function."""

    def test_basic_format(self):
        reading = GatewayReading(
            device_id="AA:BB:CC:DD:EE:FF",
            timestamp=datetime(2024, 1, 1, 12, 30, 45),
            measurement_sequence=1,
            data_format=225,
            temperature=23.0,
        )

        result = format_reading(reading)

        assert "12:30:45" in result
        assert "air/" in result
        assert "T:23.0°C" in result

    def test_with_nickname(self):
        reading = GatewayReading(
            device_id="AA:BB:CC:DD:EE:FF",
            timestamp=datetime(2024, 1, 1, 12, 30, 45),
            measurement_sequence=1,
            data_format=225,
            temperature=23.0,
        )

        device_lookup = {"AA:BB:CC:DD:EE:FF": "Office"}
        result = format_reading(reading, device_lookup)

        assert "Office" in result
        assert "AA:BB:CC:DD:EE:FF" not in result

    def test_nickname_case_insensitive(self):
        """Device lookup should be case-insensitive."""
        reading = GatewayReading(
            device_id="aa:bb:cc:dd:ee:ff",  # lowercase
            timestamp=datetime(2024, 1, 1, 12, 30, 45),
            measurement_sequence=1,
        )

        device_lookup = {"AA:BB:CC:DD:EE:FF": "Office"}  # uppercase
        result = format_reading(reading, device_lookup)

        assert "Office" in result


class TestGatewayReading:
    """Tests for GatewayReading."""

    def test_sensor_type_property(self):
        reading = GatewayReading(
            device_id="test",
            timestamp=datetime.now(),
            measurement_sequence=1,
            data_format=225,
        )
        assert reading.sensor_type == "air"

    def test_to_sensor_reading(self):
        """Should convert to SensorReading preserving all fields."""
        gateway = GatewayReading(
            device_id="AA:BB:CC:DD:EE:FF",
            timestamp=datetime.now(),
            measurement_sequence=12345,
            data_format=225,
            temperature=23.0,
            humidity=55.0,
            co2=550,
        )

        sensor = gateway.to_sensor_reading()

        assert sensor.device_id == gateway.device_id
        assert sensor.measurement_sequence == gateway.measurement_sequence
        assert sensor.temperature == gateway.temperature
        assert sensor.humidity == gateway.humidity
        assert sensor.co2 == gateway.co2
