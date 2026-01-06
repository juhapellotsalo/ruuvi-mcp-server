"""MQTT-related CLI commands."""

import yaml

from ruuvi_data.config import MqttConfig, load_config as load_typed_config
from ruuvi_data.devices import build_device_lookup
from ruuvi_data.models import SensorReading, format_reading
from ruuvi_data.mqtt import MqttSubscriber
from ruuvi_data.storage import SensorStorage

from ..ui import DIM, RESET, Spinner
from .config import CONFIG_PATH, load_config


def handle_mqtt(arg: str) -> None:
    """Handle mqtt command with subcommands."""
    parts = arg.split(None, 1)
    subcmd = parts[0] if parts else ""
    subarg = parts[1] if len(parts) > 1 else ""

    if subcmd == "":
        _mqtt_status()
    elif subcmd == "config":
        _mqtt_config()
    elif subcmd == "listen":
        _mqtt_listen(store=True)
    elif subcmd == "monitor":
        _mqtt_listen(store=False)
    else:
        print(f"Unknown subcommand: {subcmd}")
        print("\nUsage: mqtt [config|listen|monitor]")


def _mqtt_status() -> None:
    """Show MQTT configuration status."""
    config = load_config()
    mqtt_config = config.get("mqtt", {})

    print("MQTT Status\n")

    if mqtt_config.get("broker"):
        print(f"  Broker:    {mqtt_config['broker']}:{mqtt_config.get('port', 1883)}")
        print(f"  Topic:     {mqtt_config.get('topic', 'ruuvi/#')}")
        if mqtt_config.get("username"):
            print(f"  Username:  {mqtt_config['username']}")
        print(f"  Client ID: {mqtt_config.get('client_id', 'ruuvi-advisor')}")
    else:
        print(f"  {DIM}Not configured{RESET}")

    print("\nSubcommands:")
    print("  mqtt config    Configure MQTT broker")
    print("  mqtt listen    Subscribe and store readings")
    print("  mqtt monitor   Subscribe and display only (no storage)")


def _mqtt_config() -> None:
    """Configure MQTT broker."""
    config = load_config()
    mqtt = config.get("mqtt", {})

    print("MQTT Configuration\n")
    print(f"{DIM}Press Enter to keep current value{RESET}\n")

    # Broker
    current_broker = mqtt.get("broker", "")
    if current_broker:
        broker = input(f"Broker address [{current_broker}]: ").strip()
        if not broker:
            broker = current_broker
    else:
        broker = input("Broker address (e.g., localhost): ").strip()
        if not broker:
            print("Error: Broker address is required")
            return

    # Port
    current_port = mqtt.get("port", 1883)
    port_input = input(f"Port [{current_port}]: ").strip()
    if port_input:
        try:
            port = int(port_input)
        except ValueError:
            print("Invalid port, using default")
            port = current_port
    else:
        port = current_port

    # Topic
    current_topic = mqtt.get("topic", "ruuvi/#")
    topic = input(f"Topic [{current_topic}]: ").strip()
    if not topic:
        topic = current_topic

    # Username (optional)
    current_username = mqtt.get("username", "")
    username = input(f"Username [{current_username or 'none'}]: ").strip()
    if not username:
        username = current_username

    # Password (optional, only if username set)
    password = ""
    if username:
        current_password = mqtt.get("password", "")
        if current_password:
            password = input("Password [****]: ").strip()
            if not password:
                password = current_password
        else:
            password = input("Password: ").strip()

    # Save
    config["mqtt"] = {
        "broker": broker,
        "port": port,
        "topic": topic,
    }
    if username:
        config["mqtt"]["username"] = username
    if password:
        config["mqtt"]["password"] = password

    with open(CONFIG_PATH, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    print(f"\nMQTT configuration saved to {CONFIG_PATH}")


def _mqtt_listen(store: bool = True) -> None:
    """Subscribe to MQTT and optionally store readings."""
    try:
        config = load_typed_config(CONFIG_PATH)
    except Exception as e:
        print(f"Error loading config: {e}")
        return

    if not config.mqtt:
        print("MQTT not configured. Run 'mqtt config' first.")
        return

    # Build device nickname lookup
    device_lookup = build_device_lookup()

    # Initialize storage if storing
    storage = None
    if store:
        storage = SensorStorage(config.storage.path)

    print(f"Connecting to {config.mqtt.broker}:{config.mqtt.port}")
    print(f"Topic: {config.mqtt.topic}")
    if store:
        print(f"Storing to: {config.storage.path}")
    else:
        print(f"{DIM}Monitor mode - not storing{RESET}")
    print(f"{DIM}Press Ctrl+C to stop{RESET}\n")

    def on_reading(reading: SensorReading) -> bool:
        """Handle incoming reading."""
        print(format_reading(reading, device_lookup))
        if storage:
            return storage.insert(reading)
        return False

    subscriber = MqttSubscriber(config.mqtt, on_reading=on_reading)

    spinner = Spinner("Connecting")
    spinner.start()
    if not subscriber.connect():
        spinner.stop()
        print("Failed to connect to MQTT broker")
        return
    spinner.stop()

    print("Connected. Waiting for messages...\n")

    try:
        subscriber.run()
    except KeyboardInterrupt:
        pass

    print(f"\nStopped.")
    print(f"  Received: {subscriber.stats['received']}")
    if store:
        print(f"  Stored:   {subscriber.stats['stored']}")
    print(f"  Errors:   {subscriber.stats['errors']}")
