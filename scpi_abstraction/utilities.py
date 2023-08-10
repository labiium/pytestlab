import time
from scpi_abstraction.errors import InstrumentNotFoundError, SCPIConnectionError, SCPICommunicationError, SCPIValueError

def delay(seconds):
    """A utility function to introduce a delay in seconds."""
    time.sleep(seconds)

def validate_visa_resource(visa_resource):
    """A utility function to validate the VISA resource string format."""
    # Add your custom validation logic here to ensure the correct VISA resource format
    # For example, check if the resource string starts with "TCPIP0::" for LAN communication
    if not visa_resource.startswith("TCPIP0::"):
        raise ValueError("Invalid VISA resource format. Please use TCPIP0::<IP_ADDRESS>::INSTR format for LAN instruments.")

    # Add more validation checks if needed

def check_connection(instrument):
    """A utility function to check if the instrument connection is active."""
    try:
        # Send a *IDN? command to verify the connection with the instrument
        response = instrument._query("*IDN?")
        if response:
            print("Connection to the instrument is active.")
    except Exception as e:
        raise SCPIConnectionError()


class MeasurementValue:
    """A utility class to store measurement results value and unit."""
    def __init__(self, value):
        self.value = float(value)
        self.timestamp = time.time()

    def __str__(self):
        return f"{self.value}"


class MeasurementResult:
    """A utility class to store measurement results."""
    def __init__(self, instrument, units, measurement_type):
        self.values = []
        self.unit = units
        self.instrument = instrument
        self.measurement_type = measurement_type

    def add(self, value):
        self.values.append(MeasurementValue(value))

    def get(self, index):
        return self.values[index]
    
    def get_all(self):
        return self.values
    
    def clear(self):
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
            string += f"{value} {self.unit}\n}"
        return string

# Utility function for managing instruments
class InstrumentCollection:
    def __init__(self):
        self.instruments = {}

    def add(self, name, instrument):
        self.instruments[name] = instrument

    def get(self, name):
        if name in self.instruments:
            return self.instruments[name]
        else:
            raise InstrumentNotFoundError(name)
    
    def get_all(self):
        return self.instruments

    def __len__(self):
        return len(self.instruments)
    
    def __contains__(self, name):
        return name in self.instruments
    
    def __iter__(self):
        return iter(self.instruments)
    
    def __getitem__(self, name):
        if name in self.instruments:
            return self.instruments[name]
        else:
            raise InstrumentNotFoundError(name)

    def __setitem__(self, name, instrument):
        self.instruments[name] = instrument


    def __delitem__(self, name):
        if name in self.instruments:
            self.instruments[name].close()
            del self.instruments[name]
        else:
            raise InstrumentNotFoundError(name)
        
    def __del__(self):
        for name in self.instruments:
            self.instruments[name].close()
        self.instruments.clear()

    def __str__(self):
        string = "Instrument Collection:\n"
        for name in self.instruments:
            string += f"{name}: {self.instruments[name].id()}\n"
        return string
    
    def close(self):
        for name in self.instruments:
            self.instruments[name].close()
        self.instruments.clear()

    def clear(self):
        for name in self.instruments:
            self.instruments[name].close()
        self.instruments.clear()

    def keys(self):
        return self.instruments.keys()

    def values(self):
        return self.instruments.values() 

    def remove(self, name):
        if name in self.instruments:
            self.instruments[name].close()
            del self.instruments[name]
        else:
            raise InstrumentNotFoundError(name)