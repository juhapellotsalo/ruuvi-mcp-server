"""Configuration management for Ruuvi Data Advisor."""

from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"


@dataclass
class GatewayConfig:
    """Configuration for Ruuvi Gateway HTTP polling."""

    url: str
    token: str = ""
    poll_interval: int = 1


@dataclass
class CloudConfig:
    """Configuration for Ruuvi Cloud API."""

    email: str
    token: str


@dataclass
class StorageConfig:
    """Configuration for data storage."""

    path: str = "data/readings.db"


@dataclass
class DeviceConfig:
    """Configuration for a specific device."""

    mac: str
    type: str = ""  # 'air' or 'tag'
    nickname: str = ""
    description: str = ""
    ble_uuid: str = ""  # BLE address (UUID on some platforms, MAC on others)


@dataclass
class MqttConfig:
    """Configuration for MQTT subscriber."""

    broker: str
    port: int = 1883
    topic: str = "ruuvi/#"
    username: str = ""
    password: str = ""
    client_id: str = "ruuvi-advisor"


@dataclass
class Config:
    """Root configuration object."""

    gateway: GatewayConfig | None = None
    cloud: CloudConfig | None = None
    mqtt: MqttConfig | None = None
    storage: StorageConfig = field(default_factory=StorageConfig)

    @classmethod
    def from_yaml(cls, path: Path | str) -> "Config":
        """Load configuration from a YAML file."""
        path = Path(path)
        with open(path) as f:
            data = yaml.safe_load(f) or {}

        return cls._from_dict(data)

    @classmethod
    def _from_dict(cls, data: dict) -> "Config":
        """Create Config from a dictionary."""
        # Parse gateway config
        gateway = None
        if "gateway" in data:
            gw = data["gateway"]
            gateway = GatewayConfig(
                url=gw["url"],
                token=gw.get("token", ""),
                poll_interval=gw.get("poll_interval", 1),
            )

        # Parse cloud config
        cloud = None
        if "cloud" in data:
            c = data["cloud"]
            cloud = CloudConfig(
                email=c.get("email", ""),
                token=c["token"],
            )

        # Parse MQTT config
        mqtt = None
        if "mqtt" in data:
            m = data["mqtt"]
            mqtt = MqttConfig(
                broker=m["broker"],
                port=m.get("port", 1883),
                topic=m.get("topic", "ruuvi/#"),
                username=m.get("username", ""),
                password=m.get("password", ""),
                client_id=m.get("client_id", "ruuvi-advisor"),
            )

        # Parse storage config
        storage_data = data.get("storage", {})
        storage = StorageConfig(
            path=storage_data.get("path", "data/readings.db"),
        )

        return cls(gateway=gateway, cloud=cloud, mqtt=mqtt, storage=storage)


def load_config(path: Path | str = DEFAULT_CONFIG_PATH) -> Config:
    """Load configuration from file."""
    return Config.from_yaml(path)
