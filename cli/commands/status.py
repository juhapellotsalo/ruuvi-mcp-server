"""Status and help CLI commands."""

from ruuvi_data.storage import SensorStorage

from .config import load_config


def mask_token(token: str | None) -> str:
    """Mask a token for display, showing only first/last 4 chars."""
    if not token:
        return "(not set)"
    if len(token) <= 12:
        return "****"
    return f"{token[:4]}...{token[-4:]}"


def do_status(arg: str) -> None:
    """Show current configuration status."""
    config = load_config()

    print("Configuration Status")
    print("=" * 50)

    # Gateway
    print("\nGateway:")
    gw = config.get("gateway", {})
    if gw.get("url"):
        print(f"  url:           {gw['url']}")
        print(f"  token:         {mask_token(gw.get('token'))}")
        print(f"  poll_interval: {gw.get('poll_interval', 1)}s")
    else:
        print("  (not configured)")

    # Cloud
    print("\nCloud:")
    cloud = config.get("cloud", {})
    if cloud.get("token"):
        print(f"  email:  {cloud.get('email', '(not set)')}")
        print(f"  token:  {mask_token(cloud.get('token'))}")
    else:
        print("  (not configured)")

    # MQTT
    print("\nMQTT:")
    mqtt = config.get("mqtt", {})
    if mqtt.get("broker"):
        print(f"  broker:    {mqtt['broker']}")
        print(f"  port:      {mqtt.get('port', 1883)}")
        print(f"  topic:     {mqtt.get('topic', 'ruuvi/#')}")
        if mqtt.get("username"):
            print(f"  username:  {mqtt['username']}")
            print(f"  password:  {mask_token(mqtt.get('password'))}")
        print(f"  client_id: {mqtt.get('client_id', 'ruuvi-advisor')}")
    else:
        print("  (not configured)")

    # Storage
    print("\nStorage:")
    storage_cfg = config.get("storage", {})
    db_path = storage_cfg.get("path", "data/readings.db")
    print(f"  path: {db_path}")

    storage = SensorStorage(db_path)
    count = storage.count()
    devices = storage.get_devices()
    print(f"  readings: {count:,} from {len(devices)} device(s)")

    # Configured Devices
    print("\nDevices:")
    configured_devices = config.get("devices", [])
    # Build a lookup by MAC for later use
    device_lookup = {d.get("mac", "").upper(): d for d in configured_devices}
    if configured_devices:
        for dev in configured_devices:
            mac = dev.get("mac", "(no mac)")
            dev_type = dev.get("type", "")
            nickname = dev.get("nickname", "")
            description = dev.get("description", "")
            type_str = f" [{dev_type}]" if dev_type else ""
            desc_str = f" - {description}" if description else ""
            print(f"  {mac}: {nickname}{type_str}{desc_str}")
    else:
        print("  (none configured)")

    # Devices in database
    if devices:
        print("\nDevices in database:")
        for d in devices:
            device_count = storage.count(device_id=d)
            # Check if this device is in config
            dev_info = device_lookup.get(d.upper(), {})
            nickname = dev_info.get("nickname", "")
            name_str = f" ({nickname})" if nickname else ""
            print(f"  {d}{name_str}: {device_count:,} readings")
