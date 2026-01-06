"""SQLite storage for Ruuvi sensor time series data."""

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from .models import SensorReading


DEFAULT_DB_PATH = Path(__file__).parent.parent / "data" / "readings.db"


class SensorStorage:
    """SQLite storage for sensor readings."""

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Initialize database schema."""
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS readings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id TEXT NOT NULL,
                    data_format INTEGER,
                    timestamp TEXT NOT NULL,
                    temperature REAL,
                    humidity REAL,
                    pressure REAL,
                    co2 INTEGER,
                    pm_1_0 REAL,
                    pm_2_5 REAL,
                    pm_4_0 REAL,
                    pm_10_0 REAL,
                    voc INTEGER,
                    nox INTEGER,
                    luminosity REAL,
                    rssi INTEGER
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_readings_timestamp
                ON readings(timestamp)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_readings_device_timestamp
                ON readings(device_id, timestamp)
            """)

            # Migrate existing databases: add new columns if missing
            self._migrate_schema(conn)

            conn.commit()

    def _migrate_schema(self, conn):
        """Add missing columns and indexes to existing databases."""
        cursor = conn.execute("PRAGMA table_info(readings)")
        existing_columns = {row[1] for row in cursor.fetchall()}

        new_columns = [
            ("data_format", "INTEGER"),
            ("measurement_sequence", "INTEGER"),
            ("pm_1_0", "REAL"),
            ("pm_4_0", "REAL"),
            ("pm_10_0", "REAL"),
            ("luminosity", "REAL"),
            ("rssi", "INTEGER"),
            # RuuviTag motion/power fields
            ("acceleration_x", "REAL"),
            ("acceleration_y", "REAL"),
            ("acceleration_z", "REAL"),
            ("movement_counter", "INTEGER"),
            ("battery_voltage", "REAL"),
            ("tx_power", "INTEGER"),
        ]

        for col_name, col_type in new_columns:
            if col_name not in existing_columns:
                conn.execute(f"ALTER TABLE readings ADD COLUMN {col_name} {col_type}")

        # Drop old deduplication index (was based on measurement_sequence)
        conn.execute("DROP INDEX IF EXISTS idx_readings_device_sequence")

        # Add unique index for deduplication (device_id + timestamp)
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_readings_device_timestamp_unique
            ON readings(device_id, timestamp)
        """)

    @contextmanager
    def _connect(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def insert(self, reading: SensorReading) -> bool:
        """Insert a single reading, skipping duplicates.

        Auto-registers unknown devices with generated nicknames.
        Returns True if inserted, False if duplicate (based on device_id + timestamp).
        """
        # Auto-register device if not known
        if reading.device_id:
            from ruuvi_data.devices import auto_register_device
            auto_register_device(reading.device_id, reading.data_format)

        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO readings (
                    device_id, data_format, measurement_sequence, timestamp,
                    temperature, humidity, pressure,
                    co2, pm_1_0, pm_2_5, pm_4_0, pm_10_0,
                    voc, nox, luminosity, rssi,
                    acceleration_x, acceleration_y, acceleration_z,
                    movement_counter, battery_voltage, tx_power
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    reading.device_id,
                    reading.data_format,
                    reading.measurement_sequence,
                    reading.timestamp.strftime("%Y-%m-%dT%H:%M:%S"),
                    reading.temperature,
                    reading.humidity,
                    reading.pressure,
                    reading.co2,
                    reading.pm_1_0,
                    reading.pm_2_5,
                    reading.pm_4_0,
                    reading.pm_10_0,
                    reading.voc,
                    reading.nox,
                    reading.luminosity,
                    reading.rssi,
                    reading.acceleration_x,
                    reading.acceleration_y,
                    reading.acceleration_z,
                    reading.movement_counter,
                    reading.battery_voltage,
                    reading.tx_power,
                ),
            )
            conn.commit()
            return cursor.rowcount > 0

    def query(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        device_id: str | None = None,
        limit: int | None = None,
    ) -> list[SensorReading]:
        """
        Query readings within a time range.

        Args:
            start: Start of time range (inclusive)
            end: End of time range (inclusive)
            device_id: Filter by device ID
            limit: Maximum number of results

        Returns:
            List of SensorReading objects, ordered by timestamp descending
        """
        conditions = []
        params = []

        if start:
            conditions.append("timestamp >= ?")
            params.append(start.isoformat())
        if end:
            conditions.append("timestamp <= ?")
            params.append(end.isoformat())
        if device_id:
            conditions.append("device_id = ?")
            params.append(device_id)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        limit_clause = f"LIMIT {limit}" if limit else ""

        query = f"""
            SELECT * FROM readings
            {where_clause}
            ORDER BY timestamp DESC
            {limit_clause}
        """

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()

        return [self._row_to_reading(row) for row in rows]

    def get_latest(self, device_id: str | None = None) -> SensorReading | None:
        """Get the most recent reading."""
        results = self.query(device_id=device_id, limit=1)
        return results[0] if results else None

    def get_devices(self) -> list[str]:
        """Get list of unique device IDs in the database."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT device_id FROM readings"
            ).fetchall()
        return [row["device_id"] for row in rows]

    def count(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        device_id: str | None = None,
    ) -> int:
        """Count readings matching the criteria."""
        conditions = []
        params = []

        if start:
            conditions.append("timestamp >= ?")
            params.append(start.isoformat())
        if end:
            conditions.append("timestamp <= ?")
            params.append(end.isoformat())
        if device_id:
            conditions.append("device_id = ?")
            params.append(device_id)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        with self._connect() as conn:
            result = conn.execute(
                f"SELECT COUNT(*) as count FROM readings {where_clause}", params
            ).fetchone()

        return result["count"]

    @staticmethod
    def _row_to_reading(row: sqlite3.Row) -> SensorReading:
        """Convert a database row to a SensorReading."""
        keys = row.keys()
        return SensorReading(
            device_id=row["device_id"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            data_format=row["data_format"] if "data_format" in keys else None,
            measurement_sequence=row["measurement_sequence"] if "measurement_sequence" in keys else None,
            temperature=row["temperature"],
            humidity=row["humidity"],
            pressure=row["pressure"],
            co2=row["co2"],
            pm_1_0=row["pm_1_0"] if "pm_1_0" in keys else None,
            pm_2_5=row["pm_2_5"],
            pm_4_0=row["pm_4_0"] if "pm_4_0" in keys else None,
            pm_10_0=row["pm_10_0"] if "pm_10_0" in keys else None,
            voc=row["voc"],
            nox=row["nox"],
            luminosity=row["luminosity"] if "luminosity" in keys else None,
            rssi=row["rssi"] if "rssi" in keys else None,
            acceleration_x=row["acceleration_x"] if "acceleration_x" in keys else None,
            acceleration_y=row["acceleration_y"] if "acceleration_y" in keys else None,
            acceleration_z=row["acceleration_z"] if "acceleration_z" in keys else None,
            movement_counter=row["movement_counter"] if "movement_counter" in keys else None,
            battery_voltage=row["battery_voltage"] if "battery_voltage" in keys else None,
            tx_power=row["tx_power"] if "tx_power" in keys else None,
        )
