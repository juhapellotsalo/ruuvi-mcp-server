"""MCP server for Ruuvi sensor data.

Provides flexible access to indoor air quality data from Ruuvi sensors.
Designed to give AI clients compact, relevant data for analysis.

Tools:
- list_sensors(): Discover available sensors and data time range
- get_current(): Latest readings with health status
- query(): Flexible historical data with adaptive sampling
"""

import re
from datetime import datetime, timedelta
from typing import Literal

from mcp.server.fastmcp import FastMCP

from ruuvi_data.devices import load_devices, load_site, get_device, get_device_by_nickname
from ruuvi_data.models import get_sensor_type
from ruuvi_data.storage import SensorStorage

mcp = FastMCP(name="Ruuvi MCP")
storage = SensorStorage()


@mcp.resource("ruuvi://guide")
def get_guide() -> str:
    """Usage guide for Ruuvi sensor data tools."""
    return """# Ruuvi Sensor Data Guide

## Quick Start
1. Call list_sensors() to discover available sensors and data time range
2. Call get_current() for latest readings with health status
3. Call query() for historical data analysis

## Query Resolution Guidelines
Results are capped at 200 data points. Choose resolution based on time range:
- Last 1-2 hours: resolution="raw" or "auto"
- Last 24 hours: resolution="15m" or "auto"
- Last 7 days: resolution="1h"
- Last 30 days: resolution="6h"

If a query returns "too many results" error, use a coarser resolution.

## Available readings
- CO2 > 1000 ppm: Poor ventilation, may cause fatigue
- CO2 > 1500 ppm: Significantly stuffy, need fresh air
- PM2.5 > 25 µg/m³: Poor air quality (WHO guideline)
- VOC index > 100: More volatile compounds than baseline
- VOC index < 100: Cleaner than average air
- Humidity 30-60%: Comfortable range
- Humidity < 30%: Too dry
- Humidity > 70%: Too humid

## Sensor Types
- "air": Ruuvi Air sensor (CO2, PM, VOC, NOx, temp, humidity, pressure)
- "tag": RuuviTag (temp, humidity, pressure, movement)
"""


# Health thresholds based on WHO guidelines
THRESHOLDS = {
    "co2": {"good": 800, "elevated": 1000, "poor": 1500},
    "pm_2_5": {"good": 10, "elevated": 15, "poor": 25},
    "voc": {"good": 100, "elevated": 150, "poor": 250},
    "humidity": {"low": 30, "good_min": 30, "good_max": 60, "high": 70},
}

# Resolution to seconds mapping for bucket aggregation
RESOLUTION_SECONDS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "6h": 21600,
    "1d": 86400,
}

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _get_context() -> dict:
    """Get current time context for AI awareness."""
    now = datetime.now()
    return {
        "queried_at": now.isoformat(timespec="seconds"),
        "day_of_week": DAY_NAMES[now.weekday()],
    }


def _resolve_device(identifier: str | None) -> str | None:
    """Resolve device nickname to MAC address."""
    if not identifier:
        return None

    device = get_device_by_nickname(identifier)
    if device:
        return device.mac

    return identifier


def _get_device_info(device_id: str) -> dict:
    """Get device nickname, type, and description."""
    device = get_device(device_id)
    if device:
        return {
            "nickname": device.nickname,
            "type": device.type,
            "description": device.description,
        }
    return {"nickname": None, "type": "unknown", "description": None}


def _get_device_name(device_id: str) -> str:
    """Get nickname for device, or short MAC if not configured."""
    info = _get_device_info(device_id)
    return info["nickname"] or device_id[-8:]


def _get_health_status(metric: str, value: float | int | None) -> str:
    """Get health status for a metric value."""
    if value is None:
        return "unknown"

    if metric == "humidity":
        if value < THRESHOLDS["humidity"]["low"]:
            return "low"
        elif value > THRESHOLDS["humidity"]["high"]:
            return "high"
        else:
            return "good"

    if metric not in THRESHOLDS:
        return "unknown"

    t = THRESHOLDS[metric]
    if value <= t["good"]:
        return "good"
    elif value <= t["elevated"]:
        return "elevated"
    else:
        return "poor"


def _parse_time(time_str: str | None, default: datetime | None = None) -> datetime | None:
    """Parse time string - ISO format or relative like '-24h', '-7d'.

    Relative formats:
    - '-1h', '-24h': hours ago
    - '-7d', '-30d': days ago
    - '-15m': minutes ago
    """
    if time_str is None:
        return default

    # Check for relative time
    match = re.match(r'^-(\d+)(m|h|d)$', time_str.strip())
    if match:
        value = int(match.group(1))
        unit = match.group(2)
        if unit == 'm':
            return datetime.now() - timedelta(minutes=value)
        elif unit == 'h':
            return datetime.now() - timedelta(hours=value)
        elif unit == 'd':
            return datetime.now() - timedelta(days=value)

    # Try ISO format
    try:
        return datetime.fromisoformat(time_str)
    except ValueError:
        return default


def _adaptive_sample(readings: list, max_points: int, recent_minutes: int = 15) -> tuple[list, str]:
    """Adaptively sample readings to stay under max_points.

    Strategy (inspired by Ruuvi Station app):
    - If readings <= max_points: return all (raw)
    - Otherwise: keep recent data at full resolution, sample historical evenly

    Returns (sampled_readings, resolution_used)
    """
    if len(readings) <= max_points:
        return readings, "raw"

    now = datetime.now()
    recent_cutoff = now - timedelta(minutes=recent_minutes)

    # Split into recent (full res) and historical (to be sampled)
    # Readings are in reverse chronological order from storage
    recent = []
    historical = []
    for r in readings:
        if r.timestamp >= recent_cutoff:
            recent.append(r)
        else:
            historical.append(r)

    # Allocate budget: 25% for recent, 75% for historical
    recent_budget = min(len(recent), max_points // 4)
    historical_budget = max_points - recent_budget

    # Sample recent (most recent ones)
    sampled_recent = recent[:recent_budget] if recent else []

    # Sample historical evenly
    if historical and historical_budget > 0:
        step = max(1, len(historical) // historical_budget)
        sampled_historical = historical[::step][:historical_budget]
    else:
        sampled_historical = []

    # Combine: historical first (older), then recent (newer)
    # But keep in reverse chronological order (newest first)
    sampled = sampled_recent + sampled_historical

    # Estimate resolution used
    if len(sampled) >= 2:
        time_span = (sampled[-1].timestamp - sampled[0].timestamp).total_seconds()
        avg_interval = abs(time_span) / len(sampled)
        if avg_interval < 120:
            resolution = "~1m"
        elif avg_interval < 600:
            resolution = "~5m"
        elif avg_interval < 1800:
            resolution = "~15m"
        elif avg_interval < 7200:
            resolution = "~1h"
        else:
            resolution = "~6h"
    else:
        resolution = "raw"

    return sampled, resolution


def _calculate_summary(readings: list) -> dict:
    """Calculate summary statistics from readings."""
    if not readings:
        return {}

    def stats(values):
        valid = [v for v in values if v is not None]
        if not valid:
            return None
        return {
            "avg": round(sum(valid) / len(valid), 1),
            "min": round(min(valid), 1),
            "max": round(max(valid), 1),
        }

    def avg_only(values):
        valid = [v for v in values if v is not None]
        if not valid:
            return None
        return round(sum(valid) / len(valid), 1)

    summary = {}

    # Temperature
    temp_stats = stats([r.temperature for r in readings])
    if temp_stats:
        summary["temperature"] = {**temp_stats, "unit": "°C"}

    # Humidity
    humidity_stats = stats([r.humidity for r in readings])
    if humidity_stats:
        summary["humidity"] = {**humidity_stats, "unit": "%"}

    # Pressure (convert to hPa)
    pressures = [r.pressure / 100 if r.pressure else None for r in readings]
    pressure_avg = avg_only(pressures)
    if pressure_avg:
        summary["pressure"] = {"avg": pressure_avg, "unit": "hPa"}

    # CO2
    co2_stats = stats([r.co2 for r in readings])
    if co2_stats:
        summary["co2"] = {**{k: int(v) for k, v in co2_stats.items()}, "unit": "ppm"}

    # PM values
    for pm_field, pm_name in [("pm_1_0", "pm_1_0"), ("pm_2_5", "pm_2_5"),
                               ("pm_4_0", "pm_4_0"), ("pm_10_0", "pm_10_0")]:
        pm_stats = stats([getattr(r, pm_field) for r in readings])
        if pm_stats:
            summary[pm_name] = {**pm_stats, "unit": "µg/m³"}

    # VOC
    voc_stats = stats([r.voc for r in readings])
    if voc_stats:
        summary["voc"] = {**{k: int(v) for k, v in voc_stats.items()}, "unit": "index"}

    # NOx
    nox_avg = avg_only([r.nox for r in readings])
    if nox_avg:
        summary["nox"] = {"avg": int(nox_avg), "unit": "index"}

    # Battery voltage (useful for RuuviTag health monitoring)
    battery_values = [r.battery_voltage for r in readings if r.battery_voltage is not None]
    if battery_values:
        summary["battery"] = {
            "avg": round(sum(battery_values) / len(battery_values), 2),
            "min": round(min(battery_values), 2),
            "max": round(max(battery_values), 2),
            "unit": "V",
        }

    # Movement counter (show range to indicate activity)
    movements = [r.movement_counter for r in readings if r.movement_counter is not None]
    if movements:
        summary["movement"] = {"min": min(movements), "max": max(movements)}

    return summary


def _detect_gaps(readings: list, threshold_minutes: int = 60) -> list[dict]:
    """Detect significant gaps in data."""
    if len(readings) < 2:
        return []

    gaps = []
    threshold = timedelta(minutes=threshold_minutes)

    # Readings are in reverse chronological order
    for i in range(len(readings) - 1):
        newer = readings[i]
        older = readings[i + 1]
        gap = newer.timestamp - older.timestamp
        if gap > threshold:
            gaps.append({
                "start": older.timestamp.isoformat(),
                "end": newer.timestamp.isoformat(),
                "minutes": int(gap.total_seconds() / 60),
            })

    return gaps


def _format_reading(reading, include_device: bool = True) -> dict:
    """Format a reading for output, including all available metrics."""
    result = {
        "t": reading.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
    }

    if include_device:
        result["device"] = _get_device_name(reading.device_id)

    # Include all non-null metrics
    if reading.temperature is not None:
        result["temperature"] = round(reading.temperature, 1)
    if reading.humidity is not None:
        result["humidity"] = round(reading.humidity, 1)
    if reading.pressure is not None:
        result["pressure"] = round(reading.pressure / 100, 1)  # hPa
    if reading.co2 is not None:
        result["co2"] = reading.co2
    if reading.pm_1_0 is not None:
        result["pm_1_0"] = round(reading.pm_1_0, 1)
    if reading.pm_2_5 is not None:
        result["pm_2_5"] = round(reading.pm_2_5, 1)
    if reading.pm_4_0 is not None:
        result["pm_4_0"] = round(reading.pm_4_0, 1)
    if reading.pm_10_0 is not None:
        result["pm_10_0"] = round(reading.pm_10_0, 1)
    if reading.voc is not None:
        result["voc"] = reading.voc
    if reading.nox is not None:
        result["nox"] = reading.nox
    if reading.rssi is not None:
        result["rssi"] = reading.rssi

    # RuuviTag motion/power fields
    if reading.acceleration_x is not None:
        result["accel"] = [
            round(reading.acceleration_x, 3),
            round(reading.acceleration_y, 3) if reading.acceleration_y is not None else 0,
            round(reading.acceleration_z, 3) if reading.acceleration_z is not None else 0,
        ]
    if reading.battery_voltage is not None:
        result["battery"] = round(reading.battery_voltage, 2)
    if reading.movement_counter is not None:
        result["movement"] = reading.movement_counter
    if reading.tx_power is not None:
        result["tx_power"] = reading.tx_power

    return result


def _bucket_aggregate(readings: list, bucket_seconds: int) -> list[dict]:
    """Aggregate readings into time buckets."""
    if not readings:
        return []

    # Group readings by bucket
    buckets: dict[str, list] = {}
    for r in readings:
        # Round timestamp down to bucket boundary
        ts = r.timestamp.timestamp()
        bucket_ts = int(ts // bucket_seconds) * bucket_seconds
        bucket_key = datetime.fromtimestamp(bucket_ts).strftime("%Y-%m-%d %H:%M")

        if bucket_key not in buckets:
            buckets[bucket_key] = []
        buckets[bucket_key].append(r)

    # Calculate averages for each bucket
    result = []
    for bucket_time, bucket_readings in sorted(buckets.items()):
        entry = {"t": bucket_time, "n": len(bucket_readings)}

        def avg(values):
            valid = [v for v in values if v is not None]
            return round(sum(valid) / len(valid), 1) if valid else None

        def avg_int(values):
            valid = [v for v in values if v is not None]
            return int(sum(valid) / len(valid)) if valid else None

        def avg_precise(values, decimals=3):
            valid = [v for v in values if v is not None]
            return round(sum(valid) / len(valid), decimals) if valid else None

        def last_val(values):
            valid = [v for v in values if v is not None]
            return valid[-1] if valid else None

        temp = avg([r.temperature for r in bucket_readings])
        if temp is not None:
            entry["temperature"] = temp

        humidity = avg([r.humidity for r in bucket_readings])
        if humidity is not None:
            entry["humidity"] = humidity

        pressure = avg([r.pressure / 100 if r.pressure else None for r in bucket_readings])
        if pressure is not None:
            entry["pressure"] = pressure

        co2 = avg_int([r.co2 for r in bucket_readings])
        if co2 is not None:
            entry["co2"] = co2

        for pm_field in ["pm_1_0", "pm_2_5", "pm_4_0", "pm_10_0"]:
            pm = avg([getattr(r, pm_field) for r in bucket_readings])
            if pm is not None:
                entry[pm_field] = pm

        voc = avg_int([r.voc for r in bucket_readings])
        if voc is not None:
            entry["voc"] = voc

        nox = avg_int([r.nox for r in bucket_readings])
        if nox is not None:
            entry["nox"] = nox

        # RuuviTag fields - acceleration as [x,y,z] array
        acc_x = avg_precise([r.acceleration_x for r in bucket_readings])
        if acc_x is not None:
            acc_y = avg_precise([r.acceleration_y for r in bucket_readings])
            acc_z = avg_precise([r.acceleration_z for r in bucket_readings])
            entry["accel"] = [acc_x, acc_y or 0, acc_z or 0]

        battery = avg_precise([r.battery_voltage for r in bucket_readings], 2)
        if battery is not None:
            entry["battery"] = battery

        # Movement counter: use max in bucket (it's cumulative)
        movements = [r.movement_counter for r in bucket_readings if r.movement_counter is not None]
        if movements:
            entry["movement"] = max(movements)

        # TX power: use last value (usually constant)
        tx = last_val([r.tx_power for r in bucket_readings])
        if tx is not None:
            entry["tx_power"] = tx

        result.append(entry)

    return result


@mcp.tool()
def get_current(device: str | None = None) -> dict:
    """Get current sensor readings.

    Args:
        device: Sensor nickname or MAC address. Omit for all sensors.

    Returns latest reading(s) with health status indicators.
    Health status: "good", "elevated", or "poor" based on WHO guidelines.
    """
    device_id = _resolve_device(device)
    context = _get_context()

    if device_id:
        reading = storage.get_latest(device_id=device_id)
        if not reading:
            return {"error": f"No readings for device: {device}"}
        result = _format_current_reading(reading)
        result["context"] = context
        return result
    else:
        devices = storage.get_devices()
        if not devices:
            return {"error": "No readings available"}

        readings = {}
        for dev_id in devices:
            reading = storage.get_latest(device_id=dev_id)
            if reading:
                name = _get_device_name(dev_id)
                readings[name] = _format_current_reading(reading)

        return {"context": context, "sensors": readings}


def _format_current_reading(reading) -> dict:
    """Format a reading with health status indicators."""
    result = {
        "timestamp": reading.timestamp.isoformat(),
        "device_id": reading.device_id,
        "device_type": get_sensor_type(reading.data_format),
    }

    if reading.temperature is not None:
        result["temperature"] = {"value": round(reading.temperature, 1), "unit": "°C"}

    if reading.humidity is not None:
        result["humidity"] = {
            "value": round(reading.humidity),
            "unit": "%",
            "status": _get_health_status("humidity", reading.humidity),
        }

    if reading.pressure is not None:
        result["pressure"] = {"value": round(reading.pressure / 100, 1), "unit": "hPa"}

    if reading.co2 is not None:
        result["co2"] = {
            "value": reading.co2,
            "unit": "ppm",
            "status": _get_health_status("co2", reading.co2),
        }

    if reading.pm_1_0 is not None:
        result["pm_1_0"] = {"value": reading.pm_1_0, "unit": "µg/m³"}

    if reading.pm_2_5 is not None:
        result["pm_2_5"] = {
            "value": reading.pm_2_5,
            "unit": "µg/m³",
            "status": _get_health_status("pm_2_5", reading.pm_2_5),
        }

    if reading.pm_4_0 is not None:
        result["pm_4_0"] = {"value": reading.pm_4_0, "unit": "µg/m³"}

    if reading.pm_10_0 is not None:
        result["pm_10_0"] = {"value": reading.pm_10_0, "unit": "µg/m³"}

    if reading.voc is not None:
        result["voc"] = {
            "value": reading.voc,
            "unit": "index",
            "status": _get_health_status("voc", reading.voc),
        }

    if reading.nox is not None:
        result["nox"] = {"value": reading.nox, "unit": "index"}

    if reading.rssi is not None:
        result["rssi"] = {"value": reading.rssi, "unit": "dBm"}

    # RuuviTag motion/power fields
    if reading.acceleration_x is not None:
        result["acceleration"] = {
            "x": round(reading.acceleration_x, 3),
            "y": round(reading.acceleration_y, 3) if reading.acceleration_y is not None else 0,
            "z": round(reading.acceleration_z, 3) if reading.acceleration_z is not None else 0,
            "unit": "G",
        }

    if reading.battery_voltage is not None:
        result["battery"] = {"value": round(reading.battery_voltage, 2), "unit": "V"}

    if reading.movement_counter is not None:
        result["movement_counter"] = {"value": reading.movement_counter}

    if reading.tx_power is not None:
        result["tx_power"] = {"value": reading.tx_power, "unit": "dBm"}

    return result


MAX_POINTS_LIMIT = 200


@mcp.tool()
def query(
    start: str | None = None,
    end: str | None = None,
    resolution: Literal["auto", "raw", "1m", "5m", "15m", "1h", "6h", "1d"] = "auto",
    device: str | None = None,
) -> dict:
    """Query sensor data with flexible time ranges and resolution.

    Args:
        start: Start time - ISO datetime or relative like "-1h", "-24h", "-7d".
               Defaults to "-24h".
        end: End time - ISO datetime or relative. Defaults to now.
        resolution: Data resolution:
            - "auto": Smart sampling - raw if few points, else adaptive (default)
            - "raw": All readings, capped at 200 points
            - "1m", "5m", "15m", "1h", "6h", "1d": Fixed bucket aggregation
        device: Sensor nickname or MAC. Omit for all sensors (nested by device).

    Returns:
        Query metadata, summary statistics, and data points.
        Multi-device queries return data nested by device name.

    Examples:
        - query() - Last 24h, auto-sampled
        - query(start="-1h", resolution="raw") - Last hour, all points
        - query(start="-7d", resolution="1h") - Week of hourly averages
        - query(start="-48h", device="office") - 48h for specific sensor
    """
    # Parse time range
    start_dt = _parse_time(start, default=datetime.now() - timedelta(hours=24))
    end_dt = _parse_time(end, default=datetime.now())

    # Resolve device
    device_id = _resolve_device(device)

    # Build response
    result = {
        "query": {
            "start": start_dt.isoformat() if start_dt else None,
            "end": end_dt.isoformat() if end_dt else None,
            "resolution": resolution,
            "device": device,
        }
    }

    if device_id:
        # Single device query
        device_data = _query_single_device(start_dt, end_dt, device_id, resolution, MAX_POINTS_LIMIT)
        if "error" in device_data:
            return device_data
        result["summary"] = device_data.get("summary", {})
        result["data"] = device_data.get("data", [])
        result["query"]["resolution_used"] = device_data.get("resolution_used", resolution)
        if device_data.get("gaps"):
            result["gaps"] = device_data["gaps"]
    else:
        # Multi-device query - nested structure
        devices = storage.get_devices()
        if not devices:
            return {"error": "No data available"}

        result["devices"] = {}
        for dev_id in devices:
            device_data = _query_single_device(start_dt, end_dt, dev_id, resolution, MAX_POINTS_LIMIT)
            if device_data.get("data"):
                name = _get_device_name(dev_id)
                info = _get_device_info(dev_id)
                result["devices"][name] = {
                    "type": info["type"],
                    "summary": device_data.get("summary", {}),
                    "data": device_data.get("data", []),
                }
                if device_data.get("gaps"):
                    result["devices"][name]["gaps"] = device_data["gaps"]

    return result


def _query_single_device(
    start: datetime,
    end: datetime,
    device_id: str,
    resolution: str,
    max_points: int
) -> dict:
    """Query data for a single device."""
    # Fetch all readings in range (we'll sample/aggregate as needed)
    readings = storage.query(start=start, end=end, device_id=device_id, limit=50000)

    if not readings:
        return {"summary": {}, "data": [], "resolution_used": resolution}

    # Calculate summary from all readings
    summary = _calculate_summary(readings)
    summary["reading_count"] = len(readings)

    # Detect gaps
    gaps = _detect_gaps(readings)

    # Process based on resolution
    if resolution == "raw":
        # Return raw readings, capped at max_points (most recent)
        data_readings = readings[:max_points]
        data = [_format_reading(r, include_device=False) for r in data_readings]
        resolution_used = "raw"

    elif resolution == "auto":
        # Adaptive sampling
        sampled, resolution_used = _adaptive_sample(readings, max_points)
        data = [_format_reading(r, include_device=False) for r in sampled]

    else:
        # Fixed bucket aggregation
        bucket_seconds = RESOLUTION_SECONDS.get(resolution, 3600)
        data = _bucket_aggregate(readings, bucket_seconds)
        resolution_used = resolution

        # Check if result exceeds max_points
        if len(data) > max_points:
            return {
                "error": "Query produced too many results",
                "data_points": len(data),
                "max_allowed": max_points,
            }

    summary["data_points"] = len(data)

    # Calculate coverage (what % of expected readings we have)
    if len(readings) >= 2:
        time_span = (readings[0].timestamp - readings[-1].timestamp).total_seconds()
        expected_readings = time_span  # Roughly 1 reading per second
        coverage = min(1.0, len(readings) / expected_readings) if expected_readings > 0 else 1.0
        summary["coverage"] = round(coverage, 2)

    return {
        "context": _get_context(),
        "summary": summary,
        "data": data,
        "resolution_used": resolution_used,
        "gaps": gaps if gaps else None,
    }


@mcp.tool()
def list_sensors() -> dict:
    """List available sensors and data time range.

    Returns:
        - site: Global context for all sensors (location, climate, etc.)
        - sensors: List of sensors with nickname, type, description
        - data_range: First and last reading timestamps

    Call this first to discover what sensors and time periods are available.
    """
    # Get time range
    with storage._connect() as conn:
        row = conn.execute("""
            SELECT MIN(timestamp) as first, MAX(timestamp) as last
            FROM readings
        """).fetchone()

    result = {
        "data_range": {
            "first": row[0] if row else None,
            "last": row[1] if row else None,
        }
    }

    # Get site context (global info about all sensors)
    site = load_site()
    if site:
        result["site"] = site

    # Get configured devices
    sensors = []
    for device in load_devices():
        sensor_info = {
            "mac": device.mac,
            "nickname": device.nickname,
            "type": device.type,
        }
        if device.description:
            sensor_info["description"] = device.description
        sensors.append(sensor_info)

    # Also include devices found in database but not in config
    db_devices = storage.get_devices()
    configured_macs = {s["mac"].upper() for s in sensors}
    for dev_id in db_devices:
        if dev_id.upper() not in configured_macs:
            sensors.append({"mac": dev_id, "nickname": None, "type": "unknown"})

    result["sensors"] = sensors

    return result


def main():
    """Run the MCP server."""
    mcp.run(transport="stdio")


def test():
    """Quick test of all query modes."""
    import json

    def pp(label: str, data):
        print(f"\n{'='*60}\n{label}\n{'='*60}")
        print(json.dumps(data, indent=2, default=str))

    pp("LIST SENSORS", list_sensors())
    pp("CURRENT (all)", get_current())

    # New query API tests
    pp("QUERY auto (24h)", query())
    pp("QUERY raw (1h)", query(start="-1h", resolution="raw"))
    pp("QUERY hourly (48h)", query(start="-48h", resolution="1h"))
    pp("QUERY 5min buckets (4h)", query(start="-4h", resolution="5m"))


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        test()
    else:
        main()
