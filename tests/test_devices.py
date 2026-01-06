"""Tests for device management."""

import tempfile
from pathlib import Path

import pytest

from ruuvi_data.config import DeviceConfig
from ruuvi_data.devices import (
    _generate_nickname,
    auto_register_device,
    get_device,
    load_devices,
    load_site,
    save_devices,
    upsert_device,
)


@pytest.fixture
def temp_devices_path():
    """Create a temporary devices.yaml path."""
    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
        yield Path(f.name)


class TestGenerateNickname:
    """Tests for nickname generation."""

    def test_empty_devices(self, temp_devices_path):
        """First device of type gets number 1."""
        save_devices([], temp_devices_path)
        assert _generate_nickname("air", temp_devices_path) == "air1"
        assert _generate_nickname("tag", temp_devices_path) == "tag1"
        assert _generate_nickname("unknown", temp_devices_path) == "unknown1"

    def test_increments_number(self, temp_devices_path):
        """Each new device gets incrementing number."""
        devices = [
            DeviceConfig(mac="AA:BB:CC:DD:EE:01", type="air", nickname="air1"),
        ]
        save_devices(devices, temp_devices_path)
        assert _generate_nickname("air", temp_devices_path) == "air2"

    def test_fills_gaps(self, temp_devices_path):
        """Should fill gaps in numbering."""
        devices = [
            DeviceConfig(mac="AA:BB:CC:DD:EE:01", type="air", nickname="air1"),
            DeviceConfig(mac="AA:BB:CC:DD:EE:03", type="air", nickname="air3"),
        ]
        save_devices(devices, temp_devices_path)
        # Should get air2, not air4
        assert _generate_nickname("air", temp_devices_path) == "air2"

    def test_different_types_independent(self, temp_devices_path):
        """Numbering is independent per type."""
        devices = [
            DeviceConfig(mac="AA:BB:CC:DD:EE:01", type="air", nickname="air1"),
            DeviceConfig(mac="AA:BB:CC:DD:EE:02", type="air", nickname="air2"),
            DeviceConfig(mac="AA:BB:CC:DD:EE:03", type="tag", nickname="tag1"),
        ]
        save_devices(devices, temp_devices_path)
        assert _generate_nickname("air", temp_devices_path) == "air3"
        assert _generate_nickname("tag", temp_devices_path) == "tag2"

    def test_ignores_non_numeric_suffixes(self, temp_devices_path):
        """Custom nicknames without numbers are ignored."""
        devices = [
            DeviceConfig(mac="AA:BB:CC:DD:EE:01", type="air", nickname="air1"),
            DeviceConfig(mac="AA:BB:CC:DD:EE:02", type="air", nickname="office"),
        ]
        save_devices(devices, temp_devices_path)
        # "office" doesn't count, so next is air2
        assert _generate_nickname("air", temp_devices_path) == "air2"

    def test_handles_renamed_devices(self, temp_devices_path):
        """Renamed devices don't affect numbering."""
        devices = [
            DeviceConfig(mac="AA:BB:CC:DD:EE:01", type="air", nickname="Living Room"),
            DeviceConfig(mac="AA:BB:CC:DD:EE:02", type="air", nickname="air2"),
        ]
        save_devices(devices, temp_devices_path)
        # air1 is available since first device was renamed
        assert _generate_nickname("air", temp_devices_path) == "air1"


class TestAutoRegisterDevice:
    """Tests for auto-registration."""

    def test_registers_unknown_device(self, temp_devices_path):
        """Unknown device is auto-registered."""
        save_devices([], temp_devices_path)

        result = auto_register_device(
            mac="AA:BB:CC:DD:EE:FF",
            data_format=225,  # air
            path=temp_devices_path,
        )

        assert result is True
        device = get_device("AA:BB:CC:DD:EE:FF", temp_devices_path)
        assert device is not None
        assert device.type == "air"
        assert device.nickname == "air1"

    def test_skips_known_device(self, temp_devices_path):
        """Known device is not modified."""
        devices = [
            DeviceConfig(
                mac="AA:BB:CC:DD:EE:FF",
                type="air",
                nickname="Office",
                description="My office sensor",
            ),
        ]
        save_devices(devices, temp_devices_path)

        result = auto_register_device(
            mac="AA:BB:CC:DD:EE:FF",
            data_format=225,
            path=temp_devices_path,
        )

        assert result is False
        device = get_device("AA:BB:CC:DD:EE:FF", temp_devices_path)
        assert device.nickname == "Office"  # Not changed
        assert device.description == "My office sensor"  # Not changed

    def test_detects_air_type(self, temp_devices_path):
        """Data format 225 (0xE1) is detected as air."""
        save_devices([], temp_devices_path)
        auto_register_device("AA:BB:CC:DD:EE:FF", data_format=225, path=temp_devices_path)

        device = get_device("AA:BB:CC:DD:EE:FF", temp_devices_path)
        assert device.type == "air"

    def test_detects_tag_type(self, temp_devices_path):
        """Data format 5 is detected as tag."""
        save_devices([], temp_devices_path)
        auto_register_device("AA:BB:CC:DD:EE:FF", data_format=5, path=temp_devices_path)

        device = get_device("AA:BB:CC:DD:EE:FF", temp_devices_path)
        assert device.type == "tag"

    def test_handles_unknown_format(self, temp_devices_path):
        """Unknown data format is handled gracefully."""
        save_devices([], temp_devices_path)
        auto_register_device("AA:BB:CC:DD:EE:FF", data_format=99, path=temp_devices_path)

        device = get_device("AA:BB:CC:DD:EE:FF", temp_devices_path)
        assert device.type == "unknown"
        assert device.nickname == "unknown1"

    def test_handles_none_format(self, temp_devices_path):
        """None data format is handled gracefully."""
        save_devices([], temp_devices_path)
        auto_register_device("AA:BB:CC:DD:EE:FF", data_format=None, path=temp_devices_path)

        device = get_device("AA:BB:CC:DD:EE:FF", temp_devices_path)
        assert device.type == "unknown"

    def test_case_insensitive_mac(self, temp_devices_path):
        """MAC comparison is case-insensitive."""
        devices = [
            DeviceConfig(mac="aa:bb:cc:dd:ee:ff", type="air", nickname="existing"),
        ]
        save_devices(devices, temp_devices_path)

        # Should recognize as existing device
        result = auto_register_device(
            mac="AA:BB:CC:DD:EE:FF",
            data_format=225,
            path=temp_devices_path,
        )
        assert result is False

    def test_multiple_devices_numbered(self, temp_devices_path):
        """Multiple auto-registered devices get incrementing numbers."""
        save_devices([], temp_devices_path)

        auto_register_device("AA:BB:CC:DD:EE:01", data_format=225, path=temp_devices_path)
        auto_register_device("AA:BB:CC:DD:EE:02", data_format=225, path=temp_devices_path)
        auto_register_device("AA:BB:CC:DD:EE:03", data_format=5, path=temp_devices_path)

        devices = load_devices(temp_devices_path)
        nicknames = {d.nickname for d in devices}
        assert nicknames == {"air1", "air2", "tag1"}


class TestLoadSite:
    """Tests for site context loading."""

    def test_returns_site_when_present(self, temp_devices_path):
        """Returns site string when configured."""
        with open(temp_devices_path, "w") as f:
            f.write('site: "Home in the tropics. Hot and humid."\n\ndevices: []\n')

        site = load_site(temp_devices_path)
        assert site == "Home in the tropics. Hot and humid."

    def test_returns_none_when_missing(self, temp_devices_path):
        """Returns None when site is not configured."""
        save_devices([], temp_devices_path)

        site = load_site(temp_devices_path)
        assert site is None

    def test_returns_none_for_nonexistent_file(self):
        """Returns None for nonexistent file."""
        site = load_site("/nonexistent/path/devices.yaml")
        assert site is None

    def test_multiline_site(self, temp_devices_path):
        """Handles multiline site descriptions."""
        with open(temp_devices_path, "w") as f:
            f.write('site: "Line 1. Line 2."\n\ndevices: []\n')

        site = load_site(temp_devices_path)
        assert site == "Line 1. Line 2."
