"""
MeasurementDatabase – drop-in replacement for the old Database
=============================================================

Implements auto-generated codenames, FTS search, NumPy+Polars BLOB handling,
and a convenience, thread-safe API.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import lzma
import pickle
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from .experiments import Experiment
from .results import MeasurementResult
from .uncertainty_serialization import deserialize_uncertain_value
from .uncertainty_serialization import serialize_uncertain_value


# --- DUMMY DatabaseBackup for mkdocstrings compatibility ---
class DatabaseBackup:
    """
    Dummy DatabaseBackup class for documentation compatibility.
    This is not used in runtime code, but allows mkdocstrings to resolve
    'pytestlab.experiments.DatabaseBackup' for API docs.
    """

    pass


__all__ = ["Database", "MeasurementDatabase"]


_NUMPY_BLOB_PREFIX = b"PYTESTLAB:NUMPY:\x00"
_POLARS_BLOB_PREFIX = b"PYTESTLAB:POLARS:\x00"


def _generate_codename(prefix: str = "ITEM") -> str:
    """Generate a unique codename using timestamp and random hash."""
    timestamp = str(int(time.time() * 1000))  # milliseconds
    random_hash = hashlib.md5(str(time.time()).encode()).hexdigest()[:8]
    return f"{prefix}_{timestamp}_{random_hash}"


class MeasurementDatabase(contextlib.AbstractContextManager):
    """
    Enhanced SQLite database for measurement and experiment storage.

    Features:
    - Auto-generated unique codenames
    - Full-text search across descriptions/notes
    - Context manager support
    - Thread-safe operations
    - NumPy array and Polars DataFrame BLOB handling
    - Comprehensive experiment/measurement metadata

    Example:
        >>> with MeasurementDatabase("lab_data") as db:
        ...     key = db.store_experiment(None, experiment)  # auto-generated key
        ...     results = db.search_experiments("voltage sweep")
    """

    def __init__(self, db_path: str | Path) -> None:
        """
        Initialize database connection and create tables.

        Args:
            db_path: Database file path (without .db extension)
        """
        self.db_path = Path(str(db_path)).with_suffix(".db")
        self._conn_lock = threading.Lock()
        self._thread_connections = threading.local()
        self._connections: set[sqlite3.Connection] = set()

        # Register custom adapters for NumPy/Polars
        sqlite3.register_adapter(np.ndarray, self._adapt_numpy)
        sqlite3.register_converter("NPBLOB", self._convert_numpy)
        sqlite3.register_adapter(pl.DataFrame, self._adapt_polars)
        sqlite3.register_converter("PLBLOB", self._convert_polars)

        # Register custom datetime adapters to avoid Python 3.12 deprecation warnings
        sqlite3.register_adapter(dt.datetime, self._adapt_datetime)
        sqlite3.register_converter("DATETIME", self._convert_datetime)

        self._ensure_tables()

    # Context manager support
    def __enter__(self) -> MeasurementDatabase:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    # Connection management
    def _get_connection(self) -> sqlite3.Connection:
        """Get the calling thread's database connection."""
        conn = getattr(self._thread_connections, "connection", None)
        with self._conn_lock:
            if conn is not None and conn in self._connections:
                return conn

            conn = sqlite3.connect(
                self.db_path,
                detect_types=sqlite3.PARSE_DECLTYPES,
                check_same_thread=False,
                timeout=30.0,
            )
            try:
                conn.execute("PRAGMA foreign_keys = ON")
                conn.execute("PRAGMA busy_timeout = 30000")
                conn.execute("PRAGMA journal_mode = WAL")
            except Exception:
                conn.close()
                raise
            self._connections.add(conn)
            self._thread_connections.connection = conn
            return conn

    def close(self) -> None:
        """Close every connection owned by this database instance."""
        with self._conn_lock:
            for conn in self._connections:
                conn.close()
            self._connections.clear()
            self._thread_connections.connection = None

    # Binary serialization
    @staticmethod
    def _adapt_numpy(arr: np.ndarray) -> sqlite3.Binary:
        """Serialize NumPy array to binary with metadata."""
        if not isinstance(arr, np.ndarray):
            raise TypeError(f"Expected numpy array, got {type(arr)}")

        metadata = {"dtype": str(arr.dtype), "shape": arr.shape, "compressed": True}

        data_bytes = lzma.compress(arr.tobytes())
        metadata_bytes = pickle.dumps(metadata)

        # Format: [metadata_length:4][metadata][data]
        payload = len(metadata_bytes).to_bytes(4, "little") + metadata_bytes + data_bytes
        return sqlite3.Binary(_NUMPY_BLOB_PREFIX + payload)

    @staticmethod
    def _convert_numpy(blob: bytes) -> np.ndarray | pl.DataFrame:
        """Deserialize tagged and legacy NumPy or Polars binary data."""
        if blob.startswith(_POLARS_BLOB_PREFIX):
            return MeasurementDatabase._convert_polars(blob)
        if blob.startswith(_NUMPY_BLOB_PREFIX):
            blob = blob[len(_NUMPY_BLOB_PREFIX) :]

        # Check if this is an LZMA file (XZ signature)
        if blob[:7] == b"\xfd\x37\x7a\x58\x5a\x00\x00":
            try:
                # Direct LZMA compressed data without our metadata header
                decompressed = lzma.decompress(blob)
                # Try to read as a pickled numpy array
                return pickle.loads(decompressed)
            except Exception:
                # If that fails, try a legacy Polars Arrow IPC payload
                try:
                    return pl.read_ipc(decompressed)
                except Exception:
                    pass

        try:
            metadata_len = int.from_bytes(blob[:4], "little")
            metadata = pickle.loads(blob[4 : 4 + metadata_len])
            data_bytes = blob[4 + metadata_len :]

            if metadata.get("compressed", False):
                data_bytes = lzma.decompress(data_bytes)

            return np.frombuffer(data_bytes, dtype=metadata["dtype"]).reshape(metadata["shape"])
        except Exception as e:
            # Fallback for legacy or corrupted data
            try:
                # Try direct unpickling (old format)
                return pickle.loads(blob)
            except Exception:
                # Try one more approach - direct decompression if it's just compressed data
                try:
                    if blob[:7] == b"\xfd\x37\x7a\x58\x5a\x00\x00":
                        decompressed = lzma.decompress(blob)
                        # Try as simple numpy array
                        return np.frombuffer(decompressed, dtype=np.float64)
                except Exception:
                    pass

                # If all else fails, raise original error
                raise ValueError(f"Failed to deserialize numpy array: {e}") from e

    @staticmethod
    def _adapt_polars(df: pl.DataFrame) -> sqlite3.Binary:
        """Serialize Polars DataFrame using Arrow IPC + compression."""
        ipc_data = df.write_ipc(None).getvalue()
        compressed = lzma.compress(ipc_data)
        return sqlite3.Binary(_POLARS_BLOB_PREFIX + compressed)

    @staticmethod
    def _convert_polars(blob: bytes) -> pl.DataFrame:
        """Deserialize compressed Arrow IPC back to Polars DataFrame."""
        if blob.startswith(_POLARS_BLOB_PREFIX):
            blob = blob[len(_POLARS_BLOB_PREFIX) :]
        elif blob.startswith(_NUMPY_BLOB_PREFIX):
            blob = blob[len(_NUMPY_BLOB_PREFIX) :]

        # Check if this is an LZMA file (XZ signature)
        if blob[:7] == b"\xfd\x37\x7a\x58\x5a\x00\x00":
            try:
                # Direct LZMA compressed data
                decompressed = lzma.decompress(blob)
                # Try to read as Arrow IPC
                return pl.read_ipc(decompressed)
            except Exception:
                # If that fails, try to unpickle the decompressed data and ensure DataFrame
                try:
                    obj = pickle.loads(decompressed)
                    if isinstance(obj, pl.DataFrame):
                        return obj
                    raise ValueError("Unpickled object is not a Polars DataFrame")
                except Exception:
                    pass

        try:
            decompressed = lzma.decompress(blob)
            return pl.read_ipc(decompressed)
        except Exception as e:
            # Fallback for legacy or corrupted data
            try:
                # Try direct unpickling (old format)
                return pickle.loads(blob)
            except Exception:
                # If that fails, try to read as raw Arrow IPC (uncompressed)
                try:
                    return pl.read_ipc(blob)
                except Exception:
                    # One last attempt - try to create a DataFrame from a numpy array
                    try:
                        arr = MeasurementDatabase._convert_numpy(blob)
                        if isinstance(arr, np.ndarray):
                            if arr.ndim == 1:
                                return pl.DataFrame({"values": arr})
                            else:
                                # Create a column for each dimension
                                data = {f"column_{i}": arr[:, i] for i in range(arr.shape[1])}
                                return pl.DataFrame(data)
                    except Exception:
                        pass

                    # If all else fails, raise original error
                    raise ValueError(f"Failed to deserialize Polars DataFrame: {e}") from e

    # Custom datetime handling to avoid Python 3.12 deprecation warnings
    @staticmethod
    def _adapt_datetime(dt_obj: dt.datetime) -> str:
        """Convert datetime to ISO format string."""
        return dt_obj.isoformat()

    @staticmethod
    def _convert_datetime(iso_string: bytes) -> dt.datetime:
        """Convert ISO format string back to datetime."""
        return dt.datetime.fromisoformat(iso_string.decode())

    # Database schema
    def _ensure_tables(self) -> None:
        """Create database tables if they don't exist."""
        conn = self._get_connection()
        with conn:
            # Experiments table with FTS support
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS experiments (
                    codename TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    notes TEXT,
                    data PLBLOB,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    metadata TEXT  -- JSON for extensibility
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS experiments_fts USING fts5(
                    codename, name, description, notes,
                    content='experiments'
                );
            """)
            self._ensure_fts_sync(
                conn,
                table="experiments",
                fts_table="experiments_fts",
                columns=("codename", "name", "description", "notes"),
            )

            # Experiment parameters
            conn.execute("""
                CREATE TABLE IF NOT EXISTS experiment_parameters (
                    codename TEXT,
                    param_name TEXT,
                    param_unit TEXT,
                    param_notes TEXT,
                    FOREIGN KEY (codename) REFERENCES experiments(codename) ON DELETE CASCADE
                );
            """)

            # Instruments
            conn.execute("""
                CREATE TABLE IF NOT EXISTS instruments (
                    instrument_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL
                );
            """)

            # Measurements with FTS
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS measurements (
                    codename TEXT PRIMARY KEY,
                    instrument_id INTEGER,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    value_data NPBLOB NOT NULL,
                    units TEXT,
                    measurement_type TEXT,
                    notes TEXT,
                    metadata TEXT,  -- JSON for extensibility
                    FOREIGN KEY (instrument_id) REFERENCES instruments(instrument_id)
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS measurements_fts USING fts5(
                    codename, measurement_type, notes,
                    content='measurements'
                );
            """)
            self._ensure_fts_sync(
                conn,
                table="measurements",
                fts_table="measurements_fts",
                columns=("codename", "measurement_type", "notes"),
            )
            self._migrate_measurements_table(conn)

            # Indices for performance
            conn.execute("CREATE INDEX IF NOT EXISTS idx_exp_created ON experiments(created_at);")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_meas_timestamp ON measurements(timestamp);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_meas_type ON measurements(measurement_type);"
            )

    @staticmethod
    def _migrate_measurements_table(conn: sqlite3.Connection) -> None:
        """Add columns required by newer measurement serializers to existing DBs."""

        columns = {row[1] for row in conn.execute("PRAGMA table_info(measurements)")}
        if "metadata" not in columns:
            conn.execute("ALTER TABLE measurements ADD COLUMN metadata TEXT")

    @staticmethod
    def _ensure_fts_sync(
        conn: sqlite3.Connection,
        *,
        table: str,
        fts_table: str,
        columns: tuple[str, ...],
    ) -> None:
        """Install rowid-aware FTS triggers and rebuild legacy indexes once."""

        trigger_names = {
            action: f"{fts_table}_{action}" for action in ("insert", "delete", "update")
        }
        trigger_sql = {
            row[0]: (row[1] or "").lower()
            for row in conn.execute(
                "SELECT name, sql FROM sqlite_master WHERE type = 'trigger' AND tbl_name = ?",
                (table,),
            )
        }
        is_current = (
            "new.rowid" in trigger_sql.get(trigger_names["insert"], "")
            and "'delete'" in trigger_sql.get(trigger_names["delete"], "")
            and "old.rowid" in trigger_sql.get(trigger_names["delete"], "")
            and "'delete'" in trigger_sql.get(trigger_names["update"], "")
            and "old.rowid" in trigger_sql.get(trigger_names["update"], "")
            and "new.rowid" in trigger_sql.get(trigger_names["update"], "")
        )
        if is_current:
            return

        for trigger_name in trigger_names.values():
            conn.execute(f"DROP TRIGGER IF EXISTS {trigger_name}")

        column_list = ", ".join(columns)
        new_values = ", ".join(f"new.{column}" for column in columns)
        old_values = ", ".join(f"old.{column}" for column in columns)
        conn.executescript(f"""
            CREATE TRIGGER {trigger_names["insert"]} AFTER INSERT ON {table}
            BEGIN
                INSERT INTO {fts_table}(rowid, {column_list})
                VALUES (new.rowid, {new_values});
            END;

            CREATE TRIGGER {trigger_names["delete"]} AFTER DELETE ON {table}
            BEGIN
                INSERT INTO {fts_table}({fts_table}, rowid, {column_list})
                VALUES ('delete', old.rowid, {old_values});
            END;

            CREATE TRIGGER {trigger_names["update"]} AFTER UPDATE ON {table}
            BEGIN
                INSERT INTO {fts_table}({fts_table}, rowid, {column_list})
                VALUES ('delete', old.rowid, {old_values});
                INSERT INTO {fts_table}(rowid, {column_list})
                VALUES (new.rowid, {new_values});
            END;
        """)
        conn.execute(f"INSERT INTO {fts_table}({fts_table}) VALUES ('rebuild')")

    # Instrument management
    def _get_or_create_instrument_id(self, conn: sqlite3.Connection, instrument_name: str) -> int:
        """Atomically get or create an instrument ID."""
        conn.execute(
            "INSERT INTO instruments (name) VALUES (?) ON CONFLICT(name) DO NOTHING",
            (instrument_name,),
        )
        row = conn.execute(
            "SELECT instrument_id FROM instruments WHERE name = ?", (instrument_name,)
        ).fetchone()
        if row is None:
            raise RuntimeError("Failed to create instrument")
        return int(row[0])

    # Experiment operations
    def store_experiment(
        self,
        codename: str | None,
        experiment: Experiment,
        *,
        overwrite: bool = True,
        notes: str = "",
    ) -> str:
        """
        Store an experiment in the database.

        Args:
            codename: Unique identifier (auto-generated if None)
            experiment: Experiment instance to store
            overwrite: Whether to allow overwriting existing experiments
            notes: Additional notes for this experiment

        Returns:
            The final codename used for storage

        Raises:
            ValueError: If codename exists and overwrite=False
        """
        if codename is None:
            codename = _generate_codename("EXP")

        conn = self._get_connection()
        with conn:
            # Store experiment
            try:
                conn.execute(
                    """
                    INSERT INTO experiments
                    (codename, name, description, notes, data, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(codename) DO UPDATE SET
                        name = excluded.name,
                        description = excluded.description,
                        notes = excluded.notes,
                        data = excluded.data,
                        created_at = excluded.created_at,
                        metadata = NULL
                    """
                    if overwrite
                    else """
                    INSERT INTO experiments
                    (codename, name, description, notes, data, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        codename,
                        experiment.name,
                        experiment.description,
                        notes,
                        experiment.data,
                        dt.datetime.now(),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                if overwrite:
                    raise
                raise ValueError(f"Experiment '{codename}' already exists") from exc

            # Store parameters
            conn.execute("DELETE FROM experiment_parameters WHERE codename = ?", (codename,))
            for param in experiment.parameters.values():
                param_notes = getattr(param, "notes", "")
                conn.execute(
                    """
                    INSERT INTO experiment_parameters (codename, param_name, param_unit, param_notes)
                    VALUES (?, ?, ?, ?)
                """,
                    (codename, param.name, param.units, param_notes),
                )

        return codename

    def retrieve_experiment(self, codename: str) -> Experiment:
        """
        Retrieve an experiment by codename.

        Args:
            codename: Unique experiment identifier

        Returns:
            Loaded Experiment instance

        Raises:
            ValueError: If experiment not found
        """
        conn = self._get_connection()
        cursor = conn.execute(
            """
            SELECT name, description, notes, data
            FROM experiments
            WHERE codename = ?
        """,
            (codename,),
        )

        row = cursor.fetchone()
        if not row:
            raise ValueError(f"Experiment '{codename}' not found")

        name, description, notes, data = row

        # Reconstruct experiment
        experiment = Experiment(name, description)
        experiment.data = data
        experiment.notes = notes

        # Load parameters
        cursor = conn.execute(
            """
            SELECT param_name, param_unit, param_notes
            FROM experiment_parameters
            WHERE codename = ?
        """,
            (codename,),
        )

        for param_name, param_unit, param_notes in cursor.fetchall():
            experiment.add_parameter(param_name, param_unit, param_notes)

        return experiment

    def list_experiments(self, limit: int | None = None) -> list[str]:
        """List all experiment codenames, newest first."""
        conn = self._get_connection()
        query = "SELECT codename FROM experiments ORDER BY created_at DESC"
        if limit:
            query += f" LIMIT {limit}"

        cursor = conn.execute(query)
        return [row[0] for row in cursor.fetchall()]

    def search_experiments(self, query: str, limit: int = 50) -> list[dict[str, Any]]:
        """
        Full-text search across experiments.

        Args:
            query: Search terms
            limit: Maximum results to return

        Returns:
            List of dicts with experiment metadata
        """
        conn = self._get_connection()
        cursor = conn.execute(
            """
            SELECT e.codename, e.name, e.description, e.notes, e.created_at
            FROM experiments_fts f
            JOIN experiments e ON f.codename = e.codename
            WHERE experiments_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        """,
            (query, limit),
        )

        return [
            {
                "codename": row[0],
                "name": row[1],
                "description": row[2],
                "notes": row[3],
                "created_at": row[4],
            }
            for row in cursor.fetchall()
        ]

    # Measurement operations
    def store_measurement(
        self,
        codename: str | None,
        measurement: MeasurementResult,
        *,
        overwrite: bool = True,
        notes: str = "",
    ) -> str:
        """
        Store a measurement result.

        Args:
            codename: Unique identifier (auto-generated if None)
            measurement: MeasurementResult to store
            overwrite: Whether to allow overwriting existing measurements
            notes: Additional notes

        Returns:
            The final codename used for storage

        Raises:
            ValueError: If codename exists and overwrite=False
        """
        if codename is None:
            codename = _generate_codename("MEAS")

        conn = self._get_connection()
        with conn:
            # Get instrument ID
            instrument_id = self._get_or_create_instrument_id(conn, measurement.instrument)

            value_data, metadata = serialize_uncertain_value(measurement.values)
            envelope = getattr(measurement, "envelope", None)
            if envelope:
                metadata = dict(metadata)
                metadata["measurement_envelope"] = envelope

            # Store measurement
            try:
                conn.execute(
                    """
                    INSERT INTO measurements
                    (codename, instrument_id, timestamp, value_data, units, measurement_type, notes, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(codename) DO UPDATE SET
                        instrument_id = excluded.instrument_id,
                        timestamp = excluded.timestamp,
                        value_data = excluded.value_data,
                        units = excluded.units,
                        measurement_type = excluded.measurement_type,
                        notes = excluded.notes,
                        metadata = excluded.metadata
                    """
                    if overwrite
                    else """
                    INSERT INTO measurements
                    (codename, instrument_id, timestamp, value_data, units, measurement_type, notes, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        codename,
                        instrument_id,
                        dt.datetime.fromtimestamp(measurement.timestamp),
                        value_data,
                        measurement.units,
                        measurement.measurement_type,
                        notes,
                        json.dumps(metadata) if metadata else None,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                if overwrite:
                    raise
                raise ValueError(f"Measurement '{codename}' already exists") from exc

        return codename

    def retrieve_measurement(self, codename: str) -> MeasurementResult:
        """
        Retrieve a measurement by codename.

        Args:
            codename: Unique measurement identifier

        Returns:
            Loaded MeasurementResult instance

        Raises:
            ValueError: If measurement not found
        """
        conn = self._get_connection()
        cursor = conn.execute(
            """
            SELECT i.name, m.timestamp, m.value_data, m.units, m.measurement_type, m.metadata
            FROM measurements m
            JOIN instruments i ON m.instrument_id = i.instrument_id
            WHERE m.codename = ?
        """,
            (codename,),
        )

        row = cursor.fetchone()
        if not row:
            raise ValueError(f"Measurement '{codename}' not found")

        instrument, timestamp, value_data, units, measurement_type, metadata_raw = row
        envelope = {}
        if metadata_raw:
            try:
                metadata = json.loads(metadata_raw)
            except json.JSONDecodeError:
                metadata = {}
            envelope = metadata.pop("measurement_envelope", {}) or {}
            value_data = deserialize_uncertain_value(value_data, metadata)

        return MeasurementResult(
            values=value_data,
            instrument=instrument,
            units=units,
            measurement_type=measurement_type,
            timestamp=timestamp.timestamp() if hasattr(timestamp, "timestamp") else time.time(),
            envelope=envelope,
        )

    def list_measurements(
        self, instrument: str | None = None, limit: int | None = None
    ) -> list[str]:
        """
        List measurement codenames, optionally filtered by instrument.

        Args:
            instrument: Filter by instrument name
            limit: Maximum results to return

        Returns:
            List of measurement codenames
        """
        conn = self._get_connection()

        params: tuple[str, ...]
        if instrument:
            query = """
                SELECT m.codename
                FROM measurements m
                JOIN instruments i ON m.instrument_id = i.instrument_id
                WHERE i.name = ?
                ORDER BY m.timestamp DESC
            """
            params = (instrument,)
        else:
            query = "SELECT codename FROM measurements ORDER BY timestamp DESC"
            params = ()

        if limit:
            query += f" LIMIT {limit}"

        cursor = conn.execute(query, params)
        return [row[0] for row in cursor.fetchall()]

    def search_measurements(self, query: str, limit: int = 50) -> list[dict[str, Any]]:
        """
        Full-text search across measurements.

        Args:
            query: Search terms
            limit: Maximum results to return

        Returns:
            List of dicts with measurement metadata
        """
        conn = self._get_connection()

        # First try the FTS table
        cursor = conn.execute(
            """
            SELECT m.codename, i.name, m.measurement_type, m.units, m.timestamp, m.notes
            FROM measurements_fts f
            JOIN measurements m ON f.codename = m.codename
            JOIN instruments i ON m.instrument_id = i.instrument_id
            WHERE measurements_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        """,
            (query, limit),
        )

        results = [
            {
                "codename": row[0],
                "instrument": row[1],
                "measurement_type": row[2],
                "units": row[3],
                "timestamp": row[4],
                "notes": row[5],
            }
            for row in cursor.fetchall()
        ]

        # If no results from FTS, try direct instrument name matching
        if not results:
            cursor = conn.execute(
                """
                SELECT m.codename, i.name, m.measurement_type, m.units, m.timestamp, m.notes
                FROM measurements m
                JOIN instruments i ON m.instrument_id = i.instrument_id
                WHERE i.name LIKE ? OR m.measurement_type LIKE ?
                ORDER BY m.timestamp DESC
                LIMIT ?
            """,
                (f"%{query}%", f"%{query}%", limit),
            )

            results = [
                {
                    "codename": row[0],
                    "instrument": row[1],
                    "measurement_type": row[2],
                    "units": row[3],
                    "timestamp": row[4],
                    "notes": row[5],
                }
                for row in cursor.fetchall()
            ]

        return results

    def get_stats(self) -> dict[str, int]:
        """Get database statistics."""
        conn = self._get_connection()

        stats = {}
        stats["experiments"] = conn.execute("SELECT COUNT(*) FROM experiments").fetchone()[0]
        stats["measurements"] = conn.execute("SELECT COUNT(*) FROM measurements").fetchone()[0]
        stats["instruments"] = conn.execute("SELECT COUNT(*) FROM instruments").fetchone()[0]

        return stats

    def vacuum(self) -> None:
        """Optimize database file size and performance."""
        conn = self._get_connection()
        conn.execute("VACUUM")

    def __repr__(self) -> str:
        stats = self.get_stats()
        return (
            f"MeasurementDatabase({self.db_path})\n"
            f"  Experiments: {stats['experiments']}\n"
            f"  Measurements: {stats['measurements']}\n"
            f"  Instruments: {stats['instruments']}"
        )


# Legacy compatibility alias
Database = MeasurementDatabase
