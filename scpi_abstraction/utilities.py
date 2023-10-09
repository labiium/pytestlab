import time
from scpi_abstraction.errors import InstrumentNotFoundError, SCPIConnectionError, SCPICommunicationError, SCPIValueError

def delay(seconds):
    """Pauses the program for the given number of seconds.
    
    Args:
        seconds (float): Time to pause in seconds.
    """
    time.sleep(seconds)

def validate_visa_resource(visa_resource):
    """Validates the VISA resource string format.
    
    Args:
        visa_resource (str): The VISA resource string.
        
    Raises:
        ValueError: If the VISA resource string is in an invalid format.
    """
    if not visa_resource.startswith("TCPIP0::"):
        raise ValueError("Invalid VISA resource format. Please use TCPIP0::<IP_ADDRESS>::INSTR format for LAN instruments.")

def check_connection(instrument):
    """Checks if the instrument connection is active.
    
    Args:
        instrument (object): The instrument object to check the connection for.
        
    Raises:
        SCPIConnectionError: If unable to connect to the instrument.
    """
    try:
        response = instrument._query("*IDN?")
        if response:
            print("Connection to the instrument is active.")
    except Exception as e:
        raise SCPIConnectionError()

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
        self.values = []
        self.unit = units
        self.instrument = instrument
        self.measurement_type = measurement_type

    def add(self, value):
        """Adds a new MeasurementValue to the collection."""
        self.values.append(MeasurementValue(value))

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
        return string

class InstrumentCollection:
    """A class to manage a collection of instruments.
    
    Attributes:
        instruments (dict): A dictionary to store instrument objects by their names.
    """
    def __init__(self):
        self.instruments = {}

    def add(self, name, instrument):
        """Adds an instrument to the collection."""
        self.instruments[name] = instrument

    def get(self, name):
        """Gets an instrument by its name."""
        if name in self.instruments:
            return self.instruments[name]
        else:
            raise InstrumentNotFoundError(name)

    # ... (continue with the remaining methods in the same manner)
