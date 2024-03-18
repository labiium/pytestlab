from datetime import datetime
import time
import numpy as np
import polars as pl
import matplotlib.pyplot as plt

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
        if isinstance(self.values, np.float64):
            return f"{self.values} {self.units}"
        elif isinstance(self.values, pl.DataFrame):
            return str(self.values)
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
        return self.values.transpose()[index]

    def get_all(self):
        """Returns all the MeasurementValues in the collection."""
        return self.values.transpose[index]

    def clear(self):
        """Clears all the MeasurementValues from the collection."""
        if isinstance(self.values, np.ndarray):
            self.values = np.array([])
        elif isinstance(self.values, np.float64):
            self.values = np.float64(0)
    
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

            plt.xlabel(xlabel)
            plt.ylabel(ylabel)
        
        if self.measurement_type == "VoltageTime":
            plt.plot(self.values[0], self.values[1])
            xlabel = xlabel if xlabel else "Time (s)"
            ylabel = ylabel if ylabel else f"Voltage ({self.units})"
        
            plt.xlabel(xlabel)
            plt.ylabel(ylabel)
        if self .measurement_type == "franalysis":
            plt.figure(figsize=(12, 6))

            frequency = self.values[:,1].to_numpy()
            gain = self.values[:,2].to_numpy()
            phase = self.values[:,3].to_numpy()

            # Plotting from Polars data
            plt.figure(figsize=(12, 6))

            # Plot Gain vs. Frequency
            plt.subplot(2, 1, 1)
            plt.semilogx(frequency, gain, 'r-o', label='Gain (dB)')
            plt.title('Gain and Phase vs. Frequency')
            plt.ylabel('Gain (dB)')
            plt.grid(True, which="both", ls="--")
            plt.legend(loc='upper left')

            # Plot Phase vs. Frequency
            plt.subplot(2, 1, 2)
            plt.semilogx(frequency, phase, 'b-o', label='Phase (°)')
            plt.xlabel('Frequency (Hz)')
            plt.ylabel('Phase (°)')
            plt.grid(True, which="both", ls="--")
            plt.legend(loc='upper left')

            plt.tight_layout()

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
        if self.measurement_type == "FFT":
            raise ValueError("Cannot perform FFT on FFT measurement.")
        if isinstance(self.values, np.float64):
            raise ValueError("Cannot perform FFT on single value measurement.")
        # Extract the measurement values and convert them to a numpy array

        # Perform the FFT
        fft_result = np.fft.fft(self.values)

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
            realtime_timestamps=self.values[1]
        )

        return fft_measurement_result
    
    def _to_numpy(self):
        """Converts the measurement and timestamp data to numpy arrays."""
        if isinstance(self.values, np.ndarray):
            return self.values.transpose()
        else:
            return np.array(self.values)

    def __len__(self):
        if isinstance(self.values, np.ndarray):
            if len(self.values) == 0:
                return 0
            # check if array is 1D or 2D
            if len(self.values.shape) == 1:
                return len(self.values)
            else:
                return len(self.values[0])
            # return len(self.values[0])
        elif isinstance(self.values, np.float64):
            return 1
        else:
            return len(self.values)

    def __getitem__(self, index):
        return self.values.transpose()[index]

    def __iter__(self):
        return iter(self.values.transpose())

    def __delitem__(self, index):
        del self.values[0][index]
        del self.values[1][index]