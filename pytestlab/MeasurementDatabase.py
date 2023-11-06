import sqlite3
import time
import numpy as np
from datetime import datetime
from dataclasses import dataclass
import matplotlib.pyplot as plt

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
        units (str): The unit of the measurement value (e.g. "V", "A", "Ohm", "Hz").
        timestamp (float): The timestamp when the measurement was taken.
    """
    def __init__(self, value, units="units", timestamp=None):
        self.value = float(value)
        self.units = units
        self.timestamp = timestamp if timestamp else time.time()

    def __str__(self):
        return f"{self.value} {self.units}"

    def __float__(self.value):
        return self.value
    
class MeasurementResult:
    """A class to represent a collection of measurement values.
    
    Attributes:
        values (list): A list of MeasurementValue objects.
        unit (str): The unit of the measurements.
        instrument (str): The name of the instrument used for the measurements.
        measurement_type (str): The type of measurement.
    """
    def __init__(self, instrument, units, measurement_type, sampling_rate=None):
        self.values = []
        self.unit = units
        self.instrument = instrument
        self.timestamp = time.time()
        self.measurement_type = measurement_type
        self.sampling_rate = sampling_rate

    def __str__(self):
        string = ""
        for value in self.values:
            string += f"{value} {self.unit}\n"

        # remove last newline
        string = string[:-1]
        return string
    
    def __repr__(self):
        return str(self)
    
    def add(self, value):
        """Adds a new MeasurementValue to the collection."""
        ## append to numpy array
        if value.units != self.unit and self.unit != "units" and value.unit != "units":
            raise ValueError("MeasurementValue unit must match MeasurementResult unit.")
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
    
    def plot(self, title=None, xlabel=None, ylabel=None):
        """
        Generates a plot of the measurement values.

        Args:
            title (str, optional): The title of the plot.
            xlabel (str, optional): The label for the x-axis.
            ylabel (str, optional): The label for the y-axis.
        """
        timestamps = [value.timestamp for value in self.values]
        measurements = [value.value for value in self.values]
        
        plt.figure(figsize=(10, 5))
        plt.plot(timestamps, measurements, marker='o')
        
        if title:
            plt.title(title)
        
        xlabel = xlabel if xlabel else "Time (s)"
        ylabel = ylabel if ylabel else f"Measurement ({self.unit})"
        
        plt.xlabel(xlabel)
        plt.ylabel(ylabel)
        plt.grid(True)
        plt.show()

    def perform_fft(self):
        """Performs FFT on the measurement values and returns a MeasurementResult object
        for the frequency spectrum.

        Returns:
            MeasurementResult: An object with frequencies as its measurement values.
        """
        # check if is a time-domain measurement
        if self.measurement_type == "Frequency Spectrum":
            raise ValueError("Cannot perform FFT on Frequency Spectrum measurement.")
        if self.sampling_rate is None:
            raise ValueError("Sampling rate must be set to perform FFT.")

        # Extract the measurement values and convert them to a numpy array
        data = np.array([value.value for value in self.values])

        # Perform the FFT
        fft_result = np.fft.fft(data)

        # Compute the frequency bins
        freq = np.fft.fftfreq(len(fft_result), 1 / self.sampling_rate)

        # Calculate the magnitudes
        magnitudes = np.abs(fft_result)

        # Create a new MeasurementResult for the FFT results
        fft_measurement_result = MeasurementResult(
            instrument=self.instrument,
            units="units",  # or "dB" if converting to decibels
            measurement_type="Frequency Spectrum",
            sampling_rate=self.sampling_rate  # We might include the sampling rate for reference
        )

        # Populate the FFT MeasurementResult with frequency and magnitude pairs
        for f, magnitude in zip(freq, magnitudes):
            fft_measurement_value = MeasurementValue(value=magnitude)
            # Normally we would set the timestamp to the frequency value
            # Since the MeasurementValue class doesn't support a frequency attribute, we misuse the timestamp here
            fft_measurement_value.timestamp = f
            fft_measurement_result.add(fft_measurement_value)

        return fft_measurement_result
    
    def __len__(self):
        return len(self.values)

    def __getitem__(self, index):
        return self.values[index]

    def __iter__(self):
        return iter(self.values)

    def __delitem__(self, index):
        del self.values[index]

class MeasurementDatabase:
    """
    A class for managing a SQLite database that stores measurement results.
    """
    def __init__(self, db_path):
        self.db_path = db_path
        self._create_tables()

    def _create_tables(self):
        with self._get_connection() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS instruments (
                    instrument_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS measurements (
                    measurement_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    instrument_id INTEGER NOT NULL,
                    timestamp TIMESTAMP NOT NULL,
                    value REAL NOT NULL,
                    unit TEXT NOT NULL,
                    type TEXT NOT NULL, -- 'reading' or 'fft'
                    FOREIGN KEY (instrument_id) REFERENCES instruments(instrument_id)
                )
            ''')

    def _get_connection(self):
        return sqlite3.connect(self.db_path)

    def store_reading(self, measurement_result: MeasurementResult):
        """
        Stores a time-domain measurement result in the database.
        """
        with self._get_connection() as conn:
            # Get or create the instrument_id
            instrument_id = self._get_or_create_instrument_id(conn, measurement_result.instrument)

            # Store each MeasurementValue
            for measurement in measurement_result:
                conn.execute('''
                    INSERT INTO measurements (instrument_id, timestamp, value, unit, type)
                    VALUES (?, ?, ?, ?, ?)
                ''', (instrument_id, datetime.fromtimestamp(measurement.timestamp),
                      measurement.value, measurement_result.unit, 'reading'))

    def store_fft_result(self, fft_result: MeasurementResult):
        """
        Stores an FFT measurement result in the database.
        """
        with self._get_connection() as conn:
            # Get or create the instrument_id
            instrument_id = self._get_or_create_instrument_id(conn, fft_result.instrument)

            # Store each FFT result (frequency, magnitude)
            for measurement in fft_result:
                # Assuming timestamp field is reused to store frequency
                conn.execute('''
                    INSERT INTO measurements (instrument_id, timestamp, value, unit, type)
                    VALUES (?, ?, ?, ?, ?)
                ''', (instrument_id, measurement.timestamp, measurement.value,
                      fft_result.unit, 'fft'))

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

    def retrieve_measurements(self, instrument_name, measurement_type):
        """
        Retrieves measurements from the database by instrument name and measurement type.
        """
        with self._get_connection() as conn:
            cursor = conn.execute('''
                SELECT m.timestamp, m.value, m.unit
                FROM measurements m
                JOIN instruments i ON m.instrument_id = i.instrument_id
                WHERE i.name = ? AND m.type = ?
            ''', (instrument_name, measurement_type))
            return cursor.fetchall()