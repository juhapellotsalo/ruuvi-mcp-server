"""Ruuvi Cloud API client.

Fetches sensor data from Ruuvi Cloud (network.ruuvi.com).
Requires a paid Ruuvi Cloud subscription for historical data access.

Authentication flow:
1. Call request_verification(email) - sends code to your email
2. Call verify(email, code) - returns bearer token
3. Store token in config and use for all subsequent calls

API docs: https://docs.ruuvi.com/communicate-with-ruuvi-cloud/cloud/user-api
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from .decoder import decode_raw_data
from .models import SensorReading, format_reading


BASE_URL = "https://network.ruuvi.com"


@dataclass
class CloudSensor:
    """A sensor from the cloud API."""

    mac: str
    name: str
    owner: str
    is_owner: bool
    picture: str | None = None
    public: bool = False
    last_reading: SensorReading | None = None


class RuuviCloudError(Exception):
    """Error from Ruuvi Cloud API."""

    pass


class RuuviCloud:
    """Client for Ruuvi Cloud API."""

    def __init__(self, token: str | None = None):
        """Initialize client with optional bearer token."""
        self.token = token
        self._client = httpx.Client(base_url=BASE_URL, timeout=30.0)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self._client.close()

    def _headers(self) -> dict[str, str]:
        """Get headers for authenticated requests."""
        if not self.token:
            raise RuuviCloudError("No token set. Call verify() first.")
        return {"Authorization": f"Bearer {self.token}"}

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """Handle API response, raising on errors."""
        try:
            data = response.json()
        except Exception:
            raise RuuviCloudError(f"Invalid JSON response: {response.text}")

        if response.status_code == 401:
            raise RuuviCloudError("Invalid or expired token")
        if response.status_code == 429:
            raise RuuviCloudError("Rate limited - too many requests")
        if not response.is_success:
            error = data.get("error", response.text)
            raise RuuviCloudError(f"API error: {error}")

        return data

    # --- Authentication ---

    def request_verification(self, email: str) -> bool:
        """Request verification code to be sent to email.

        Returns True if successful.
        """
        response = self._client.post("/register", json={"email": email})
        data = self._handle_response(response)
        return data.get("result") == "success"

    def verify(self, code: str) -> str:
        """Verify with code and get bearer token.

        Args:
            code: Verification code from email

        Returns the bearer token to use for authenticated requests.
        Store this token securely - it's valid for 6 months of inactivity.
        """
        response = self._client.get("/verify", params={"token": code})
        data = self._handle_response(response)

        token = data.get("data", {}).get("accessToken")
        if not token:
            raise RuuviCloudError("No access token in response")

        self.token = token
        return token

    # --- User Info ---

    def get_user(self) -> dict[str, Any]:
        """Get current user information."""
        response = self._client.get("/user", headers=self._headers())
        data = self._handle_response(response)
        return data.get("data", {}).get("email", data)

    # --- Sensors ---

    def get_sensors(self, include_measurements: bool = True) -> list[CloudSensor]:
        """Get list of sensors with optional latest measurements.

        Args:
            include_measurements: If True, includes latest reading for each sensor

        Returns:
            List of CloudSensor objects
        """
        params = {}
        if include_measurements:
            params["measurements"] = "true"

        response = self._client.get(
            "/sensors-dense", headers=self._headers(), params=params
        )
        data = self._handle_response(response)

        sensors = []
        sensors_data = data.get("data", {}).get("sensors", [])
        user_email = data.get("data", {}).get("email", "")

        for sensor_data in sensors_data:
            mac = sensor_data.get("sensor", "")

            # Parse latest measurement if available
            last_reading = None
            measurements = sensor_data.get("measurements", [])
            if measurements:
                m = measurements[0]  # Most recent
                last_reading = self._parse_measurement(mac, m)

            sensors.append(
                CloudSensor(
                    mac=mac,
                    name=sensor_data.get("name", mac),
                    owner=sensor_data.get("owner", ""),
                    is_owner=sensor_data.get("owner") == user_email,
                    picture=sensor_data.get("picture"),
                    public=sensor_data.get("public", False),
                    last_reading=last_reading,
                )
            )

        return sensors

    def get_sensor_history(
        self,
        sensor_mac: str,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 5000,
    ) -> list[SensorReading]:
        """Get historical data for a sensor.

        Args:
            sensor_mac: MAC address of the sensor
            since: Start time (default: 24h ago)
            until: End time (default: now)
            limit: Max results (API caps at 5000)

        Returns:
            List of SensorReading objects, newest first
        """
        params: dict[str, Any] = {"sensor": sensor_mac, "limit": min(limit, 5000)}

        if since:
            params["since"] = int(since.timestamp())
        if until:
            params["until"] = int(until.timestamp())

        response = self._client.get("/get", headers=self._headers(), params=params)
        data = self._handle_response(response)

        readings = []
        for m in data.get("data", {}).get("measurements", []):
            reading = self._parse_measurement(sensor_mac, m)
            readings.append(reading)

        return readings

    def _parse_measurement(self, mac: str, m: dict[str, Any]) -> SensorReading:
        """Parse a measurement dict into a SensorReading."""
        timestamp = m.get("timestamp")
        if isinstance(timestamp, (int, float)):
            ts = datetime.fromtimestamp(timestamp)
        else:
            ts = datetime.fromisoformat(timestamp) if timestamp else datetime.now()

        rssi = m.get("rssi")

        # Cloud API returns raw hex data that needs decoding
        raw_data = m.get("data")
        if raw_data:
            decoded = decode_raw_data(raw_data)
            if decoded:
                return SensorReading(
                    device_id=mac,
                    timestamp=ts,
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

        # Fallback if no raw data or decoding failed
        return SensorReading(
            device_id=mac,
            timestamp=ts,
            rssi=rssi,
        )


# --- CLI for testing ---

if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Ruuvi Cloud API client")
    parser.add_argument("--token", help="Bearer token for authentication")
    parser.add_argument("--email", help="Email for authentication")
    parser.add_argument("--code", help="Verification code from email")
    parser.add_argument("--sensors", action="store_true", help="List sensors")
    parser.add_argument("--history", metavar="MAC", help="Get history for sensor MAC")
    parser.add_argument("--limit", type=int, default=10, help="Number of readings")

    args = parser.parse_args()

    if args.email and args.code:
        # Verify and get token
        with RuuviCloud() as cloud:
            token = cloud.verify(args.code)
            print(f"Token: {token}")
            print("\nStore this in your config.yaml under cloud.token")
        sys.exit(0)

    if args.email and not args.code:
        # Request verification
        with RuuviCloud() as cloud:
            cloud.request_verification(args.email)
            print(f"Verification code sent to {args.email}")
            print("Run again with --code <code> to get your token")
        sys.exit(0)

    if not args.token:
        print("Error: --token required (or use --email to authenticate)")
        sys.exit(1)

    with RuuviCloud(args.token) as cloud:
        if args.sensors:
            sensors = cloud.get_sensors()
            print(f"Found {len(sensors)} sensors:\n")
            for s in sensors:
                owner_str = "(owner)" if s.is_owner else "(shared)"
                print(f"  {s.mac}  {s.name}  {owner_str}")
                if s.last_reading:
                    print(f"    Latest: {format_reading(s.last_reading, include_date=True)}")
            sys.exit(0)

        if args.history:
            readings = cloud.get_sensor_history(args.history, limit=args.limit)
            print(f"Last {len(readings)} readings for {args.history}:\n")
            for r in readings:
                print(f"  {format_reading(r, include_date=True)}")
            sys.exit(0)

        # Default: show sensors
        print("Use --sensors or --history MAC")
