"""Tests for SQLite storage."""

import tempfile
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from ruuvi_data.models import SensorReading
from ruuvi_data.storage import SensorStorage


@pytest.fixture(autouse=True)
def mock_auto_register():
    """Prevent tests from polluting real devices.yaml."""
    with patch("ruuvi_data.devices.auto_register_device"):
        yield


@pytest.fixture
def storage():
    """Create a temporary storage instance."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        yield SensorStorage(f.name)


@pytest.fixture
def sample_reading():
    """Create a sample reading."""
    return SensorReading(
        device_id="AA:BB:CC:DD:EE:FF",
        timestamp=datetime.now(),
        measurement_sequence=12345,
        data_format=225,
        temperature=23.0,
        humidity=55.0,
        pressure=97600,
        co2=550,
        voc=88,
        nox=1,
        pm_2_5=15.5,
    )


class TestInsert:
    """Tests for inserting readings."""

    def test_insert_returns_true(self, storage, sample_reading):
        assert storage.insert(sample_reading) is True

    def test_insert_increments_count(self, storage, sample_reading):
        assert storage.count() == 0
        storage.insert(sample_reading)
        assert storage.count() == 1


class TestDeduplication:
    """Tests for duplicate handling based on device_id + timestamp."""

    def test_duplicate_same_timestamp_rejected(self, storage):
        """Same device + timestamp should be rejected."""
        ts = datetime(2024, 1, 1, 12, 0, 0)
        reading1 = SensorReading(
            device_id="AA:BB:CC:DD:EE:FF",
            timestamp=ts,
            temperature=20.0,
        )
        reading2 = SensorReading(
            device_id="AA:BB:CC:DD:EE:FF",
            timestamp=ts,  # Same timestamp
            temperature=21.0,  # Different value - still rejected
        )

        assert storage.insert(reading1) is True
        assert storage.insert(reading2) is False
        assert storage.count() == 1

    def test_different_timestamp_accepted(self, storage):
        """Same device with different timestamp should be accepted."""
        reading1 = SensorReading(
            device_id="AA:BB:CC:DD:EE:FF",
            timestamp=datetime(2024, 1, 1, 12, 0, 0),
            temperature=20.0,
        )
        reading2 = SensorReading(
            device_id="AA:BB:CC:DD:EE:FF",
            timestamp=datetime(2024, 1, 1, 12, 0, 1),  # 1 second later
            temperature=21.0,
        )

        assert storage.insert(reading1) is True
        assert storage.insert(reading2) is True
        assert storage.count() == 2

    def test_same_timestamp_different_device_accepted(self, storage):
        """Same timestamp but different device should be accepted."""
        ts = datetime(2024, 1, 1, 12, 0, 0)
        reading1 = SensorReading(
            device_id="AA:BB:CC:DD:EE:01",
            timestamp=ts,
            temperature=20.0,
        )
        reading2 = SensorReading(
            device_id="AA:BB:CC:DD:EE:02",  # Different device
            timestamp=ts,  # Same timestamp - OK
            temperature=21.0,
        )

        assert storage.insert(reading1) is True
        assert storage.insert(reading2) is True
        assert storage.count() == 2


class TestQuery:
    """Tests for querying readings."""

    def test_get_latest(self, storage):
        """Should return most recent reading."""
        old = SensorReading(
            device_id="AA:BB:CC:DD:EE:FF",
            timestamp=datetime.now() - timedelta(hours=1),
            measurement_sequence=1,
            temperature=20.0,
        )
        new = SensorReading(
            device_id="AA:BB:CC:DD:EE:FF",
            timestamp=datetime.now(),
            measurement_sequence=2,
            temperature=25.0,
        )

        storage.insert(old)
        storage.insert(new)

        latest = storage.get_latest()
        assert latest.temperature == 25.0

    def test_get_latest_empty(self, storage):
        """Should return None when no readings."""
        assert storage.get_latest() is None

    def test_query_with_start_time(self, storage):
        """Should filter by start time."""
        old = SensorReading(
            device_id="AA:BB:CC:DD:EE:FF",
            timestamp=datetime.now() - timedelta(hours=2),
            measurement_sequence=1,
            temperature=20.0,
        )
        new = SensorReading(
            device_id="AA:BB:CC:DD:EE:FF",
            timestamp=datetime.now(),
            measurement_sequence=2,
            temperature=25.0,
        )

        storage.insert(old)
        storage.insert(new)

        # Query only last hour
        results = storage.query(start=datetime.now() - timedelta(hours=1))
        assert len(results) == 1
        assert results[0].temperature == 25.0

    def test_get_devices(self, storage):
        """Should return unique device IDs."""
        r1 = SensorReading(
            device_id="AA:BB:CC:DD:EE:FF",
            timestamp=datetime.now(),
            measurement_sequence=1,
        )
        r2 = SensorReading(
            device_id="11:22:33:44:55:66",
            timestamp=datetime.now(),
            measurement_sequence=1,
        )

        storage.insert(r1)
        storage.insert(r2)

        devices = storage.get_devices()
        assert len(devices) == 2
        assert "AA:BB:CC:DD:EE:FF" in devices
        assert "11:22:33:44:55:66" in devices
