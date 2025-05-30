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
from typing import Any, Dict, List as TypingList, Optional, Union # Renamed List to TypingList

import numpy as np
import polars as pl
from tqdm.auto import tqdm

from .experiments import Experiment
from .results import MeasurementResult
from .._log import get_logger # For self._logger
from uncertainties.core import Variable as UFloat # For type checking in encode_data

__all__ = ["Database", "MeasurementDatabase"]


def _generate_codename(prefix: str = "ITEM") -> str:
    """Generate a unique codename using timestamp and random hash."""
    timestamp = str(int(time.time() * 1000))  # milliseconds
    random_hash = hashlib.md5(str(time.time()).encode()).hexdigest()[:8]
    return f"{prefix}_{timestamp}_{random_hash}"


class MeasurementDatabase(contextlib.AbstractContextManager["MeasurementDatabase"]): # Added type hint for AbstractContextManager
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
        self.db_path: Path = Path(str(db_path)).with_suffix(".db")
        self._conn_lock: threading.Lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None
        self._logger = get_logger(self.__class__.__name__) # Initialize logger
        
        sqlite3.register_adapter(np.ndarray, self._adapt_numpy)
        sqlite3.register_converter("NPBLOB", self._convert_numpy)
        sqlite3.register_adapter(pl.DataFrame, self._adapt_polars)
        sqlite3.register_converter("PLBLOB", self._convert_polars)
        sqlite3.register_adapter(dt.datetime, self._adapt_datetime)
        sqlite3.register_converter("DATETIME", self._convert_datetime)
        
        self._ensure_tables()
    
    def __enter__(self) -> MeasurementDatabase:
        return self
    
    def __exit__(self, exc_type: Optional[Type[BaseException]], exc_val: Optional[BaseException], exc_tb: Optional[Any]) -> None: # Added type hints for __exit__
        self.close()
    
    def _get_connection(self) -> sqlite3.Connection:
        """Get thread-safe database connection."""
        with self._conn_lock:
            if self._conn is None:
                self._conn = sqlite3.connect(
                    self.db_path,
                    detect_types=sqlite3.PARSE_DECLTYPES,
                    check_same_thread=False # Allow connection to be used by different threads (with external locking)
                )
                self._conn.execute("PRAGMA foreign_keys = ON")
                self._conn.execute("PRAGMA journal_mode = WAL")
            return self._conn
    
    def close(self) -> None:
        """Close database connection."""
        with self._conn_lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
    
    @staticmethod
    def _adapt_numpy(arr: np.ndarray) -> sqlite3.Binary:
        """Serialize NumPy array to binary with metadata."""
        if not isinstance(arr, np.ndarray):
            raise TypeError("Expected numpy.ndarray")
        
        metadata: Dict[str, Any] = {
            "dtype": str(arr.dtype),
            "shape": arr.shape,
            "compressed": True
        }
        
        data_bytes = lzma.compress(arr.tobytes())
        metadata_bytes = pickle.dumps(metadata)
        
        return sqlite3.Binary(
            len(metadata_bytes).to_bytes(4, "little") + 
            metadata_bytes + 
            data_bytes
        )
    
    @staticmethod
    def _convert_numpy(blob: bytes) -> np.ndarray:
        """Deserialize binary data back to NumPy array."""
        metadata_len = int.from_bytes(blob[:4], "little")
        metadata: Dict[str, Any] = pickle.loads(blob[4:4+metadata_len])
        data_bytes_compressed = blob[4+metadata_len:] # Renamed for clarity
        
        actual_data_bytes: bytes
        if metadata.get("compressed", False):
            actual_data_bytes = lzma.decompress(data_bytes_compressed)
        else:
            actual_data_bytes = data_bytes_compressed # Should not happen with current _adapt_numpy
        
        return np.frombuffer(actual_data_bytes, dtype=np.dtype(metadata["dtype"])).reshape(metadata["shape"]) # Use np.dtype()
    
    @staticmethod
    def _adapt_polars(df: pl.DataFrame) -> sqlite3.Binary:
        """Serialize Polars DataFrame using Arrow IPC + compression."""
        # write_ipc with None as first arg writes to a BytesIO buffer
        ipc_buffer = df.write_ipc(None, compat_level=0) 
        if ipc_buffer is None: # Should not happen if write_ipc(None) works as expected
            raise ValueError("Polars write_ipc(None) returned None, expected bytes.")
        ipc_data = ipc_buffer.getvalue()
        compressed = lzma.compress(ipc_data)
        return sqlite3.Binary(compressed)
    
    @staticmethod
    def _convert_polars(blob: bytes) -> pl.DataFrame:
        """Deserialize compressed Arrow IPC back to Polars DataFrame."""
        decompressed = lzma.decompress(blob)
        return pl.read_ipc(decompressed)
    
    @staticmethod
    def _adapt_datetime(dt_obj: dt.datetime) -> str:
        """Convert datetime to ISO format string."""
        return dt_obj.isoformat()
    
    @staticmethod
    def _convert_datetime(iso_string: bytes) -> dt.datetime:
        """Convert ISO format string back to datetime."""
        return dt.datetime.fromisoformat(iso_string.decode('utf-8')) # Ensure decoding
    
    def _ensure_tables(self) -> None:
        """Create database tables if they don't exist."""
        conn = self._get_connection()
        with conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS experiments (
                    codename TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    notes TEXT,
                    data PLBLOB,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    metadata TEXT
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS experiments_fts USING fts5(
                    codename, name, description, notes,
                    content='experiments', tokenize='porter unicode61'
                );
                CREATE TRIGGER IF NOT EXISTS experiments_fts_insert AFTER INSERT ON experiments
                BEGIN
                    INSERT INTO experiments_fts(rowid, codename, name, description, notes)
                    VALUES (new.rowid, new.codename, new.name, new.description, new.notes);
                END;
                CREATE TRIGGER IF NOT EXISTS experiments_fts_delete AFTER DELETE ON experiments
                BEGIN
                    DELETE FROM experiments_fts WHERE rowid = old.rowid;
                END;
                CREATE TRIGGER IF NOT EXISTS experiments_fts_update AFTER UPDATE ON experiments
                BEGIN
                    UPDATE experiments_fts SET 
                        name = new.name,
                        description = new.description,
                        notes = new.notes
                    WHERE rowid = new.rowid;
                END;
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS experiment_parameters (
                    codename TEXT,
                    param_name TEXT,
                    param_unit TEXT,
                    param_notes TEXT,
                    PRIMARY KEY (codename, param_name),
                    FOREIGN KEY (codename) REFERENCES experiments(codename) ON DELETE CASCADE
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS instruments (
                    instrument_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL
                );
            """)
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS measurements (
                    codename TEXT PRIMARY KEY,
                    instrument_id INTEGER,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    value_data NPBLOB NOT NULL,
                    units TEXT,
                    measurement_type TEXT,
                    notes TEXT,
                    metadata TEXT,
                    FOREIGN KEY (instrument_id) REFERENCES instruments(instrument_id)
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS measurements_fts USING fts5(
                    codename, measurement_type, notes,
                    content='measurements', tokenize='porter unicode61'
                );
                CREATE TRIGGER IF NOT EXISTS measurements_fts_insert AFTER INSERT ON measurements
                BEGIN
                    INSERT INTO measurements_fts(rowid, codename, measurement_type, notes)
                    VALUES (new.rowid, new.codename, new.measurement_type, new.notes);
                END;
                CREATE TRIGGER IF NOT EXISTS measurements_fts_delete AFTER DELETE ON measurements
                BEGIN
                    DELETE FROM measurements_fts WHERE rowid = old.rowid;
                END;
                CREATE TRIGGER IF NOT EXISTS measurements_fts_update AFTER UPDATE ON measurements
                BEGIN
                    UPDATE measurements_fts SET 
                        measurement_type = new.measurement_type,
                        notes = new.notes
                    WHERE rowid = new.rowid;
                END;
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_exp_created ON experiments(created_at DESC);") # Added DESC
            conn.execute("CREATE INDEX IF NOT EXISTS idx_meas_timestamp ON measurements(timestamp DESC);") # Added DESC
            conn.execute("CREATE INDEX IF NOT EXISTS idx_meas_type ON measurements(measurement_type);")
    
    def _get_or_create_instrument_id(self, conn: sqlite3.Connection, instrument_name: str) -> int:
        """Get or create instrument ID."""
        cursor = conn.execute("SELECT instrument_id FROM instruments WHERE name = ?", (instrument_name,))
        row = cursor.fetchone()
        if row:
            return int(row[0]) # Ensure int
        
        cursor = conn.execute("INSERT INTO instruments (name) VALUES (?)", (instrument_name,))
        last_id = cursor.lastrowid
        if last_id is None: # Should not happen with AUTOINCREMENT if insert was successful
            raise sqlite3.Error("Failed to get lastrowid after instrument insert.")
        return int(last_id)
    
    def store_experiment(
        self, 
        codename: Optional[str], 
        experiment: Experiment, 
        *, 
        overwrite: bool = False, # Changed default to False for safety
        notes: Optional[str] = None # Allow notes to be None
    ) -> str:
        """
        Store an experiment in the database.
        """
        final_codename = codename if codename is not None else _generate_codename("EXP")
        
        conn = self._get_connection()
        with conn:
            cursor = conn.execute("SELECT 1 FROM experiments WHERE codename = ?", (final_codename,))
            if cursor.fetchone() and not overwrite:
                raise ValueError(f"Experiment '{final_codename}' already exists and overwrite is False.")
            
            conn.execute("""
                INSERT OR REPLACE INTO experiments 
                (codename, name, description, notes, data, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                final_codename,
                experiment.name,
                experiment.description,
                notes if notes is not None else experiment.description,
                self.encode_data(experiment.data) if isinstance(experiment.data, pl.DataFrame) else experiment.data,
                dt.datetime.now()
            ))
            
            conn.execute("DELETE FROM experiment_parameters WHERE codename = ?", (final_codename,))
            for param_obj in experiment.parameters.values(): # Iterate over ExperimentParameter objects
                conn.execute("""
                    INSERT INTO experiment_parameters (codename, param_name, param_unit, param_notes)
                    VALUES (?, ?, ?, ?)
                """, (final_codename, param_obj.name, param_obj.units, param_obj.notes))
        
        return final_codename
    
    def retrieve_experiment(self, codename: str) -> Experiment:
        """
        Retrieve an experiment by codename.
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
        
        name, description, db_notes, data_blob = row # db_notes is the specific notes for this storage instance
        
        retrieved_experiment = Experiment(name, description)
        if isinstance(data_blob, pl.DataFrame): # data_blob is already converted by sqlite3 adapter
            retrieved_experiment.data = data_blob
        elif data_blob is not None: # Should not happen if adapter works
             raise TypeError(f"Retrieved data for experiment '{codename}' is not a Polars DataFrame.")
        # Note: The 'notes' attribute on the Experiment object itself is not directly stored/retrieved here.
        # The 'notes' field in the DB is specific to the storage instance.
        # If Experiment object should have its own notes, that's separate.

        param_cursor = conn.execute("""
            SELECT param_name, param_unit, param_notes 
            FROM experiment_parameters 
            WHERE codename = ?
        """, (codename,))
        
        for param_name, param_unit, param_notes_db in param_cursor.fetchall():
            retrieved_experiment.add_parameter(param_name, param_unit, param_notes_db)
        
        return retrieved_experiment
    
    def list_experiments(self, limit: Optional[int] = None) -> TypingList[str]:
        """List all experiment codenames, newest first."""
        conn = self._get_connection()
        query = "SELECT codename FROM experiments ORDER BY created_at DESC"
        if limit is not None: # Check for None explicitly
            if not isinstance(limit, int) or limit < 1:
                raise ValueError("Limit must be a positive integer.")
            query += f" LIMIT {limit}"
        
        cursor = conn.execute(query)
        return [str(row[0]) for row in cursor.fetchall()] # Ensure string
    
    def search_experiments(self, query: str, limit: int = 50) -> TypingList[Dict[str, Any]]:
        """
        Full-text search across experiments.
        """
        conn = self._get_connection()
        cursor = conn.execute("""
            SELECT e.codename, e.name, e.description, e.notes, e.created_at
            FROM experiments_fts f
            JOIN experiments e ON f.codename = e.codename
            WHERE experiments_fts MATCH ?
            ORDER BY rank DESC -- Typically more relevant results have higher rank
            LIMIT ? 
        """, (query, limit))
        
        return [
            {
                "codename": row[0], "name": row[1], "description": row[2],
                "notes": row[3], "created_at": row[4] # Already datetime object
            }
            for row in cursor.fetchall()
        ]
    
    def store_measurement(
        self,
        codename: Optional[str],
        measurement: MeasurementResult,
        *,
        overwrite: bool = False, # Changed default to False
        notes: Optional[str] = None # Allow notes to be None
    ) -> str:
        """
        Store a measurement result.
        """
        final_codename = codename if codename is not None else _generate_codename("MEAS")
        
        conn = self._get_connection()
        with conn:
            cursor = conn.execute("SELECT 1 FROM measurements WHERE codename = ?", (final_codename,))
            if cursor.fetchone() and not overwrite:
                raise ValueError(f"Measurement '{final_codename}' already exists and overwrite is False.")
            
            instrument_id = self._get_or_create_instrument_id(conn, measurement.instrument)
            
            conn.execute("""
                INSERT OR REPLACE INTO measurements 
                (codename, instrument_id, timestamp, value_data, units, measurement_type, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                final_codename, instrument_id,
                dt.datetime.fromtimestamp(measurement.timestamp),
                self._prepare_measurement_values_for_db(measurement.values),
                measurement.units,
                measurement.measurement_type, notes
            ))
        
        return final_codename

    def _prepare_measurement_values_for_db(self, values: Any) -> Any:
        """Prepares measurement values for database storage, handling DataFrames and UFloats."""
        if isinstance(values, pl.DataFrame):
            return self.encode_data(values)
        elif isinstance(values, UFloat): # Handle single UFloat
            return np.array([values.nominal_value, values.std_dev])
        # Could add handling for np.ndarray of UFloats here if NPBLOB should store them split.
        # For now, _adapt_numpy will pickle them if they are in an object array.
        return values

    def encode_data(self, df: pl.DataFrame) -> pl.DataFrame:
        """
        Transforms Polars DataFrame columns containing UFloat objects.
        A UFloat column is replaced by a column of its nominal values (same name)
        and a new column for standard deviations (suffixed with '_σ').
        """
        new_df = df.clone() # Work on a copy
        columns_to_add = []
        columns_to_drop = []

        for col_name in new_df.columns:
            # Ensure the column is of object type and not empty before checking element type
            if new_df[col_name].dtype == pl.Object and new_df[col_name].drop_nulls().len() > 0:
                try:
                    # Attempt to check the first non-null element's type
                    first_val = new_df[col_name].drop_nulls().item(0) # Use item(0) for direct access
                    if isinstance(first_val, UFloat):
                        self._logger.debug(f"Serializing UFloat column '{col_name}' into nominal and sigma columns.")
                        
                        # Use map_elements for potentially better performance and type handling
                        nominal_values = new_df[col_name].map_elements(
                            lambda x: x.nominal_value if isinstance(x, UFloat) else x,
                            return_dtype=pl.Float64
                        )
                        sigma_values = new_df[col_name].map_elements(
                            lambda x: x.std_dev if isinstance(x, UFloat) else None,
                            return_dtype=pl.Float64
                        )

                        # Replace original column with nominal values
                        columns_to_add.append(nominal_values.alias(col_name))
                        # Add new sigma column
                        columns_to_add.append(sigma_values.alias(f"{col_name}_σ"))
                        
                        if col_name not in columns_to_drop: # Ensure not to add duplicates to drop list
                             columns_to_drop.append(col_name)
                except Exception as e:
                    self._logger.error(f"Error processing column '{col_name}' for UFloat conversion: {e}")
                    # Decide if to raise, or continue, or just log. For now, continue.
        
        if columns_to_drop:
            # Select columns that are not being replaced, then add the new/modified ones.
            # Need to be careful if a column in columns_to_add has the same name as one in columns_to_drop
            # The current logic for columns_to_add reuses col_name for nominals.
            
            # Create a list of columns to select, excluding those to be dropped
            final_column_selection = [col for col in new_df.columns if col not in columns_to_drop]
            
            # Add the new columns (nominal and sigma)
            # If a nominal column (reusing original name) is added, it effectively replaces the dropped one.
            new_df = new_df.select(final_column_selection).with_columns(columns_to_add)
            
        return new_df

    def retrieve_measurement(self, codename: str) -> MeasurementResult:
        """
        Retrieve a measurement by codename.
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
        
        instrument_name, timestamp_dt, value_data_blob, units_str, meas_type_str = row
        
        # value_data_blob is already converted to np.ndarray by the adapter
        if not isinstance(value_data_blob, np.ndarray):
             raise TypeError(f"Retrieved value_data for measurement '{codename}' is not a NumPy array.")

        return MeasurementResult(
            values=value_data_blob,
            instrument=str(instrument_name), # Ensure string
            units=str(units_str) if units_str is not None else "",
            measurement_type=str(meas_type_str) if meas_type_str is not None else "",
            timestamp=timestamp_dt.timestamp() # Convert datetime back to float timestamp
        )
    
    def list_measurements(
        self, 
        instrument: Optional[str] = None, 
        limit: Optional[int] = None
    ) -> TypingList[str]:
        """
        List measurement codenames, optionally filtered by instrument.
        """
        conn = self._get_connection()
        params: tuple[Any, ...] = ()
        
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
            # params remains empty tuple
        
        if limit is not None:
            if not isinstance(limit, int) or limit < 1:
                raise ValueError("Limit must be a positive integer.")
            query += f" LIMIT ?" # Use placeholder for limit
            params += (limit,)
        
        cursor = conn.execute(query, params)
        return [str(row[0]) for row in cursor.fetchall()]
    
    def search_measurements(self, query: str, limit: int = 50) -> TypingList[Dict[str, Any]]:
        """
        Full-text search across measurements.
        """
        conn = self._get_connection()
        cursor = conn.execute("""
            SELECT m.codename, i.name, m.measurement_type, m.units, m.timestamp, m.notes
            FROM measurements_fts f
            JOIN measurements m ON f.codename = m.codename
            JOIN instruments i ON m.instrument_id = i.instrument_id
            WHERE measurements_fts MATCH ?
            ORDER BY rank DESC
            LIMIT ? 
        """, (query, limit))
        
        return [
            {
                "codename": row[0], "instrument": row[1], "measurement_type": row[2],
                "units": row[3], "timestamp": row[4], "notes": row[5]
            }
            for row in cursor.fetchall()
        ]
    
    def bulk_store_measurements(
        self,
        measurements: TypingList[tuple[Optional[str], MeasurementResult]],
        show_progress: bool = True
    ) -> TypingList[str]:
        """
        Store multiple measurements efficiently.
        """
        codenames: TypingList[str] = []
        # Ensure measurements is iterable for tqdm
        iterator = tqdm(measurements, desc="Storing measurements", disable=not show_progress, unit="measurement")
        
        for codename_in, measurement_obj in iterator:
            final_codename = self.store_measurement(codename_in, measurement_obj) # Default overwrite=False
            codenames.append(final_codename)
        
        return codenames
    
    def vacuum(self) -> None:
        """Optimize database file size and performance."""
        conn = self._get_connection()
        with conn: # Ensure VACUUM is in a transaction
            conn.execute("VACUUM")
        self._log("Database VACUUM completed.", level="info")
    
    def get_stats(self) -> Dict[str, int]:
        """Get database statistics."""
        conn = self._get_connection()
        stats: Dict[str, int] = {}
        
        stats["experiments"] = conn.execute("SELECT COUNT(*) FROM experiments").fetchone()[0] # type: ignore
        stats["measurements"] = conn.execute("SELECT COUNT(*) FROM measurements").fetchone()[0] # type: ignore
        stats["instruments"] = conn.execute("SELECT COUNT(*) FROM instruments").fetchone()[0] # type: ignore
        
        return stats
    
    def __repr__(self) -> str:
        stats = self.get_stats()
        return (
            f"MeasurementDatabase(db_path='{self.db_path}')\n"
            f"  Experiments: {stats.get('experiments', 0)}\n"
            f"  Measurements: {stats.get('measurements', 0)}\n"
            f"  Instruments: {stats.get('instruments', 0)}"
        )

Database = MeasurementDatabase
