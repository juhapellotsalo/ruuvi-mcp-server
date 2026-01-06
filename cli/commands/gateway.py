"""Gateway-related CLI commands."""

import asyncio

import yaml

from ruuvi_data.config import GatewayConfig, load_config as load_typed_config
from ruuvi_data.devices import build_device_lookup
from ruuvi_data.gateway import GatewayClient
from ruuvi_data.models import format_reading
from ruuvi_data.storage import SensorStorage

from ..ui import DIM, RESET, Spinner, separator_line
from .config import CONFIG_PATH, load_config


def handle_gateway(arg: str) -> None:
    """Handle gateway command with subcommands."""
    parts = arg.split(None, 1)
    subcmd = parts[0] if parts else ""
    subarg = parts[1] if len(parts) > 1 else ""

    if subcmd == "":
        _gateway_status()
    elif subcmd == "config":
        _gateway_config()
    elif subcmd == "test":
        _gateway_test()
    elif subcmd == "poll":
        if subarg == "raw":
            _gateway_poll_raw()
        else:
            _gateway_poll()
    else:
        print(f"Unknown subcommand: {subcmd}")
        print("\nUsage: gateway [config|test|poll|poll raw]")


def _gateway_status() -> None:
    """Show gateway configuration status."""
    config = load_config()
    gw = config.get("gateway", {})

    print("Gateway Status\n")

    if gw.get("url"):
        print(f"  URL:           {gw['url']}")
        if gw.get("token"):
            masked = gw["token"][:4] + "****" if len(gw["token"]) > 4 else "****"
            print(f"  Token:         {masked}")
        else:
            print(f"  Token:         {DIM}not set{RESET}")
        print(f"  Poll interval: {gw.get('poll_interval', 1)}s")
    else:
        print(f"  {DIM}Not configured{RESET}")

    print("\nSubcommands:")
    print("  gateway config     Configure connection")
    print("  gateway test       Test connection")
    print("  gateway poll       Poll and store readings")
    print("  gateway poll raw   Fetch raw JSON payload")


def _gateway_config() -> None:
    """Configure gateway connection."""
    config = load_config()
    gw = config.get("gateway", {})

    print("Gateway Configuration\n")
    print(f"{DIM}Press Enter to keep current value{RESET}\n")

    # Address (IP or hostname)
    current_url = gw.get("url", "")
    if current_url:
        address = input(f"Gateway address [{current_url}]: ").strip()
        if not address:
            url = current_url
        elif not address.startswith(("http://", "https://")):
            url = f"http://{address}"
        else:
            url = address
    else:
        address = input("Gateway address (IP or .local): ").strip()
        if not address:
            print("Error: Address is required")
            return
        # Prepend http:// if no scheme
        if not address.startswith(("http://", "https://")):
            url = f"http://{address}"
        else:
            url = address

    # Token (optional)
    current_token = gw.get("token", "")
    if current_token:
        masked = current_token[:4] + "****" if len(current_token) > 4 else "****"
        token = input(f"Bearer token [{masked}]: ").strip()
        if not token:
            token = current_token
    else:
        token = input("Bearer token (optional): ").strip()

    # Poll interval
    current_interval = gw.get("poll_interval", 1)
    interval_input = input(f"Poll interval in seconds [{current_interval}]: ").strip()
    if interval_input:
        try:
            poll_interval = int(interval_input)
        except ValueError:
            print("Invalid number, using default")
            poll_interval = current_interval
    else:
        poll_interval = current_interval

    # Save
    config["gateway"] = {
        "url": url,
        "token": token,
        "poll_interval": poll_interval,
    }

    # Remove empty token
    if not config["gateway"]["token"]:
        del config["gateway"]["token"]

    with open(CONFIG_PATH, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    print(f"\nGateway configuration saved to {CONFIG_PATH}\n")

    # Test the connection
    _gateway_test()


def _gateway_test() -> None:
    """Test gateway connection."""
    config = load_config()
    gw = config.get("gateway", {})

    if not gw.get("url"):
        print("Gateway not configured. Run 'gateway config' first.")
        return

    print(f"Testing connection to {gw['url']}...\n")

    async def test_connection():
        gateway_config = GatewayConfig(
            url=gw["url"],
            token=gw.get("token", ""),
            poll_interval=1,
        )
        async with GatewayClient(gateway_config) as client:
            readings = await client.fetch_readings()
            return readings

    spinner = Spinner("Connecting")
    spinner.start()
    try:
        readings = asyncio.run(test_connection())
        spinner.stop()

        print("Connection successful.\n")
        print(f"Found {len(readings)} sensor(s):\n")
        for r in readings:
            sensor_type = r.sensor_type
            if sensor_type in ("air", "tag"):
                print(f"  {sensor_type}/{r.device_id}")
            else:
                print(f"  {r.device_id}")
            if r.temperature is not None:
                print(f"    T:{r.temperature:.1f}°C", end="")
            if r.humidity is not None:
                print(f"  H:{r.humidity:.0f}%", end="")
            if r.co2 is not None:
                print(f"  CO2:{r.co2}", end="")
            print()

    except Exception as e:
        spinner.stop()
        print(f"Connection failed: {e}")


def _gateway_poll() -> None:
    """Poll gateway and store readings."""
    try:
        config = load_typed_config(CONFIG_PATH)
    except Exception as e:
        print(f"Error loading config: {e}")
        return

    if not config.gateway:
        print("Gateway not configured. Run 'gateway config' first.")
        return

    device_lookup = build_device_lookup()
    storage = SensorStorage(config.storage.path)

    print(f"Polling {config.gateway.url}")
    print(f"Poll interval: {config.gateway.poll_interval}s")
    print(f"Storing to: {config.storage.path}")
    print(f"{DIM}Press Ctrl+C to stop{RESET}\n")
    print(separator_line())

    received = [0]
    stored = [0]

    async def poll():
        gw = config.gateway
        gateway_config = GatewayConfig(
            url=gw.url, token=gw.token, poll_interval=gw.poll_interval
        )
        async with GatewayClient(gateway_config) as client:
            async for reading in client.stream_readings():
                print(format_reading(reading, device_lookup))
                received[0] += 1
                if storage.insert(reading.to_sensor_reading()):
                    stored[0] += 1

    try:
        asyncio.run(poll())
    except KeyboardInterrupt:
        pass

    print(separator_line())
    print(f"\nStopped. Received {received[0]}, stored {stored[0]} new.")


def _gateway_poll_raw() -> None:
    """Fetch raw JSON payload from gateway."""
    import json
    import httpx

    config_dict = load_config()
    gw = config_dict.get("gateway", {})

    if not gw.get("url"):
        print("Gateway not configured. Run 'gateway config' first.")
        return

    url = f"{gw['url'].rstrip('/')}/history"
    headers = {}
    if gw.get("token"):
        headers["Authorization"] = f"Bearer {gw['token']}"

    spinner = Spinner("Fetching")
    spinner.start()
    try:
        response = httpx.get(url, headers=headers, timeout=10.0)
        response.raise_for_status()
        data = response.json()
        spinner.stop()
        print(json.dumps(data, indent=2))
    except Exception as e:
        spinner.stop()
        print(f"Error: {e}")
