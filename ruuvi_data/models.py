"""Data models for Ruuvi sensors."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


# Ruuvi data format mapping: format_id -> (sensor_type, format_name)
DATA_FORMAT_INFO: dict[int, tuple[Literal["air", "tag", "unknown"], str]] = {
    3: ("tag", "RAWv1"),
    4: ("tag", "URL"),
    5: ("tag", "RAWv2"),
    6: ("air", "Format6"),
    8: ("tag", "Encrypted"),
    197: ("tag", "Cut-RAWv2"),  # 0xC5
    225: ("air", "ExtendedV1"),  # 0xE1
}


def get_sensor_type(data_format: int | None) -> Literal["air", "tag", "unknown"]:
    """Get sensor type from data format."""
    if data_format is None:
        return "unknown"
    info = DATA_FORMAT_INFO.get(data_format)
    return info[0] if info else "unknown"


@dataclass
class SensorReading:
    """A sensor reading for storage.

    Sensor ranges and meanings:
    - data_format: Ruuvi data format (5=RAWv2, 6=Air BLE4, 225=Air Extended)
    - measurement_sequence: Monotonically increasing counter per device (for dedup)
    - temperature: °C, accuracy ±0.45°C at 15-30°C
    - humidity: % RH, accuracy ±4.5% at 30-70%
    - pressure: Pa, accuracy ±100 Pa, range 50000-115534 Pa
    - co2: ppm, range 0-40000. >1000 = poor ventilation (Air only)
    - pm_1_0, pm_2_5, pm_4_0, pm_10_0: µg/m³, particulate matter (Air only)
    - voc: Index 0-500. 100 = baseline, >100 = more VOCs (Air only)
    - nox: Index 1-500. Higher = more combustion pollutants (Air only)
    - luminosity: lux (reserved, currently unused)
    - rssi: signal strength in dBm
    - acceleration_x/y/z: G, range ±32.767 (Tag only)
    - movement_counter: increments on motion detection (Tag only)
    - battery_voltage: V, range 1.6-3.646 (Tag only)
    - tx_power: dBm, range -40 to +20 (Tag only)
    """

    device_id: str
    timestamp: datetime
    data_format: int | None = None
    measurement_sequence: int | None = None
    temperature: float | None = None
    humidity: float | None = None
    pressure: float | None = None
    co2: int | None = None
    pm_1_0: float | None = None
    pm_2_5: float | None = None
    pm_4_0: float | None = None
    pm_10_0: float | None = None
    voc: int | None = None
    nox: int | None = None
    luminosity: float | None = None
    rssi: int | None = None
    # RuuviTag motion/power fields
    acceleration_x: float | None = None
    acceleration_y: float | None = None
    acceleration_z: float | None = None
    movement_counter: int | None = None
    battery_voltage: float | None = None
    tx_power: int | None = None

    def format_metrics(self) -> str:
        """Format sensor metrics as a display string.

        Shows relevant fields based on sensor type:
        - All: Temperature, Humidity, Pressure
        - Air: CO2, PM2.5, VOC, NOx
        - Tag: Acceleration, Movement, Battery
        """
        parts = []
        if self.temperature is not None:
            parts.append(f"T:{self.temperature:.1f}°C")
        if self.humidity is not None:
            parts.append(f"H:{self.humidity:.0f}%")
        if self.pressure is not None:
            parts.append(f"P:{self.pressure / 100:.0f}hPa")
        # Air quality fields
        if self.co2 is not None:
            parts.append(f"CO2:{self.co2}")
        if self.pm_2_5 is not None:
            parts.append(f"PM2.5:{self.pm_2_5:.1f}")
        if self.voc is not None:
            parts.append(f"VOC:{self.voc}")
        if self.nox is not None:
            parts.append(f"NOx:{self.nox}")
        # Tag motion/power fields
        if self.acceleration_x is not None:
            parts.append(f"Acc:{self.acceleration_x:.2f},{self.acceleration_y:.2f},{self.acceleration_z:.2f}")
        if self.movement_counter is not None:
            parts.append(f"Mov:{self.movement_counter}")
        if self.battery_voltage is not None:
            parts.append(f"Bat:{self.battery_voltage:.2f}V")
        return " ".join(parts)


def format_reading(
    reading: "SensorReading | GatewayReading",
    device_lookup: dict[str, str] | None = None,
    include_date: bool = False,
) -> str:
    """Format a reading for display.

    Works with both SensorReading and GatewayReading.

    Args:
        reading: The reading to format
        device_lookup: Optional dict mapping MAC (uppercase) to nickname
        include_date: If True, include date in timestamp (for historical data)
    """
    # Get device nickname or use MAC
    if device_lookup:
        name = device_lookup.get(reading.device_id.upper()) or reading.device_id
    else:
        name = reading.device_id

    # Build sensor identifier with type
    sensor_type = get_sensor_type(reading.data_format)
    if sensor_type != "unknown":
        sensor_id = f"{sensor_type}/{name}"
    else:
        sensor_id = name

    if include_date:
        time_str = reading.timestamp.strftime("%Y-%m-%d %H:%M:%S")
    else:
        time_str = reading.timestamp.strftime("%H:%M:%S")
    return f"{time_str}  {sensor_id}  {reading.format_metrics()}"


@dataclass
class GatewayReading:
    """A sensor reading from the Gateway /history endpoint.

    Contains all fields available from Ruuvi Air (Data Format E1).
    """

    device_id: str  # MAC address of the sensor
    timestamp: datetime
    measurement_sequence: int

    # Sensor identification
    data_format: int | None = None  # 5=RuuviTag, 6/225=Ruuvi Air

    # Environmental
    temperature: float | None = None  # °C
    humidity: float | None = None  # % RH
    pressure: float | None = None  # Pa (divide by 100 for hPa)

    # Air quality
    co2: int | None = None  # ppm
    voc: int | None = None  # index 0-500
    nox: int | None = None  # index 0-500

    # Particulate matter (µg/m³)
    pm_1_0: float | None = None
    pm_2_5: float | None = None
    pm_4_0: float | None = None
    pm_10_0: float | None = None

    # RuuviTag motion/power fields
    acceleration_x: float | None = None
    acceleration_y: float | None = None
    acceleration_z: float | None = None
    movement_counter: int | None = None
    battery_voltage: float | None = None
    tx_power: int | None = None

    # Other
    rssi: int | None = None  # signal strength dBm

    # Gateway info
    gateway_mac: str | None = None

    @property
    def sensor_type(self) -> Literal["air", "tag", "unknown"]:
        """Get sensor type based on data format."""
        return get_sensor_type(self.data_format)

    def format_metrics(self) -> str:
        """Format sensor metrics as a display string."""
        return self.to_sensor_reading().format_metrics()

    def to_sensor_reading(self) -> SensorReading:
        """Convert to SensorReading for storage."""
        return SensorReading(
            device_id=self.device_id,
            timestamp=self.timestamp,
            data_format=self.data_format,
            measurement_sequence=self.measurement_sequence,
            temperature=self.temperature,
            humidity=self.humidity,
            pressure=self.pressure,
            co2=self.co2,
            pm_1_0=self.pm_1_0,
            pm_2_5=self.pm_2_5,
            pm_4_0=self.pm_4_0,
            pm_10_0=self.pm_10_0,
            voc=self.voc,
            nox=self.nox,
            rssi=self.rssi,
            acceleration_x=self.acceleration_x,
            acceleration_y=self.acceleration_y,
            acceleration_z=self.acceleration_z,
            movement_counter=self.movement_counter,
            battery_voltage=self.battery_voltage,
            tx_power=self.tx_power,
        )
