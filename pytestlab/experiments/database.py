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
import lzma
import pickle
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import numpy as np
import polars as pl
from tqdm.auto import tqdm

from .experiments import Experiment
from .results import MeasurementResult

__all__ = ["Database", "MeasurementDatabase"]


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
    
    def __init__(self, db_path: Union[str, Path]) -> None:
        """
        Initialize database connection and create tables.
        
        Args:
            db_path: Database file path (without .db extension)
        """
        self.db_path = Path(str(db_path)).with_suffix(".db")
        self._conn_lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None
        
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
    def __enter__(self) -> "MeasurementDatabase":
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
    
    # Connection management
    def _get_connection(self) -> sqlite3.Connection:
        """Get thread-safe database connection."""
        with self._conn_lock:
            if self._conn is None:
                self._conn = sqlite3.connect(
                    self.db_path,
                    detect_types=sqlite3.PARSE_DECLTYPES,
                    check_same_thread=False
                )
                self._conn.execute("PRAGMA foreign_keys = ON")
                self._conn.execute("PRAGMA journal_mode = WAL")  # Better concurrency
            return self._conn
    
    def close(self) -> None:
        """Close database connection."""
        with self._conn_lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
    
    # Binary serialization
    @staticmethod
    def _adapt_numpy(arr: np.ndarray) -> sqlite3.Binary:
        """Serialize NumPy array to binary with metadata."""
        if not isinstance(arr, np.ndarray):
            raise TypeError("Expected numpy.ndarray")
        
        metadata = {
            "dtype": str(arr.dtype),
            "shape": arr.shape,
            "compressed": True
        }
        
        data_bytes = lzma.compress(arr.tobytes())
        metadata_bytes = pickle.dumps(metadata)
        
        # Format: [metadata_length:4][metadata][data]
        return sqlite3.Binary(
            len(metadata_bytes).to_bytes(4, "little") + 
            metadata_bytes + 
            data_bytes
        )
    
    @staticmethod
    def _convert_numpy(blob: bytes) -> np.ndarray:
        """Deserialize binary data back to NumPy array."""
        metadata_len = int.from_bytes(blob[:4], "little")
        metadata = pickle.loads(blob[4:4+metadata_len])
        data_bytes = blob[4+metadata_len:]
        
        if metadata.get("compressed", False):
            data_bytes = lzma.decompress(data_bytes)
        
        return np.frombuffer(data_bytes, dtype=metadata["dtype"]).reshape(metadata["shape"])
    
    @staticmethod
    def _adapt_polars(df: pl.DataFrame) -> sqlite3.Binary:
        """Serialize Polars DataFrame using Arrow IPC + compression."""
        ipc_data = df.write_ipc(None, compat_level=0).getvalue()
        compressed = lzma.compress(ipc_data)
        return sqlite3.Binary(compressed)
    
    @staticmethod
    def _convert_polars(blob: bytes) -> pl.DataFrame:
        """Deserialize compressed Arrow IPC back to Polars DataFrame."""
        decompressed = lzma.decompress(blob)
        return pl.read_ipc(decompressed)
    
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
                
                -- FTS triggers for auto-sync
                CREATE TRIGGER IF NOT EXISTS experiments_fts_insert AFTER INSERT ON experiments
                BEGIN
                    INSERT INTO experiments_fts(codename, name, description, notes)
                    VALUES (new.codename, new.name, new.description, new.notes);
                END;
                
                CREATE TRIGGER IF NOT EXISTS experiments_fts_delete AFTER DELETE ON experiments
                BEGIN
                    DELETE FROM experiments_fts WHERE codename = old.codename;
                END;
                
                CREATE TRIGGER IF NOT EXISTS experiments_fts_update AFTER UPDATE ON experiments
                BEGIN
                    UPDATE experiments_fts SET 
                        name = new.name,
                        description = new.description,
                        notes = new.notes
                    WHERE codename = new.codename;
                END;
            """)
            
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
                
                -- FTS triggers for measurements
                CREATE TRIGGER IF NOT EXISTS measurements_fts_insert AFTER INSERT ON measurements
                BEGIN
                    INSERT INTO measurements_fts(codename, measurement_type, notes)
                    VALUES (new.codename, new.measurement_type, new.notes);
                END;
                
                CREATE TRIGGER IF NOT EXISTS measurements_fts_delete AFTER DELETE ON measurements
                BEGIN
                    DELETE FROM measurements_fts WHERE codename = old.codename;
                END;
                
                CREATE TRIGGER IF NOT EXISTS measurements_fts_update AFTER UPDATE ON measurements
                BEGIN
                    UPDATE measurements_fts SET 
                        measurement_type = new.measurement_type,
                        notes = new.notes
                    WHERE codename = new.codename;
                END;
            """)
            
            # Indices for performance
            conn.execute("CREATE INDEX IF NOT EXISTS idx_exp_created ON experiments(created_at);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_meas_timestamp ON measurements(timestamp);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_meas_type ON measurements(measurement_type);")
    
    # Instrument management
    def _get_or_create_instrument_id(self, conn: sqlite3.Connection, instrument_name: str) -> int:
        """Get or create instrument ID."""
        cursor = conn.execute("SELECT instrument_id FROM instruments WHERE name = ?", (instrument_name,))
        row = cursor.fetchone()
        if row:
            return row[0]
        
        cursor = conn.execute("INSERT INTO instruments (name) VALUES (?)", (instrument_name,))
        return cursor.lastrowid
    
    # Experiment operations
    def store_experiment(
        self, 
        codename: Optional[str], 
        experiment: Experiment, 
        *, 
        overwrite: bool = True,
        notes: str = ""
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
            # Check for existing entry
            cursor = conn.execute("SELECT 1 FROM experiments WHERE codename = ?", (codename,))
            if cursor.fetchone() and not overwrite:
                raise ValueError(f"Experiment '{codename}' already exists")
            
            # Store experiment
            conn.execute("""
                INSERT OR REPLACE INTO experiments 
                (codename, name, description, notes, data, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                codename,
                experiment.name,
                experiment.description,
                notes,
                experiment.data,
                dt.datetime.now()
            ))
            
            # Store parameters
            conn.execute("DELETE FROM experiment_parameters WHERE codename = ?", (codename,))
            for param in experiment.parameters.values():
                param_notes = getattr(param, "notes", "")
                conn.execute("""
                    INSERT INTO experiment_parameters (codename, param_name, param_unit, param_notes)
                    VALUES (?, ?, ?, ?)
                """, (codename, param.name, param.units, param_notes))
        
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
        cursor = conn.execute("""
            SELECT name, description, notes, data 
            FROM experiments 
            WHERE codename = ?
        """, (codename,))
        
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"Experiment '{codename}' not found")
        
        name, description, notes, data = row
        
        # Reconstruct experiment
        experiment = Experiment(name, description)
        experiment.data = data
        experiment.notes = notes
        
        # Load parameters
        cursor = conn.execute("""
            SELECT param_name, param_unit, param_notes 
            FROM experiment_parameters 
            WHERE codename = ?
        """, (codename,))
        
        for param_name, param_unit, param_notes in cursor.fetchall():
            experiment.add_parameter(param_name, param_unit, param_notes)
        
        return experiment
    
    def list_experiments(self, limit: Optional[int] = None) -> List[str]:
        """List all experiment codenames, newest first."""
        conn = self._get_connection()
        query = "SELECT codename FROM experiments ORDER BY created_at DESC"
        if limit:
            query += f" LIMIT {limit}"
        
        cursor = conn.execute(query)
        return [row[0] for row in cursor.fetchall()]
    
    def search_experiments(self, query: str, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Full-text search across experiments.
        
        Args:
            query: Search terms
            limit: Maximum results to return
        
        Returns:
            List of dicts with experiment metadata
        """
        conn = self._get_connection()
        cursor = conn.execute("""
            SELECT e.codename, e.name, e.description, e.notes, e.created_at
            FROM experiments_fts f
            JOIN experiments e ON f.codename = e.codename
            WHERE experiments_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        """, (query, limit))
        
        return [
            {
                "codename": row[0],
                "name": row[1], 
                "description": row[2],
                "notes": row[3],
                "created_at": row[4]
            }
            for row in cursor.fetchall()
        ]
    
    # Measurement operations
    def store_measurement(
        self,
        codename: Optional[str],
        measurement: MeasurementResult,
        *,
        overwrite: bool = True,
        notes: str = ""
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
            # Check for existing entry
            cursor = conn.execute("SELECT 1 FROM measurements WHERE codename = ?", (codename,))
            if cursor.fetchone() and not overwrite:
                raise ValueError(f"Measurement '{codename}' already exists")
            
            # Get instrument ID
            instrument_id = self._get_or_create_instrument_id(conn, measurement.instrument)
            
            # Store measurement
            conn.execute("""
                INSERT OR REPLACE INTO measurements 
                (codename, instrument_id, timestamp, value_data, units, measurement_type, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                codename,
                instrument_id,
                dt.datetime.fromtimestamp(measurement.timestamp),
                measurement.values,
                measurement.units,
                measurement.measurement_type,
                notes
            ))
        
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
        cursor = conn.execute("""
            SELECT i.name, m.timestamp, m.value_data, m.units, m.measurement_type
            FROM measurements m
            JOIN instruments i ON m.instrument_id = i.instrument_id
            WHERE m.codename = ?
        """, (codename,))
        
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"Measurement '{codename}' not found")
        
        instrument, timestamp, value_data, units, measurement_type = row
        
        return MeasurementResult(
            values=value_data,
            instrument=instrument,
            units=units,
            measurement_type=measurement_type,
            timestamp=timestamp.timestamp() if hasattr(timestamp, 'timestamp') else time.time()
        )
    
    def list_measurements(
        self, 
        instrument: Optional[str] = None, 
        limit: Optional[int] = None
    ) -> List[str]:
        """
        List measurement codenames, optionally filtered by instrument.
        
        Args:
            instrument: Filter by instrument name
            limit: Maximum results to return
        
        Returns:
            List of measurement codenames
        """
        conn = self._get_connection()
        
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
    
    def search_measurements(self, query: str, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Full-text search across measurements.
        
        Args:
            query: Search terms
            limit: Maximum results to return
        
        Returns:
            List of dicts with measurement metadata
        """
        conn = self._get_connection()
        cursor = conn.execute("""
            SELECT m.codename, i.name, m.measurement_type, m.units, m.timestamp, m.notes
            FROM measurements_fts f
            JOIN measurements m ON f.codename = m.codename
            JOIN instruments i ON m.instrument_id = i.instrument_id
            WHERE measurements_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        """, (query, limit))
        
        return [
            {
                "codename": row[0],
                "instrument": row[1],
                "measurement_type": row[2],
                "units": row[3],
                "timestamp": row[4],
                "notes": row[5]
            }
            for row in cursor.fetchall()
        ]
    
    # Bulk operations
    def bulk_store_measurements(
        self,
        measurements: List[tuple[Optional[str], MeasurementResult]],
        show_progress: bool = True
    ) -> List[str]:
        """
        Store multiple measurements efficiently.
        
        Args:
            measurements: List of (codename, MeasurementResult) tuples
            show_progress: Whether to show progress bar
        
        Returns:
            List of final codenames used
        """
        codenames = []
        iterator = tqdm(measurements, desc="Storing measurements", disable=not show_progress)
        
        for codename, measurement in iterator:
            final_codename = self.store_measurement(codename, measurement)
            codenames.append(final_codename)
        
        return codenames
    
    # Database utilities
    def vacuum(self) -> None:
        """Optimize database file size and performance."""
        conn = self._get_connection()
        conn.execute("VACUUM")
    
    def get_stats(self) -> Dict[str, int]:
        """Get database statistics."""
        conn = self._get_connection()
        
        stats = {}
        stats["experiments"] = conn.execute("SELECT COUNT(*) FROM experiments").fetchone()[0]
        stats["measurements"] = conn.execute("SELECT COUNT(*) FROM measurements").fetchone()[0]
        stats["instruments"] = conn.execute("SELECT COUNT(*) FROM instruments").fetchone()[0]
        
        return stats
    
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
