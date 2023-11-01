import sqlite3
import time
import numpy as np
from dataclasses import dataclass

@dataclass
class Preamble:
    """A class to store the preamble data from the oscilloscope channel.

    :param format: The format of the data
    :param type: The type of the data
    :param points: The number of points
    :param xinc: The x increment
    :param xorg: The x origin
    :param xref: The x reference
    :param yinc: The y increment
    :param yorg: The y origin
    :param yref: The y reference
    """

    format: str
    type: str
    points: int
    xinc: float
    xorg: float
    xref: float
    yinc: float
    yorg: float
    yref: float

class MeasurementValue:
    """A class to represent a single measurement value and its timestamp.
    
    Attributes:
        value (float): The measurement value.
        timestamp (float): The timestamp when the measurement was taken.
    """
    def __init__(self, value):
        self.value = float(value)
        self.timestamp = time.time()

    def __str__(self):
        return f"{self.value}"

class MeasurementResult:
    """A class to represent a collection of measurement values.
    
    Attributes:
        values (list): A list of MeasurementValue objects.
        unit (str): The unit of the measurements.
        instrument (str): The name of the instrument used for the measurements.
        measurement_type (str): The type of measurement.
    """
    def __init__(self, instrument, units, measurement_type):
        self.values = np.array([])
        self.unit = units
        self.instrument = instrument
        self.timestamp = time.time()
        self.measurement_type = measurement_type

    def add(self, value):
        """Adds a new MeasurementValue to the collection."""
        ## append to numpy array
        self.values = np.append(self.values, value)

    def set_values(self, values):
        """Sets the MeasurementValues in the collection."""
        self.values = values

    def get(self, index):
        """Gets the MeasurementValue at a specified index."""
        return self.values[index]

    def get_all(self):
        """Returns all the MeasurementValues in the collection."""
        return self.values

    def clear(self):
        """Clears all the MeasurementValues from the collection."""
        self.values.clear()

    def __len__(self):
        return len(self.values)

    def __getitem__(self, index):
        return self.values[index]

    def __iter__(self):
        return iter(self.values)

    def __delitem__(self, index):
        del self.values[index]

    def __str__(self):
        string = ""
        for value in self.values:
            string += f"{value} {self.unit}\n"

        # remove last newline
        string = string[:-1]
        return string

class MeasurementDatabase:
    """
    A class for managing a SQLite database that stores measurement results.

    Provides methods for storing and retrieving measurement data associated with instrument names.

    Attributes:
        db_path (str): The path to the SQLite database file.
    """

    def __init__(self, db_path):
        """
        Initializes the MeasurementDatabase instance.

        Args:
            db_path (str): The path to the SQLite database file.
        """
        self.db_path = db_path
        self._create_tables()

    def _create_tables(self):
        """
        Creates the 'measurements' table in the database if it does not already exist.
        """
        with self._get_connection() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS measurements (
                    measurement_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TIMESTAMP NOT NULL,
                    instrument_name TEXT NOT NULL,
                    measurement_data TEXT NOT NULL
                )
            ''')

    def _get_connection(self):
        """
        Opens a new connection to the SQLite database.

        Returns:
            sqlite3.Connection: A SQLite database connection.
        """
        return sqlite3.connect(self.db_path)

    def store_measurement_result(self, instrument_name, measurement_data):
        """
        Stores a measurement result in the database.

        Args:
            instrument_name (str): The name of the instrument.
            measurement_data (str): The serialized measurement data.
        """
        with self._get_connection() as conn:
            conn.execute('''
                INSERT INTO measurements (timestamp, instrument_name, measurement_data)
                VALUES (DATETIME('now'), ?, ?)
            ''', (instrument_name, measurement_data))

    def store_measurement_result(self, measurement_data: MeasurementResult) -> None:
        """
        Stores a MeasurementResult instance in the database.

        Args:
            measurement_data (MeasurementResult): A MeasurementResult object containing the measurement data and instrument name.

        Note: 
            This method is an overload of the previous method, it expects a MeasurementResult instance.
        """
        with self._get_connection() as conn:
            conn.execute('''
                INSERT INTO measurements (timestamp, instrument_name, measurement_data)
                VALUES (DATETIME('now'), ?, ?)
            ''', (measurement_data.instrument, str(measurement_data)))
            
    def retrieve_measurement_results(self, instrument_name):
        """
        Retrieves all measurement results associated with a given instrument name.

        Args:
            instrument_name (str): The name of the instrument.

        Returns:
            list: A list of tuples where each tuple contains the timestamp and measurement data.
        """
        with self._get_connection() as conn:
            cursor = conn.execute('''
                SELECT timestamp, measurement_data
                FROM measurements
                WHERE instrument_name = ?
            ''', (instrument_name,))
            return cursor.fetchall()
