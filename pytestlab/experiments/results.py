from datetime import datetime
import time
import numpy as np
import polars as pl
import matplotlib.pyplot as plt
import polars as pl

class MeasurementResult:
    """A class to represent a collection of measurement values.
    
    Attributes:
        values (list): A list of MeasurementValue objects.
        units (str): The units of the measurements.
        instrument (str): The name of the instrument used for the measurements.
        measurement_type (str): The type of measurement.
    """
    def __init__(self, values, instrument, units, measurement_type, **kwargs):
        self.values = values
        self.units = units
        self.instrument = instrument
        self.measurement_type = measurement_type
        self.timestamp = time.time()

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
        return self.values[index]

    def get_all(self):
        """Returns all the MeasurementValues in the collection."""
        return self.values

    def clear(self):
        """Clears all the MeasurementValues from the collection."""
        if isinstance(self.values, np.ndarray):
            self.values = np.array([])
        elif isinstance(self.values, np.float64):
            self.values = np.float64(0)
        elif isinstance(self.values, pl.DataFrame):
            self.values = pl.DataFrame()
        else:
            self.values = np.float64(0)
    
    def _to_numpy(self):
        """Converts the measurement and timestamp data to numpy arrays."""
        if isinstance(self.values, np.ndarray):
            return self.values.transpose()
        elif isinstance(self.values, pl.DataFrame):
            return self.values.to_numpy()
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