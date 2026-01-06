"""Cloud-related CLI commands."""

from ruuvi_data.cloud import RuuviCloud, RuuviCloudError
from ruuvi_data.devices import get_device, get_device_by_nickname, load_devices, upsert_device
from ruuvi_data.models import format_reading
from ruuvi_data.storage import SensorStorage

from ..ui import DIM, RESET, Spinner
from .config import (
    ensure_storage_config,
    get_cloud_token,
    load_config,
    save_cloud_config,
)


def resolve_device(identifier: str) -> str:
    """Resolve a device identifier (nickname or MAC) to MAC address."""
    device = get_device_by_nickname(identifier)
    if device:
        return device.mac
    # Return as-is (assume it's a MAC)
    return identifier


def handle_cloud(arg: str) -> None:
    """Handle cloud command with subcommands."""
    parts = arg.split(None, 1)
    subcmd = parts[0] if parts else ""
    subarg = parts[1] if len(parts) > 1 else ""

    if subcmd == "":
        _cloud_status()
    elif subcmd == "auth":
        _cloud_auth()
    elif subcmd == "sensors":
        # Check for "raw" suffix
        if subarg == "raw":
            _cloud_sensors(raw=True)
        else:
            _cloud_sensors()
    elif subcmd == "history":
        # Check for "raw" in args
        subargs = subarg.split()
        if "raw" in subargs:
            subargs.remove("raw")
            _cloud_history(" ".join(subargs), raw=True)
        else:
            _cloud_history(subarg)
    elif subcmd == "sync":
        _cloud_sync(subarg)
    else:
        print(f"Unknown subcommand: {subcmd}")
        print("\nUsage: cloud [auth|sensors|history|sync]")


def _cloud_status() -> None:
    """Show cloud configuration status."""
    config = load_config()
    cloud_config = config.get("cloud", {})

    print("Cloud Status\n")

    if cloud_config.get("token"):
        email = cloud_config.get("email", "unknown")
        print(f"  Authenticated: {email}")
        token = cloud_config["token"]
        masked = token[:4] + "****" if len(token) > 4 else "****"
        print(f"  Token:         {masked}")
    else:
        print(f"  {DIM}Not authenticated{RESET}")

    print("\nSubcommands:")
    print("  cloud auth              Authenticate with Ruuvi Cloud")
    print("  cloud sensors           List sensors")
    print("  cloud sensors raw       List sensors (raw JSON)")
    print("  cloud history [device]  Display history (no storage)")
    print("  cloud history raw [device]  Display raw API response")
    print("  cloud sync [dev] [n]    Sync to local database (optionally one device)")


def _cloud_auth() -> None:
    """Authenticate with Ruuvi Cloud."""
    config = load_config()
    cloud_config = config.get("cloud", {})
    current_email = cloud_config.get("email", "")

    print("Ruuvi Cloud Authentication\n")
    print(f"{DIM}Press Enter to keep current value{RESET}\n")

    if current_email:
        email = input(f"Email [{current_email}]: ").strip()
        if not email:
            email = current_email
    else:
        email = input("Email: ").strip()
        if not email:
            print("Error: Email required")
            return

    spinner = Spinner("Sending verification code")
    spinner.start()
    try:
        with RuuviCloud() as cloud:
            cloud.request_verification(email)
    except RuuviCloudError as e:
        spinner.stop()
        print(f"Error: {e}")
        return
    spinner.stop()

    print(f"Verification code sent to {email}\n")
    code = input("Enter verification code: ").strip()
    if not code:
        print("Error: Code required")
        return

    spinner = Spinner("Verifying")
    spinner.start()
    try:
        with RuuviCloud() as cloud:
            token = cloud.verify(code)
    except RuuviCloudError as e:
        spinner.stop()
        print(f"Error: {e}")
        return
    spinner.stop()

    save_cloud_config(email, token)
    print("Authentication successful. Token saved.\n")

    # Show sensors
    _cloud_sensors()


def _cloud_sensors(raw: bool = False) -> None:
    """List sensors from Ruuvi Cloud."""
    import json
    import httpx

    token = get_cloud_token()
    if not token:
        print("Not authenticated. Run 'cloud auth' first.")
        return

    if raw:
        spinner = Spinner("Fetching")
        spinner.start()
        try:
            response = httpx.get(
                "https://network.ruuvi.com/sensors-dense",
                headers={"Authorization": f"Bearer {token}"},
                params={"measurements": "true"},
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()
            spinner.stop()
            print(json.dumps(data, indent=2))
        except Exception as e:
            spinner.stop()
            print(f"Error: {e}")
        return

    spinner = Spinner("Fetching sensors")
    spinner.start()
    try:
        with RuuviCloud(token) as cloud:
            sensors = cloud.get_sensors(include_measurements=True)
    except RuuviCloudError as e:
        spinner.stop()
        print(f"Error: {e}")
        return
    spinner.stop()

    print(f"Found {len(sensors)} sensors:\n")
    for s in sensors:
        owner = "(owner)" if s.is_owner else "(shared)"
        print(f"  {s.mac}  {s.name}  {owner}")
        if s.last_reading:
            print(f"    {format_reading(s.last_reading, include_date=True)}")
        print()


def _cloud_history(arg: str, raw: bool = False) -> None:
    """Fetch history for a sensor."""
    import json
    import httpx

    args = arg.split()

    # If no device specified, prompt user to pick from configured devices
    if not args:
        devices = load_devices()

        if not devices:
            print("No devices configured. Use 'devices add' or specify MAC directly.")
            print("Usage: cloud history <MAC|nickname> [limit]")
            return

        if len(devices) == 1:
            # Only one device, use it
            mac = devices[0].mac
            identifier = devices[0].nickname or mac
        else:
            # Multiple devices, let user pick
            print("Select device:\n")
            for i, d in enumerate(devices, 1):
                nickname = d.nickname
                mac_addr = d.mac or "?"
                print(f"  {i}. {nickname or mac_addr}")

            print()
            choice = input("Enter number: ").strip()
            if not choice.isdigit() or int(choice) < 1 or int(choice) > len(devices):
                print("Invalid choice.")
                return

            selected = devices[int(choice) - 1]
            mac = selected.mac
            identifier = selected.nickname or mac

        limit = 20
    else:
        identifier = args[0]
        mac = resolve_device(identifier)
        limit = int(args[1]) if len(args) > 1 else 20

    token = get_cloud_token()
    if not token:
        print("Not authenticated. Run 'cloud auth' first.")
        return

    if raw:
        spinner = Spinner("Fetching")
        spinner.start()
        try:
            response = httpx.get(
                "https://network.ruuvi.com/get",
                headers={"Authorization": f"Bearer {token}"},
                params={"sensor": mac, "limit": limit},
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()
            spinner.stop()
            print(json.dumps(data, indent=2))
        except Exception as e:
            spinner.stop()
            print(f"Error: {e}")
        return

    spinner = Spinner(f"Fetching {limit} readings")
    spinner.start()
    try:
        with RuuviCloud(token) as cloud:
            readings = cloud.get_sensor_history(mac, limit=limit)
    except RuuviCloudError as e:
        spinner.stop()
        print(f"Error: {e}")
        return
    spinner.stop()

    print(f"Last {len(readings)} readings for {mac}:\n")
    for r in readings:
        print(format_reading(r, include_date=True))


def _cloud_sync(arg: str) -> None:
    """Sync cloud history to local SQLite."""
    token = get_cloud_token()
    if not token:
        print("Not authenticated. Run 'cloud auth' first.")
        return

    # Parse args: [device] [limit]
    args = arg.split()
    device_filter = None
    limit = 1000

    for a in args:
        if a.isdigit():
            limit = int(a)
        else:
            device_filter = resolve_device(a)

    # Get sensors first
    spinner = Spinner("Fetching sensors")
    spinner.start()
    try:
        with RuuviCloud(token) as cloud:
            sensors = cloud.get_sensors()
    except RuuviCloudError as e:
        spinner.stop()
        print(f"Error: {e}")
        return
    spinner.stop()

    if not sensors:
        print("No sensors found.")
        return

    # Auto-add discovered sensors to devices
    devices_added = []
    for sensor in sensors:
        if not get_device(sensor.mac):
            upsert_device(sensor.mac, nickname=sensor.name or "")
            devices_added.append(sensor.name or sensor.mac)

    if devices_added:
        print(f"Added {len(devices_added)} new device(s):")
        for name in devices_added:
            print(f"  + {name}")
        print()

    # Filter to specific device if requested
    if device_filter:
        sensors = [s for s in sensors if s.mac.upper() == device_filter.upper()]
        if not sensors:
            print(f"Device {device_filter} not found in cloud.")
            return

    if device_filter:
        print(f"Syncing last {limit} readings for {device_filter}...\n")
    else:
        print(f"Syncing last {limit} readings per sensor...\n")

    # Ensure storage config exists
    ensure_storage_config()

    config = load_config()
    db_path = config.get("storage", {}).get("path", "data/readings.db")
    storage = SensorStorage(db_path)

    total_synced = 0

    for sensor in sensors:
        spinner = Spinner(f"Syncing {sensor.name or sensor.mac}")
        spinner.start()
        try:
            with RuuviCloud(token) as cloud:
                readings = cloud.get_sensor_history(sensor.mac, limit=limit)
        except RuuviCloudError as e:
            spinner.stop()
            print(f"  Error syncing {sensor.mac}: {e}")
            continue
        spinner.stop()

        # Insert readings (duplicates are automatically skipped)
        synced = 0
        skipped = 0
        for reading in readings:
            if storage.insert(reading):
                synced += 1
            else:
                skipped += 1

        if skipped:
            print(f"  {sensor.name or sensor.mac}: {synced} new, {skipped} duplicates")
        else:
            print(f"  {sensor.name or sensor.mac}: {synced} new")
        total_synced += synced

    print(f"\nSynced {total_synced} readings to {db_path}")
