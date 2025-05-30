from __future__ import annotations

import sqlite3
import time
import numpy as np
from datetime import datetime
from .results import MeasurementResult
from .experiments import Experiment
import polars as pl
# import pickle # Not directly used in this version of the file, but often used with lzma/serialization
import lzma
from typing import Optional, Any, Union # Added Optional, Any, Union

class Database:
    """
    Manages a SQLite database for storing experiments and measurement results.
    
    This class supports storing:
      - Experiments, including their trial data (stored as a compressed Polars DataFrame),
        descriptions, and additional notes.
      - Experiment parameters.
      - Instruments used for measurements.
      - Measurement results (with values stored as binary-encoded numpy arrays).
    
    Custom adapters and converters are registered to handle numpy arrays and Polars DataFrames.
    
    Attributes:
        db_path (str): Base path (without extension) to the SQLite database.
        _conn (Optional[sqlite3.Connection]): The SQLite connection object (initialized on demand).
    """
    def __init__(self, db_path: str) -> None:
        """
        Initialize the Database instance, register custom adapters/converters, and create tables.
        
        Args:
            db_path (str): Base path for the SQLite database. The database file will be '{db_path}.db'.
        """
        self.db_path: str = db_path
        self._conn: Optional[sqlite3.Connection] = None
        sqlite3.register_adapter(np.ndarray, self.adapt_npdata)
        sqlite3.register_converter("NPDATA", self.convert_npdata)
        sqlite3.register_adapter(pl.DataFrame, self.encode_data)
        sqlite3.register_converter("PLDATA", self.decode_data)
        self._create_tables()

    @staticmethod
    def encode_data(df: pl.DataFrame) -> sqlite3.Binary:
        """
        Encode a Polars DataFrame to a compressed binary format.
        
        The DataFrame is serialized to the Apache Arrow IPC format, then compressed with lzma.
        
        Args:
            df (pl.DataFrame): The Polars DataFrame to encode.
            
        Returns:
            sqlite3.Binary: The compressed binary representation of the DataFrame.
        """
        # write_ipc with None as first arg writes to a BytesIO buffer
        ipc_buffer = df.write_ipc(None) # Removed future=True as it's default or deprecated depending on polars version
        if ipc_buffer is None: # Should not happen if write_ipc(None) works as expected
            raise ValueError("Polars write_ipc(None) returned None, expected bytes.")
        compressed_data = lzma.compress(ipc_buffer.getvalue())
        return sqlite3.Binary(compressed_data)

    @staticmethod
    def decode_data(blob: bytes) -> pl.DataFrame:
        """
        Decode binary data back into a Polars DataFrame.
        
        The binary data is decompressed using lzma and then read as an Apache Arrow IPC format.
        
        Args:
            blob (bytes): The binary data stored in the database.
            
        Returns:
            pl.DataFrame: The reconstructed Polars DataFrame.
        """
        decompressed_data = lzma.decompress(blob)
        df = pl.read_ipc(decompressed_data)
        return df

    @staticmethod
    def adapt_npdata(arr: np.ndarray) -> sqlite3.Binary:
        """
        Adapt a numpy array to a binary format with encoded dtype and shape.
        
        Args:
            arr (np.ndarray): The numpy array to adapt.
            
        Returns:
            sqlite3.Binary: The binary representation of the array.
            
        Raises:
            ValueError: If the provided object is not a numpy.ndarray.
        """
        if not isinstance(arr, np.ndarray):
            raise ValueError("Unsafe object passed to adapt_npdata; expected a numpy.ndarray.")
        data_bytes = arr.tobytes()
        dtype_str = str(arr.dtype)
        shape_str = ",".join(map(str, arr.shape))
        # Ensure all parts are bytes before concatenation
        return sqlite3.Binary(data_bytes + b";" + dtype_str.encode('utf-8') + b";" + shape_str.encode('utf-8'))

    @staticmethod
    def convert_npdata(text: bytes) -> np.ndarray:
        """
        Convert binary data back into a numpy array, reconstructing its dtype and shape.
        
        Args:
            text (bytes): The binary representation stored in the database.
            
        Returns:
            np.ndarray: The reconstructed numpy array.
        """
        data_bytes, dtype_bytes, shape_bytes = text.rsplit(b";", 2)
        dtype_str = dtype_bytes.decode('utf-8')
        shape_str = shape_bytes.decode('utf-8')
        shape_tuple: tuple[int, ...] = tuple(map(int, shape_str.split(","))) if shape_str else ()
        return np.frombuffer(data_bytes, dtype=np.dtype(dtype_str)).reshape(shape_tuple)

    def _create_tables(self) -> None:
        """
        Create the necessary tables in the SQLite database if they do not exist.
        Commits the transaction after table creation.
        """
        with self._get_connection() as conn:
            conn.execute("PRAGMA foreign_keys = ON;") # Ensure PRAGMA is executed
            conn.execute('''
                CREATE TABLE IF NOT EXISTS experiments (
                    experiment_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    codename TEXT UNIQUE NOT NULL,
                    data PLDATA,
                    name TEXT NOT NULL,
                    description TEXT,
                    notes TEXT
                );
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS experiment_parameters (
                    parameter_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    experiment_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    units TEXT,
                    notes TEXT,
                    FOREIGN KEY (experiment_id) REFERENCES experiments(experiment_id) ON DELETE CASCADE
                );
            ''') # Added ON DELETE CASCADE
            conn.execute('''
                CREATE TABLE IF NOT EXISTS instruments (
                    instrument_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE
                );
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS measurements (
                    measurement_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    codename TEXT UNIQUE NOT NULL,
                    instrument_id INTEGER NOT NULL,
                    timestamp TIMESTAMP NOT NULL,
                    value NPDATA NOT NULL,
                    units TEXT NOT NULL,
                    type TEXT,
                    FOREIGN KEY (instrument_id) REFERENCES instruments(instrument_id) ON DELETE CASCADE
                );
            ''') # Added ON DELETE CASCADE
            # Add indices for frequently queried columns
            conn.execute("CREATE INDEX IF NOT EXISTS idx_exp_codename ON experiments(codename);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_meas_codename ON measurements(codename);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_meas_timestamp ON measurements(timestamp DESC);")
            conn.commit()

    def _get_connection(self) -> sqlite3.Connection:
        """
        Retrieve the SQLite connection, creating it if necessary, and ensure foreign key support.
        
        Returns:
            sqlite3.Connection: The active database connection.
        """
        if self._conn is None:
            # PARSE_DECLTYPES allows custom converters to work based on declared column types
            self._conn = sqlite3.connect(f"{self.db_path}.db", detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
            self._conn.execute("PRAGMA foreign_keys = ON;")
        return self._conn

    def _get_or_create_instrument_id(self, conn: sqlite3.Connection, instrument_name: str) -> int:
        """
        Retrieve the instrument ID for a given instrument name. If it doesn't exist, create a new entry.
        
        Args:
            conn (sqlite3.Connection): The active database connection.
            instrument_name (str): The instrument's name.
            
        Returns:
            int: The instrument ID.
        """
        cursor = conn.execute('SELECT instrument_id FROM instruments WHERE name = ?', (instrument_name,))
        result = cursor.fetchone()
        if result:
            return int(result[0]) # Ensure int
        else:
            cursor.execute('INSERT INTO instruments (name) VALUES (?)', (instrument_name,))
            # conn.commit() # Commit should be handled by the calling function's transaction
            last_id = cursor.lastrowid
            if last_id is None:
                 raise sqlite3.Error("Failed to get lastrowid after instrument insert.")
            return int(last_id)

    def store_measurement(self, codename: str, measurement_result: MeasurementResult, force: bool = False) -> None:
        """
        Store a measurement result in the database.
        """
        with self._get_connection() as conn:
            instrument_id = self._get_or_create_instrument_id(conn, measurement_result.instrument)
            sql_op = "INSERT OR REPLACE INTO" if force else "INSERT INTO"
            
            try:
                conn.execute(f'''
                    {sql_op} measurements (codename, instrument_id, timestamp, value, units, type)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (
                    codename,
                    instrument_id,
                    datetime.fromtimestamp(measurement_result.timestamp),
                    measurement_result.values, # This will use adapt_npdata
                    measurement_result.units,
                    measurement_result.measurement_type
                ))
                conn.commit()
            except sqlite3.IntegrityError as e:
                if "UNIQUE constraint failed: measurements.codename" in str(e) and not force:
                    raise ValueError(f"Measurement codename '{codename}' already exists. Use force=True to overwrite.") from e
                raise # Re-raise other integrity errors

    def retrieve_measurement(self, codename: str) -> MeasurementResult:
        """
        Retrieve a measurement result from the database by its codename.
        """
        with self._get_connection() as conn:
            cursor = conn.execute('''
                SELECT i.name, m.timestamp, m.value, m.units, m.type
                FROM measurements m
                JOIN instruments i ON m.instrument_id = i.instrument_id
                WHERE m.codename = ?
            ''', (codename,))
            row = cursor.fetchone() # Use fetchone as codename is unique
            if not row:
                raise ValueError(f"No measurement found with codename: '{codename}'.")
            
            instrument_name, timestamp_obj, values_blob, units_str, type_str = row
            # values_blob is automatically converted by convert_npdata due to PARSE_DECLTYPES and column type NPDATA
            
            return MeasurementResult(
                values=values_blob, # Should be np.ndarray
                instrument=str(instrument_name),
                units=str(units_str),
                measurement_type=str(type_str) if type_str is not None else "",
                timestamp=timestamp_obj.timestamp() # Convert datetime object back to float
            )

    def store_experiment(self, codename: str, experiment: Experiment, force: bool = False) -> None:
        """
        Store an Experiment (including its trial data, parameters, and notes) in the database.
        """
        with self._get_connection() as conn:
            sql_op = "INSERT OR REPLACE INTO" if force else "INSERT INTO"
            try:
                cursor = conn.execute(f'''
                    {sql_op} experiments (codename, data, name, description, notes)
                    VALUES (?, ?, ?, ?, ?)
                ''', (codename, experiment.data, experiment.name, experiment.description, getattr(experiment, "notes", "")))
                
                experiment_id_to_use: Optional[int] = None
                if force: # If replacing, need to get existing or new experiment_id
                    id_cursor = conn.execute('SELECT experiment_id FROM experiments WHERE codename = ?', (codename,))
                    id_row = id_cursor.fetchone()
                    if id_row:
                        experiment_id_to_use = int(id_row[0])
                    # If it was a new insert via REPLACE, lastrowid should be set
                    elif cursor.lastrowid is not None:
                         experiment_id_to_use = int(cursor.lastrowid)
                elif cursor.lastrowid is not None: # New insert
                    experiment_id_to_use = int(cursor.lastrowid)

                if experiment_id_to_use is None:
                    raise sqlite3.Error(f"Could not determine experiment_id for codename '{codename}'.")

                # If forcing, delete old parameters before inserting new ones
                if force:
                    conn.execute('DELETE FROM experiment_parameters WHERE experiment_id = ?', (experiment_id_to_use,))

                for param_obj in experiment.parameters.values():
                    param_notes = getattr(param_obj, "notes", "")
                    conn.execute('''
                        INSERT INTO experiment_parameters (experiment_id, name, units, notes)
                        VALUES (?, ?, ?, ?)
                    ''', (experiment_id_to_use, param_obj.name, param_obj.units, param_notes))
                conn.commit()
            except sqlite3.IntegrityError as e:
                if "UNIQUE constraint failed: experiments.codename" in str(e) and not force:
                     raise ValueError(f"Experiment codename '{codename}' already exists. Use force=True to overwrite.") from e
                raise


    def retrieve_experiment(self, codename: str) -> Experiment:
        """
        Retrieve an Experiment (with its parameters and notes) from the database by its codename.
        """
        with self._get_connection() as conn:
            cursor = conn.execute('SELECT experiment_id, data, name, description, notes FROM experiments WHERE codename = ?', (codename,))
            exp_row = cursor.fetchone()
            if not exp_row:
                raise ValueError(f"No experiment found with codename: '{codename}'.")
            
            experiment_id, data_blob, name_str, description_str, notes_str = exp_row
            
            retrieved_experiment = Experiment(name_str, description_str)
            # data_blob is automatically converted by decode_data
            if isinstance(data_blob, pl.DataFrame):
                retrieved_experiment.data = data_blob
            elif data_blob is not None: # Should not happen if adapter works
                raise TypeError(f"Retrieved data for experiment '{codename}' is not a Polars DataFrame.")

            setattr(retrieved_experiment, "notes", notes_str if notes_str is not None else "")
            
            param_cursor = conn.execute('SELECT name, units, notes FROM experiment_parameters WHERE experiment_id = ?', (experiment_id,))
            for param_name, param_units, param_notes_db in param_cursor.fetchall():
                retrieved_experiment.add_parameter(str(param_name), str(param_units), str(param_notes_db if param_notes_db is not None else ""))
            return retrieved_experiment

    def close(self) -> None:
        """
        Close the database connection.
        """
        if self._conn:
            self._conn.close()
            self._conn = None
