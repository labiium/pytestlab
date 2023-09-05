import sqlite3

from scpi_abstraction.utilities import MeasurementResult

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
