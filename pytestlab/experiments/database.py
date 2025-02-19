import sqlite3
import time
import numpy as np
from datetime import datetime
from .results import MeasurementResult
from .experiments import Experiment
import polars as pl
import pickle
import lzma

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
        _conn (sqlite3.Connection): The SQLite connection object (initialized on demand).
    """
    def __init__(self, db_path):
        """
        Initialize the Database instance, register custom adapters/converters, and create tables.
        
        Args:
            db_path (str): Base path for the SQLite database. The database file will be '{db_path}.db'.
        """
        self.db_path = db_path
        self._conn = None
        sqlite3.register_adapter(np.ndarray, self.adapt_npdata)
        sqlite3.register_converter("NPDATA", self.convert_npdata)
        sqlite3.register_adapter(pl.DataFrame, self.encode_data)
        sqlite3.register_converter("PLDATA", self.decode_data)
        self._create_tables()

    @staticmethod
    def encode_data(df):
        """
        Encode a Polars DataFrame to a compressed binary format.
        
        The DataFrame is serialized to the Apache Arrow IPC format, then compressed with lzma.
        
        Args:
            df (pl.DataFrame): The Polars DataFrame to encode.
            
        Returns:
            sqlite3.Binary: The compressed binary representation of the DataFrame.
        """
        data = df.write_ipc(None, future=True)
        compressed_data = lzma.compress(data.getvalue())
        return sqlite3.Binary(compressed_data)

    @staticmethod
    def decode_data(blob):
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
    def adapt_npdata(arr):
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
        data = arr.tobytes()
        dtype = str(arr.dtype)
        shape = ",".join(map(str, arr.shape))
        return sqlite3.Binary(data + b";" + dtype.encode() + b";" + shape.encode())

    @staticmethod
    def convert_npdata(text):
        """
        Convert binary data back into a numpy array, reconstructing its dtype and shape.
        
        Args:
            text (bytes): The binary representation stored in the database.
            
        Returns:
            np.ndarray: The reconstructed numpy array.
        """
        data, dtype_str, shape_str = text.rsplit(b";", 2)
        dtype = dtype_str.decode()
        shape = tuple(map(int, shape_str.decode().split(","))) if shape_str.decode() != "" else ()
        return np.frombuffer(data, dtype=dtype).reshape(shape)

    def _create_tables(self):
        """
        Create the necessary tables in the SQLite database if they do not exist.
        
        Tables:
          - experiments: Stores experiment metadata, trial data, descriptions, and notes.
          - experiment_parameters: Stores parameters associated with each experiment.
          - instruments: Stores instrument names.
          - measurements: Stores measurement results (with binary-encoded numpy arrays).
          
        Commits the transaction after table creation.
        """
        with self._get_connection() as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute('''
                CREATE TABLE IF NOT EXISTS experiments (
                    experiment_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    codename TEXT UNIQUE,
                    data PLDATA,
                    name TEXT NOT NULL,
                    description TEXT,
                    notes TEXT
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS experiment_parameters (
                    parameter_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    experiment_id INTEGER,
                    name TEXT,
                    units TEXT,
                    notes TEXT,
                    FOREIGN KEY (experiment_id) REFERENCES experiments(experiment_id)
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS instruments (
                    instrument_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS measurements (
                    measurement_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    codename TEXT UNIQUE,
                    instrument_id INTEGER NOT NULL,
                    timestamp TIMESTAMP NOT NULL,
                    value NPDATA NOT NULL,
                    units TEXT NOT NULL,
                    type TEXT,
                    FOREIGN KEY (instrument_id) REFERENCES instruments(instrument_id)
                )
            ''')
            conn.commit()

    def _get_connection(self):
        """
        Retrieve the SQLite connection, creating it if necessary, and ensure foreign key support.
        
        Returns:
            sqlite3.Connection: The active database connection.
        """
        if self._conn is None:
            self._conn = sqlite3.connect(f"{self.db_path}.db", detect_types=sqlite3.PARSE_DECLTYPES)
            self._conn.execute("PRAGMA foreign_keys = ON")
        return self._conn

    def _get_or_create_instrument_id(self, conn, instrument_name):
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
            return result[0]
        else:
            cursor.execute('INSERT INTO instruments (name) VALUES (?)', (instrument_name,))
            conn.commit()
            return cursor.lastrowid

    def store_measurement(self, codename, measurement_result: MeasurementResult, force=False):
        """
        Store a measurement result in the database.
        
        The measurement is stored along with its instrument, timestamp, value (as binary data),
        units, and type.
        
        Args:
            codename (str): A unique identifier for the measurement.
            measurement_result (MeasurementResult): The measurement result to store.
            force (bool): If True, use INSERT OR REPLACE to update an existing record with the same codename.
            
        Raises:
            sqlite3.IntegrityError: If a measurement with the same codename exists and force is False.
        """
        with self._get_connection() as conn:
            try:
                instrument_id = self._get_or_create_instrument_id(conn, measurement_result.instrument)
                if force:
                    sql_statement = '''
                        INSERT OR REPLACE INTO measurements (codename, instrument_id, timestamp, value, units, type)
                        VALUES (?, ?, ?, ?, ?, ?)
                    '''
                else:
                    sql_statement = '''
                        INSERT INTO measurements (codename, instrument_id, timestamp, value, units, type)
                        VALUES (?, ?, ?, ?, ?, ?)
                    '''
                conn.execute(sql_statement, (
                    codename,
                    instrument_id,
                    datetime.fromtimestamp(measurement_result.timestamp),
                    measurement_result.values,
                    measurement_result.units,
                    measurement_result.measurement_type
                ))
                conn.commit()
            except sqlite3.IntegrityError as e:
                raise sqlite3.IntegrityError(f"Measurement codename '{codename}' is already in use.") from e

    def retrieve_measurement(self, codename):
        """
        Retrieve a measurement result from the database by its codename.
        
        Args:
            codename (str): The unique identifier for the measurement.
            
        Returns:
            MeasurementResult: The retrieved measurement result.
            
        Raises:
            ValueError: If no measurement is found with the given codename.
        """
        with self._get_connection() as conn:
            cursor = conn.execute('''
                SELECT i.name, m.type, m.value, m.units
                FROM measurements m
                JOIN instruments i ON m.instrument_id = i.instrument_id
                WHERE m.codename = ?
            ''', (codename,))
            rows = cursor.fetchall()
            if not rows:
                raise ValueError(f"No measurements found with codename: '{codename}'.")
            instrument_name, measurement_type, values, units = rows[0]
        return MeasurementResult(
            values=values,
            instrument=instrument_name,
            units=units,
            measurement_type=measurement_type
        )

    def store_experiment(self, codename, experiment: Experiment):
        """
        Store an Experiment (including its trial data, parameters, and notes) in the database.
        
        The experiment is stored with its codename, name, description, trial data (as a compressed Polars DataFrame),
        and additional notes. Experiment parameters (with optional notes) are stored in a separate table.
        
        Args:
            codename (str): A unique identifier for the experiment.
            experiment (Experiment): The Experiment instance to store. It should have a 'notes' attribute containing
                                     extra details.
        
        Raises:
            ValueError: If an experiment with the same codename already exists.
        """
        with self._get_connection() as conn:
            # Check for duplicate codename.
            cursor = conn.execute('SELECT experiment_id FROM experiments WHERE codename = ?', (codename,))
            if cursor.fetchone():
                raise ValueError(f"An experiment with codename '{codename}' already exists. Please use a different codename.")
            
            cursor = conn.execute('''
                INSERT INTO experiments (codename, data, name, description, notes)
                VALUES (?, ?, ?, ?, ?)
            ''', (codename, experiment.data, experiment.name, experiment.description, getattr(experiment, "notes", "")))
            experiment_id = cursor.lastrowid
            for param in experiment.parameters.values():
                param_notes = getattr(param, "notes", "")
                conn.execute('''
                    INSERT INTO experiment_parameters (experiment_id, name, units, notes)
                    VALUES (?, ?, ?, ?)
                ''', (experiment_id, param.name, param.units, param_notes))
            conn.commit()

    def retrieve_experiment(self, codename):
        """
        Retrieve an Experiment (with its parameters and notes) from the database by its codename.
        
        The stored trial data (a compressed Polars DataFrame) is loaded back into the Experiment instance.
        
        Args:
            codename (str): The unique identifier for the experiment.
            
        Returns:
            Experiment: The retrieved Experiment instance with data, parameters, and notes populated.
            
        Raises:
            ValueError: If no experiment is found with the given codename.
        """
        with self._get_connection() as conn:
            cursor = conn.execute('SELECT * FROM experiments WHERE codename = ?', (codename,))
            exp_row = cursor.fetchone()
            if not exp_row:
                raise ValueError(f"No experiment found with codename: '{codename}'.")
            experiment_id, _, data, name, description, notes = exp_row
            experiment = Experiment(name, description)
            experiment.data = data
            experiment.notes = notes  # Set the experiment's notes attribute
            cursor = conn.execute('SELECT * FROM experiment_parameters WHERE experiment_id = ?', (experiment_id,))
            for param in cursor.fetchall():
                # param[2]=name, param[3]=units, param[4]=notes
                experiment.add_parameter(param[2], param[3], param[4])
            return experiment

    def close(self):
        """
        Close the database connection.
        
        After calling this method, the Database instance will no longer be able to communicate with the database.
        """
        if self._conn:
            self._conn.close()
            self._conn = None
