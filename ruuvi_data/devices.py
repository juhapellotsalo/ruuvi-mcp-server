"""Device configuration management.

Stores device metadata (nickname, type, description) in data/devices.yaml,
separate from connection configuration (gateway, cloud, mqtt) in config.yaml.
"""

from pathlib import Path

import yaml

from ruuvi_data.config import DeviceConfig

DEFAULT_DEVICES_PATH = Path(__file__).parent.parent / "data" / "devices.yaml"


def load_site(path: Path | str | None = None) -> str | None:
    """Load site context from YAML file.

    The site field provides global context for all sensors (e.g., location,
    climate, building type) that helps interpret sensor readings.
    """
    path = Path(path) if path else DEFAULT_DEVICES_PATH
    if not path.exists():
        return None
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    return data.get("site")


def load_devices(path: Path | str | None = None) -> list[DeviceConfig]:
    """Load devices from YAML file."""
    path = Path(path) if path else DEFAULT_DEVICES_PATH
    if not path.exists():
        return []
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    devices = []
    for d in data.get("devices", []):
        devices.append(
            DeviceConfig(
                mac=d.get("mac", ""),
                type=d.get("type", ""),
                nickname=d.get("nickname", ""),
                description=d.get("description", ""),
                ble_uuid=d.get("ble_uuid", ""),
            )
        )
    return devices


def save_devices(devices: list[DeviceConfig], path: Path | str | None = None) -> None:
    """Save devices to YAML file."""
    path = Path(path) if path else DEFAULT_DEVICES_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "devices": [
            {
                "mac": d.mac,
                "type": d.type,
                "nickname": d.nickname,
                "description": d.description,
                "ble_uuid": d.ble_uuid,
            }
            for d in devices
        ]
    }
    # Filter out empty values for cleaner YAML
    for device in data["devices"]:
        for key in list(device.keys()):
            if not device[key]:
                del device[key]
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def get_device(mac: str, path: Path | str | None = None) -> DeviceConfig | None:
    """Get device by MAC address (case-insensitive)."""
    mac_upper = mac.upper()
    for device in load_devices(path):
        if device.mac.upper() == mac_upper:
            return device
    return None


def get_device_by_nickname(
    nickname: str, path: Path | str | None = None
) -> DeviceConfig | None:
    """Get device by nickname (case-insensitive)."""
    nickname_lower = nickname.lower()
    for device in load_devices(path):
        if device.nickname and device.nickname.lower() == nickname_lower:
            return device
    return None


def upsert_device(
    mac: str,
    type: str = "",
    nickname: str = "",
    description: str = "",
    ble_uuid: str = "",
    path: Path | str | None = None,
) -> bool:
    """Add or update a device.

    Returns:
        True if device was added, False if updated.
    """
    devices = load_devices(path)
    mac_upper = mac.upper()

    for i, device in enumerate(devices):
        if device.mac.upper() == mac_upper:
            # Update existing device, preserving fields not specified
            devices[i] = DeviceConfig(
                mac=device.mac,
                type=type or device.type,
                nickname=nickname or device.nickname,
                description=description or device.description,
                ble_uuid=ble_uuid or device.ble_uuid,
            )
            save_devices(devices, path)
            return False

    # Add new device
    devices.append(
        DeviceConfig(
            mac=mac,
            type=type,
            nickname=nickname,
            description=description,
            ble_uuid=ble_uuid,
        )
    )
    save_devices(devices, path)
    return True


def build_device_lookup(path: Path | str | None = None) -> dict[str, str]:
    """Return {MAC: nickname} dict for display formatting.

    Only includes devices with nicknames. MAC addresses are uppercased.
    """
    return {
        d.mac.upper(): d.nickname for d in load_devices(path) if d.nickname
    }


def _generate_nickname(sensor_type: str, path: Path | str | None = None) -> str:
    """Generate nickname like 'air1', 'tag2' based on existing devices.

    Finds the next available number for the given sensor type prefix.
    """
    devices = load_devices(path)
    prefix = sensor_type  # "air", "tag", or "unknown"

    # Find all used numbers for this prefix
    used_numbers: set[int] = set()
    for d in devices:
        if d.nickname and d.nickname.startswith(prefix):
            suffix = d.nickname[len(prefix):]
            try:
                used_numbers.add(int(suffix))
            except ValueError:
                pass  # Nickname doesn't end with a number

    # Find the first available number starting from 1
    next_num = 1
    while next_num in used_numbers:
        next_num += 1

    return f"{prefix}{next_num}"


def auto_register_device(
    mac: str,
    data_format: int | None,
    path: Path | str | None = None,
) -> bool:
    """Auto-register a device if not already known.

    Called from storage.insert() to automatically add unknown devices
    with auto-generated nicknames based on device type.

    Args:
        mac: Device MAC address
        data_format: BLE data format (determines device type)
        path: Optional path to devices.yaml

    Returns:
        True if device was added, False if already existed
    """
    if get_device(mac, path):
        return False

    from ruuvi_data.models import get_sensor_type

    sensor_type = get_sensor_type(data_format)
    nickname = _generate_nickname(sensor_type, path)

    upsert_device(
        mac=mac,
        type=sensor_type,
        nickname=nickname,
        description="",  # Empty to indicate field is available
        path=path,
    )
    return True
