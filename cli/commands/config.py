"""Shared configuration helpers for CLI commands."""

from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).parent.parent.parent / "config.yaml"


def load_config() -> dict:
    """Load config.yaml as dict."""
    if not CONFIG_PATH.exists():
        return {}
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f) or {}


def save_config(config: dict) -> None:
    """Save config dict to config.yaml."""
    with open(CONFIG_PATH, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)


def save_cloud_config(email: str, token: str) -> None:
    """Update config.yaml with cloud credentials."""
    config = load_config()

    config["cloud"] = {
        "email": email,
        "token": token,
    }

    with open(CONFIG_PATH, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)


def get_cloud_token() -> str | None:
    """Get cloud token from config."""
    config = load_config()
    return config.get("cloud", {}).get("token")


def ensure_storage_config() -> None:
    """Ensure storage config exists with default path."""
    config = load_config()
    if "storage" not in config:
        config["storage"] = {"path": "data/readings.db"}
        save_config(config)


def ensure_device_in_config(
    mac: str,
    name: str | None = None,
    device_type: str | None = None,
) -> bool:
    """Add device to config if not already present.

    Args:
        mac: Device MAC address
        name: Optional name/nickname for the device
        device_type: Optional type ('air' or 'tag')

    Returns:
        True if device was added, False if already existed
    """
    from ruuvi_data.devices import get_device, upsert_device

    # Check if device already exists
    if get_device(mac):
        return False

    # Add new device
    upsert_device(mac, type=device_type or "", nickname=name or "")
    return True


def get_device_by_mac(mac: str) -> dict | None:
    """Get device config by MAC address."""
    from ruuvi_data.devices import get_device

    device = get_device(mac)
    if device:
        return {
            "mac": device.mac,
            "type": device.type,
            "nickname": device.nickname,
            "description": device.description,
            "ble_uuid": device.ble_uuid,
        }
    return None
