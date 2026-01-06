"""HTTP client for polling Ruuvi Gateway /history endpoint."""

import asyncio
from datetime import datetime
from typing import AsyncIterator

import httpx

from .config import GatewayConfig
from .models import GatewayReading


class GatewayClient:
    """Client for polling Ruuvi Gateway /history endpoint."""

    def __init__(self, config: GatewayConfig):
        self.config = config
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self):
        self._client = httpx.AsyncClient(timeout=10.0)
        return self

    async def __aexit__(self, *args):
        if self._client:
            await self._client.aclose()

    async def fetch_readings(self) -> list[GatewayReading]:
        """Fetch current readings from all sensors."""
        if not self._client:
            raise RuntimeError("Client not initialized. Use 'async with' context.")

        url = f"{self.config.url.rstrip('/')}/history"
        headers = {}
        if self.config.token:
            headers["Authorization"] = f"Bearer {self.config.token}"

        response = await self._client.get(url, headers=headers)
        response.raise_for_status()

        data = response.json()
        return self._parse_response(data)

    def _parse_response(self, data: dict) -> list[GatewayReading]:
        """Parse Gateway /history JSON response into readings."""
        readings = []
        gateway_data = data.get("data", {})
        gateway_mac = gateway_data.get("gw_mac")
        tags = gateway_data.get("tags", {})

        for mac, tag_data in tags.items():
            reading = GatewayReading(
                device_id=mac,
                timestamp=datetime.fromtimestamp(tag_data.get("timestamp", 0)),
                measurement_sequence=tag_data.get("measurementSequenceNumber", 0),
                data_format=tag_data.get("dataFormat"),
                temperature=tag_data.get("temperature"),
                humidity=tag_data.get("humidity"),
                pressure=tag_data.get("pressure"),
                # Air quality fields
                co2=tag_data.get("CO2"),
                voc=tag_data.get("VOC"),
                nox=tag_data.get("NOx"),
                pm_1_0=tag_data.get("PM1.0"),
                pm_2_5=tag_data.get("PM2.5"),
                pm_4_0=tag_data.get("PM4.0"),
                pm_10_0=tag_data.get("PM10.0"),
                # Tag motion/power fields
                acceleration_x=tag_data.get("accelX"),
                acceleration_y=tag_data.get("accelY"),
                acceleration_z=tag_data.get("accelZ"),
                movement_counter=tag_data.get("movementCounter"),
                battery_voltage=tag_data.get("voltage"),
                tx_power=tag_data.get("txPower"),
                rssi=tag_data.get("rssi"),
                gateway_mac=gateway_mac,
            )
            readings.append(reading)

        return readings

    async def stream_readings(self) -> AsyncIterator[GatewayReading]:
        """
        Stream sensor readings continuously, yielding only new readings.

        Deduplicates based on measurement_sequence per device.
        """
        last_sequence: dict[str, int] = {}

        while True:
            try:
                readings = await self.fetch_readings()

                for reading in readings:
                    device = reading.device_id
                    seq = reading.measurement_sequence

                    # Only yield if sequence number changed (new data)
                    if device not in last_sequence or last_sequence[device] != seq:
                        last_sequence[device] = seq
                        yield reading

            except httpx.HTTPError as e:
                # Log error but continue polling
                print(f"Gateway error: {e}")

            await asyncio.sleep(self.config.poll_interval)
