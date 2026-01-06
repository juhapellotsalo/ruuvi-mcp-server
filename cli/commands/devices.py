"""Device management CLI commands."""

import re

from ruuvi_data.devices import get_device, load_devices, upsert_device

# MAC address pattern: XX:XX:XX:XX:XX:XX
MAC_PATTERN = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")
VALID_TYPES = ("air", "tag")


def handle_devices(arg: str) -> None:
    """Handle devices commands."""
    parts = arg.split()
    subcommand = parts[0] if parts else ""

    if subcommand == "":
        list_devices()
    elif subcommand == "add":
        add_device()
    else:
        print(f"Unknown subcommand: {subcommand}")
        print("Usage: devices [add]")


def list_devices() -> None:
    """List configured devices."""
    devices = load_devices()

    if not devices:
        print("No devices configured.")
        print("Run 'devices add' or 'ble scan' to add devices.")
        return

    print(f"Configured Devices ({len(devices)})\n")

    for device in devices:
        mac = device.mac or "?"
        nickname = device.nickname
        device_type = device.type
        description = device.description
        ble_uuid = device.ble_uuid

        # Show short MAC (last 6 chars) alongside full
        short_mac = mac.replace(":", "")[-6:] if mac else "?"

        print(f"  {nickname or short_mac}")
        print(f"    MAC:  {mac}")
        if device_type:
            print(f"    Type: {device_type}")
        if ble_uuid:
            print(f"    BLE:  {ble_uuid}")
        if description:
            print(f"    {description}")
        print()


def validate_mac(mac: str) -> bool:
    """Validate MAC address format."""
    return bool(MAC_PATTERN.match(mac))


def validate_type(device_type: str) -> bool:
    """Validate device type."""
    return device_type.lower() in VALID_TYPES


def add_device() -> None:
    """Interactively add a new device."""
    print("Add New Device\n")

    # MAC address
    while True:
        mac = input("  MAC address (XX:XX:XX:XX:XX:XX): ").strip().upper()
        if validate_mac(mac):
            break
        print("  Invalid MAC format. Use XX:XX:XX:XX:XX:XX\n")

    # Check for duplicate
    if get_device(mac):
        print(f"  Device {mac} already exists.")
        return

    # Type
    while True:
        device_type = input("  Type (air/tag): ").strip().lower()
        if validate_type(device_type):
            break
        print("  Invalid type. Must be 'air' or 'tag'\n")

    # Nickname
    nickname = input("  Nickname (optional): ").strip()

    # Description
    description = input("  Description (optional): ").strip()

    # Save
    upsert_device(mac, type=device_type, nickname=nickname, description=description)

    print(f"\n  Added device {nickname or mac}")
