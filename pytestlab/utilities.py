import time
from pytestlab.errors import InstrumentNotFoundError, SCPIConnectionError, SCPICommunicationError, SCPIValueError

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
