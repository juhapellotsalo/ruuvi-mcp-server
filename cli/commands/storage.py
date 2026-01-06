"""Storage-related CLI commands."""

import yaml

from ruuvi_data.storage import SensorStorage

from ..ui import DIM, RESET
from .config import CONFIG_PATH, load_config


def do_storage(arg: str) -> None:
    """Configure storage settings."""
    config = load_config()
    storage_config = config.get("storage", {})
    current_path = storage_config.get("path", "data/readings.db")

    print("Storage Configuration\n")
    print(f"{DIM}Press Enter to keep current value{RESET}\n")

    path = input(f"Database path [{current_path}]: ").strip()
    if not path:
        path = current_path

    # Save
    config["storage"] = {"path": path}

    with open(CONFIG_PATH, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    print(f"\nStorage configuration saved to {CONFIG_PATH}\n")

    # Show current stats
    storage = SensorStorage(path)
    count = storage.count()
    devices = storage.get_devices()

    print(f"Database: {path}")
    print(f"  {count:,} readings from {len(devices)} device(s)")

    if devices:
        print("\n  Devices:")
        for d in devices:
            device_count = storage.count(device_id=d)
            print(f"    {d}  ({device_count:,} readings)")
