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


# @dataclass
# class MeasurementSet:


#     ty
class MeasurementResult:
    """A class to represent a collection of measurement values.
    
    Attributes:
        values (list): A list of MeasurementValue objects.
        units (str): The units of the measurements.
        instrument (str): The name of the instrument used for the measurements.
        measurement_type (str): The type of measurement.
    """
    def __init__(self, values, instrument, units, measurement_type, sampling_rate=None, realtime_timestamps=False):
        self.values = values
        self.units = units
        self.instrument = instrument
        self.measurement_type = measurement_type
        self.timestamp = time.time()
        self.sampling_rate = sampling_rate

    def __str__(self):
        string = ""
        for value in self.values:
            string += f"{value} {self.units}\n"

        # remove last newline
        string = string[:-1]
        return string
    
    def __repr__(self):
        return str(self)
    
    def add(self, value):
        """Adds a new MeasurementValue to the collection."""
        ## append to numpy array
        # TODO: check if units match
        # if value.units != self.units and self.units != "units" and value.units != "units":
        #     raise ValueError("MeasurementValue units must match MeasurementResult units.")
        self.values = np.append(self.values, value)

    def set_values(self, values):
        """Sets the MeasurementValues in the collection."""
        self.values = values

    def get(self, index):
        """Gets the MeasurementValue at a specified index."""
        return self.values.transpose[index]

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
        
        if self.measurement_type == "FFT":
            plt.plot(self.values[0], self.values[1])
            ## change grid
            xlabel = xlabel if xlabel else "Frequency (Hz)"
            ylabel = ylabel if ylabel else f"Magnitude ({self.units})"
        
        if self.measurement_type == "VoltageTime":
            plt.plot(self.values[0], self.values[1])
            xlabel = xlabel if xlabel else "Time (s)"
            ylabel = ylabel if ylabel else f"Voltage ({self.units})"
        
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
            units=self.units,
            measurement_type="FFT",
            sampling_rate=self.sampling_rate,  #  for reference
            values = np.array([freq, magnitudes]),
            realtime_timestamps=self.realtime_timestamps
        )

        return fft_measurement_result
    
    def _to_numpy(self):
        """Converts the measurement and timestamp data to numpy arrays."""
        if isinstance(self.values, np.ndarray):
            return self.values.transpose()
        else:
            return np.array(self.values)

    def __len__(self):
        return len(self.values[0])

    def __getitem__(self, index):
        return self.values.transpose()[index]

    def __iter__(self):
        return iter(self.values.transpose())

    def __delitem__(self, index):
        del self.values[0][index]
        del self.values[1][index]

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
                    units TEXT NOT NULL,
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
                    INSERT INTO measurements (instrument_id, timestamp, value, units, type)
                    VALUES (?, ?, ?, ?, ?)
                ''', (instrument_id, datetime.fromtimestamp(measurement.timestamp),
                      measurement.value, measurement_result.units, 'reading'))

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
                    INSERT INTO measurements (instrument_id, timestamp, value, units, type)
                    VALUES (?, ?, ?, ?, ?)
                ''', (instrument_id, measurement.timestamp, measurement.value,
                      fft_result.units, 'fft'))

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
                SELECT m.timestamp, m.value, m.units
                FROM measurements m
                JOIN instruments i ON m.instrument_id = i.instrument_id
                WHERE i.name = ? AND m.type = ?
            ''', (instrument_name, measurement_type))
            return cursor.fetchall()