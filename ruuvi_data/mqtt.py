"""MQTT subscriber for Ruuvi Gateway data."""

import json
from datetime import datetime
from typing import Callable

import paho.mqtt.client as mqtt

from .config import MqttConfig
from .decoder import decode_raw_data
from .models import SensorReading


def parse_mqtt_message(payload: bytes) -> SensorReading | None:
    """Parse MQTT message payload into a SensorReading.

    Expected payload format:
    {
        "gw_mac": "AA:BB:CC:DD:EE:FF",
        "rssi": -36,
        "data": "2BFF9904E1125356ECB857...",
        "ts": "2025-12-31T17:00:00Z",  # optional
        "coordinates": ""  # optional
    }
    """
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None

    raw_data = data.get("data")
    if not raw_data:
        return None

    decoded = decode_raw_data(raw_data)
    if not decoded:
        return None

    # Get timestamp - try 'ts' field first, fallback to now
    ts = data.get("ts")
    if ts:
        try:
            if isinstance(ts, int):
                # Unix timestamp
                timestamp = datetime.fromtimestamp(ts)
            else:
                # ISO format string
                timestamp = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except (ValueError, OSError):
            timestamp = datetime.now()
    else:
        timestamp = datetime.now()

    # Get device MAC from decoded data or topic
    device_id = decoded.mac or ""

    rssi = data.get("rssi")

    return SensorReading(
        device_id=device_id,
        timestamp=timestamp,
        data_format=decoded.data_format,
        measurement_sequence=decoded.measurement_sequence,
        temperature=decoded.temperature,
        humidity=decoded.humidity,
        pressure=decoded.pressure,
        co2=decoded.co2,
        pm_1_0=decoded.pm_1_0,
        pm_2_5=decoded.pm_2_5,
        pm_4_0=decoded.pm_4_0,
        pm_10_0=decoded.pm_10_0,
        voc=decoded.voc,
        nox=decoded.nox,
        luminosity=decoded.luminosity,
        rssi=rssi,
        acceleration_x=decoded.acceleration_x,
        acceleration_y=decoded.acceleration_y,
        acceleration_z=decoded.acceleration_z,
        movement_counter=decoded.movement_counter,
        battery_voltage=decoded.battery_voltage,
        tx_power=decoded.tx_power,
    )


class MqttSubscriber:
    """MQTT subscriber for Ruuvi Gateway messages."""

    def __init__(
        self,
        config: MqttConfig,
        on_reading: Callable[[SensorReading], bool] | None = None,
    ):
        """Initialize subscriber.

        Args:
            config: MQTT configuration
            on_reading: Callback for each reading, returns True if stored
        """
        self.config = config
        self.on_reading = on_reading
        self._client: mqtt.Client | None = None
        self._running = False
        self.stats = {"received": 0, "stored": 0, "errors": 0}

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        """Handle connection to broker."""
        if reason_code == 0:
            client.subscribe(self.config.topic)
        else:
            print(f"Connection failed: {reason_code}")

    def _on_message(self, client, userdata, msg):
        """Handle incoming message."""
        self.stats["received"] += 1

        reading = parse_mqtt_message(msg.payload)
        if not reading:
            self.stats["errors"] += 1
            return

        if self.on_reading:
            if self.on_reading(reading):
                self.stats["stored"] += 1

    def connect(self) -> bool:
        """Connect to MQTT broker."""
        self._client = mqtt.Client(
            client_id=self.config.client_id,
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        )

        if self.config.username:
            self._client.username_pw_set(
                self.config.username,
                self.config.password,
            )

        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message

        try:
            self._client.connect(self.config.broker, self.config.port)
            return True
        except Exception as e:
            print(f"Connection error: {e}")
            return False

    def run(self):
        """Run the subscriber loop (blocking)."""
        if not self._client:
            if not self.connect():
                return

        self._running = True
        try:
            self._client.loop_forever()
        except KeyboardInterrupt:
            pass
        finally:
            self._running = False
            self._client.disconnect()

    def stop(self):
        """Stop the subscriber."""
        self._running = False
        if self._client:
            self._client.disconnect()
