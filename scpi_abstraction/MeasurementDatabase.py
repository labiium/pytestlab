import sqlite3

class MeasurementDatabase:
    def __init__(self, db_path):
        self.db_path = db_path
        self._create_tables()

    def _create_tables(self):
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
        return sqlite3.connect(self.db_path)

    def store_measurement_result(self, instrument_name, measurement_data):
        with self._get_connection() as conn:
            conn.execute('''
                INSERT INTO measurements (timestamp, instrument_name, measurement_data)
                VALUES (DATETIME('now'), ?, ?)
            ''', (instrument_name, measurement_data))

    def retrieve_measurement_results(self, instrument_name):
        with self._get_connection() as conn:
            cursor = conn.execute('''
                SELECT timestamp, measurement_data
                FROM measurements
                WHERE instrument_name = ?
            ''', (instrument_name,))
            return cursor.fetchall()
