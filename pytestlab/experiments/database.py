import sqlite3
import time
import numpy as np
from datetime import datetime
from .results import MeasurementResult
from .experiments import Experiment
import polars as pl

class Database:
    """
    A class for managing a SQLite database that stores measurement results.
    """
    def __init__(self, db_path):
        self.db_path = db_path
        self._conn = None  # Add this line
        sqlite3.register_adapter(np.ndarray, self.adapt_npdata)
        sqlite3.register_converter("NPDATA", self.convert_npdata)
        sqlite3.register_adapter("PLDATA", self.adapt_dataframe)
        self._create_tables()

    @staticmethod
    def adapt_dataframe(df):
        """
        Adapter function to convert a Polars DataFrame to a binary format, including schema.
        """
        data = df.to_ipc()
        schema = df.schema.to_json()
        return sqlite3.Binary(data + b";" + schema.encode())
    
    @staticmethod
    def decode_dataframe(text):
        """
        Converter function to convert binary text to a Polars DataFrame.
        """
        if isinstance(text, bytes):
            data, schema = text.rsplit(b";", 1)
            schema = pl.Schema.parse_json(schema.decode())
            return pl.read_ipc(data, schema=schema)
        else:
            return pl.DataFrame()

    @staticmethod
    def adapt_npdata(arr):
        """
        Adapter function to convert a numpy array (including np.float64 numbers
        and matrices) to a binary format, including shape and dtype.
        - arr: A numpy array, which can be a scalar (0D), vector (1D), matrix (2D), or higher-dimensional.
        """
        data = arr.tobytes()
        dtype = str(arr.dtype)
        shape = ",".join(map(str, arr.shape))  # Works for scalars (0D) with an empty shape tuple
        # Use a unique separator that is unlikely to appear in dtype or shape
        return sqlite3.Binary(data + b";" + dtype.encode() + b";" + shape.encode())

    @staticmethod
    def convert_npdata(text):
        """
        Converter function to convert binary text to a numpy array,
        including reconstructing shape and dtype. Supports np.float64 and matrices.
        """
        if isinstance(text, bytes):
            data, dtype_str, shape_str = text.rsplit(b";", 2)
            dtype = dtype_str.decode()
            shape = tuple(map(int, shape_str.decode().split(",")))
            # np.frombuffer will correctly handle scalar (0D), vector (1D), matrix (2D), etc.
            return np.frombuffer(data, dtype=dtype).reshape(shape)
        else:
            return np.float64(text)

    def _create_tables(self):
        with self._get_connection() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS experiments (
                    experiment_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    codename TEXT UNIQUE,
                    data PLDATA,
                    name TEXT NOT NULL,
                    description TEXT
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
                CREATE TABLE IF NOT EXISTS trial_parameters (
                    trial_parameter_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    parameter_id INTEGER,
                    trial_id INTEGER,
                    value REAL,
                    FOREIGN KEY (trial_id) REFERENCES trials(trial_id)
                    FOREIGN KEY (parameter_id) REFERENCES experiment_parameters(parameter_id)
                )
            ''')


            conn.execute('''
                CREATE TABLE IF NOT EXISTS trials (
                    trial_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    experiment_id INTEGER,
                    timestamp TIMESTAMP,
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
                    trial_id INTEGER,
                    codename TEXT UNIQUE,
                    instrument_id INTEGER NOT NULL,
                    timestamp TIMESTAMP NOT NULL,
                    value NPDATA NOT NULL,
                    units TEXT NOT NULL,
                    type TEXT, -- 'reading' or 'fft'
                    FOREIGN KEY (instrument_id) REFERENCES instruments(instrument_id),
                    FOREIGN KEY (trial_id) REFERENCES trials(trial_id)
                )
            ''')


    def _get_connection(self):
        if self._conn is None:
            self._conn = sqlite3.connect(f"{self.db_path}.db", detect_types=sqlite3.PARSE_DECLTYPES)
        return self._conn

    # def store_fft_result(self, codename, fft_result: MeasurementResult):
    #     """
    #     Stores an FFT measurement result in the database.
    #     """
    #     with self._get_connection() as conn:
    #         # Get or create the instrument_id
    #         instrument_id = self._get_or_create_instrument_id(conn, fft_result.instrument)

    #         # Store each FFT result (frequency, magnitude)
    #         for measurement in fft_result:
    #             # Assuming timestamp field is reused to store frequency
    #             conn.execute('''
    #                 INSERT INTO measurements (instrument_id, timestamp, value, units, type)
    #                 VALUES (?, ?, ?, ?, ?)
    #             ''', (instrument_id, measurement.timestamp, measurement.value,
    #                   fft_result.units, 'fft'))

    def _get_or_create_instrument_id(self, conn, instrument_name):
        """
        Retrieves the instrument ID for the given name, or creates it if it doesn't exist.
        """
        cursor = conn.execute('SELECT instrument_id FROM instruments WHERE name = ?', (instrument_name,))
        result = cursor.fetchone()
        if result:
            return result[0]
        else:
            cursor.execute('INSERT INTO instruments (name) VALUES (?)', (instrument_name,))
            return cursor.lastrowid


    def store_measurement(self, codename, measurement_result: MeasurementResult, force=False):
        """
        Stores a time-domain measurement result in the database.
        """
        with self._get_connection() as conn:

            try:
                # Get or create the instrument_id
                instrument_id = self._get_or_create_instrument_id(conn, measurement_result.instrument)

                if force:
                    # Use INSERT OR REPLACE to update an existing record with the same codename
                    sql_statement = '''
                        INSERT OR REPLACE INTO measurements (codename, instrument_id, timestamp, value, units, type)
                        VALUES (?, ?, ?, ?, ?, ?)
                    '''
                else:
                    # Regular INSERT to fail on duplicate codename
                    sql_statement = '''
                        INSERT INTO measurements (codename, instrument_id, timestamp, value, units, type)
                        VALUES (?, ?, ?, ?, ?, ?)
                    '''
                conn.execute(sql_statement, (codename, instrument_id, datetime.fromtimestamp(measurement_result.timestamp),
                                     measurement_result.values, measurement_result.units, measurement_result.measurement_type))

            except sqlite3.IntegrityError:
                print("codename already in use")
            
    def retrieve_measurement(self, codename):
        """
        Retrieves a measurement from a given codename
        """
        with self._get_connection() as conn:
            cursor = conn.execute('''
                SELECT i.name, m.type, m.value, m.units
                FROM measurements m
                JOIN instruments i ON m.instrument_id = i.instrument_id
                WHERE m.codename = ?
            ''', (codename,))  # Note the comma here, which makes it a tuple

            rows = cursor.fetchall()
            if not rows:
                raise ValueError(f"No measurements found with codename: '{codename}'.")

            # Assuming you want to use the first row's data to construct the MeasurementResult
            # Note: You had some undefined variables (instrument_name and measurement_type); fixing this:
            instrument_name, measurement_type, values, units = rows[0]

            values = self.convert_npdata(values)
        
        # Construct and return the MeasurementResult object
        return MeasurementResult(values=values, instrument=instrument_name,
                                 units=units, measurement_type=measurement_type)


    def store_experiment(self, codename, experiment):
        """Stores an experiment and its measurements in the database."""
        with self._get_connection() as conn:
            # Store the experiment
            data = self.adapt_dataframe(experiment.data)
            cursor = conn.execute('''
                INSERT INTO experiments (codename, data, name, description)
                VALUES (?, ?, ?)
            ''', (codename, experiment.data, experiment.name, experiment.description))
            experiment_id = cursor.lastrowid

            # Store experiment parameters
            for param in experiment.parameters.values():
                conn.execute('''
                    INSERT INTO experiment_parameters (experiment_id, name, units, notes)
                    VALUES (?, ?, ?, ?)
                ''', (experiment_id, param.name, param.units, param.notes))

    def retrieve_experiment(self, codename):
        """Retrieves an experiment by codename, including its parameters and measurements."""
        with self._get_connection() as conn:
            cursor = conn.execute('SELECT * FROM experiments WHERE codename = ?', (codename,))
            experiment = cursor.fetchone()
            if not experiment:
                raise ValueError(f"No experiment found with codename: '{codename}'.")
            
            experiment_id, _, data, name, description = experiment

            experiment = Experiment(name, description)
            experiment.data = self.decode_dataframe(data)

            cursor = conn.execute('SELECT * FROM experiment_parameters WHERE experiment_id = ?', (experiment_id,))
            return experiment
        
    def close(self):
        if hasattr(self, '_conn') and self._conn:
            self._conn.close()
            self._conn = None
