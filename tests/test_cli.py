"""Tests for CLI utility functions."""

import pytest

from cli.app import RuuviCLI
from cli.commands.cloud import resolve_device
from cli.commands.devices import validate_mac, validate_type
from cli.commands.status import mask_token


class TestMaskToken:
    """Tests for token masking."""

    def test_none_token(self):
        assert mask_token(None) == "(not set)"

    def test_empty_token(self):
        assert mask_token("") == "(not set)"

    def test_short_token(self):
        """Tokens <= 12 chars should be fully masked."""
        assert mask_token("abc123") == "****"
        assert mask_token("123456789012") == "****"

    def test_normal_token(self):
        """Normal tokens show first/last 4 chars."""
        assert mask_token("abcd1234567890wxyz") == "abcd...wxyz"

    def test_13_char_token(self):
        """Just over threshold should show partial."""
        assert mask_token("1234567890123") == "1234...0123"


class TestValidateMac:
    """Tests for MAC address validation."""

    def test_valid_uppercase(self):
        assert validate_mac("AA:BB:CC:DD:EE:FF") is True

    def test_valid_lowercase(self):
        assert validate_mac("aa:bb:cc:dd:ee:ff") is True

    def test_valid_mixed_case(self):
        assert validate_mac("Aa:Bb:Cc:Dd:Ee:Ff") is True

    def test_invalid_no_colons(self):
        assert validate_mac("AABBCCDDEEFF") is False

    def test_invalid_dashes(self):
        assert validate_mac("AA-BB-CC-DD-EE-FF") is False

    def test_invalid_too_short(self):
        assert validate_mac("AA:BB:CC:DD:EE") is False

    def test_invalid_too_long(self):
        assert validate_mac("AA:BB:CC:DD:EE:FF:00") is False

    def test_invalid_chars(self):
        assert validate_mac("GG:HH:II:JJ:KK:LL") is False

    def test_empty(self):
        assert validate_mac("") is False


class TestValidateType:
    """Tests for device type validation."""

    def test_air_lowercase(self):
        assert validate_type("air") is True

    def test_tag_lowercase(self):
        assert validate_type("tag") is True

    def test_air_uppercase(self):
        assert validate_type("AIR") is True

    def test_tag_mixed_case(self):
        assert validate_type("Tag") is True

    def test_invalid_type(self):
        assert validate_type("sensor") is False

    def test_empty(self):
        assert validate_type("") is False


class TestResolveDevice:
    """Tests for device nickname resolution."""

    def test_resolves_nickname(self, monkeypatch):
        from ruuvi_data.config import DeviceConfig
        mock_device = DeviceConfig(mac="AA:BB:CC:DD:EE:FF", nickname="office")
        monkeypatch.setattr(
            "cli.commands.cloud.get_device_by_nickname",
            lambda n: mock_device if n.lower() == "office" else None
        )
        assert resolve_device("office") == "AA:BB:CC:DD:EE:FF"

    def test_case_insensitive(self, monkeypatch):
        from ruuvi_data.config import DeviceConfig
        mock_device = DeviceConfig(mac="AA:BB:CC:DD:EE:FF", nickname="Office")
        monkeypatch.setattr(
            "cli.commands.cloud.get_device_by_nickname",
            lambda n: mock_device if n.lower() == "office" else None
        )
        assert resolve_device("OFFICE") == "AA:BB:CC:DD:EE:FF"
        assert resolve_device("office") == "AA:BB:CC:DD:EE:FF"

    def test_returns_input_if_not_found(self, monkeypatch):
        monkeypatch.setattr("cli.commands.cloud.get_device_by_nickname", lambda n: None)
        assert resolve_device("AA:BB:CC:DD:EE:FF") == "AA:BB:CC:DD:EE:FF"

    def test_returns_input_if_no_devices(self, monkeypatch):
        monkeypatch.setattr("cli.commands.cloud.get_device_by_nickname", lambda n: None)
        assert resolve_device("some-device") == "some-device"

    def test_multiple_devices(self, monkeypatch):
        from ruuvi_data.config import DeviceConfig
        devices = {
            "bedroom": DeviceConfig(mac="11:22:33:44:55:66", nickname="bedroom"),
            "office": DeviceConfig(mac="AA:BB:CC:DD:EE:FF", nickname="office"),
        }
        monkeypatch.setattr(
            "cli.commands.cloud.get_device_by_nickname",
            lambda n: devices.get(n.lower())
        )
        assert resolve_device("bedroom") == "11:22:33:44:55:66"
        assert resolve_device("office") == "AA:BB:CC:DD:EE:FF"


class TestPrecmd:
    """Tests for command preprocessing."""

    @pytest.fixture
    def cli(self):
        """Create a CLI instance for testing."""
        cli = RuuviCLI()
        cli.interactive = False  # Disable UI side effects
        return cli

    def test_strips_leading_slash(self, cli):
        assert cli.precmd("/status") == "status"

    def test_converts_hyphen_to_underscore(self, cli):
        assert cli.precmd("gateway-test") == "gateway_test"

    def test_slash_and_hyphen(self, cli):
        assert cli.precmd("/cloud-sync") == "cloud_sync"

    def test_preserves_arguments(self, cli):
        assert cli.precmd("cloud sync office 100") == "cloud sync office 100"

    def test_hyphen_only_in_command(self, cli):
        """Hyphens in arguments should be preserved."""
        assert cli.precmd("cloud-sync my-device") == "cloud_sync my-device"

    def test_empty_line(self, cli):
        assert cli.precmd("") == ""

    def test_multiple_hyphens(self, cli):
        assert cli.precmd("some-long-command") == "some_long_command"
