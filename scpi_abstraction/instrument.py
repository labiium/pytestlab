import pyvisa
from scpi_abstraction.errors import SCPIConnectionError, SCPICommunicationError

class SCPIInstrument:
    """
    A class representing an SCPI-compliant instrument.

    Attributes:
        visa_resource (str): The VISA resource string that identifies the instrument.
    """

    def __init__(self, visa_resource):
        """
        Initialize the SCPIInstrument class.

        Args:
            visa_resource (str): The VISA resource string to use for the connection.
        """
        self.visa_resource = visa_resource
        self._connect()

    def _connect(self):
        """Connect to the instrument using the VISA resource string."""
        try:
            self.instrument = pyvisa.ResourceManager().open_resource(self.visa_resource)
        except pyvisa.Error as e:
            raise SCPIConnectionError(f"Failed to connect to the instrument: {str(e)}")

    def _send_command(self, command):
        """
        Send an SCPI command to the instrument.

        Args:
            command (str): The SCPI command to send.

        Raises:
            SCPICommunicationError: If sending the command fails.
        """
        try:
            self.instrument.write(command)
        except pyvisa.Error as e:
            raise SCPICommunicationError(f"Failed to send command: {str(e)}")

    def _query(self, query):
        """
        Query the instrument and return the response.

        Args:
            query (str): The SCPI query to send.

        Returns:
            str: The instrument's response to the query.

        Raises:
            SCPICommunicationError: If the query fails.
        """
        try:
            return self.instrument.query(query)
        except pyvisa.Error as e:
            raise SCPICommunicationError(f"Failed to query instrument: {str(e)}")

    def id(self):
        """
        Query the instrument for its identification.

        Returns:
            str: The identification string of the instrument.
        """
        return self._query("*IDN?")
    
    def close(self):
        """Close the connection to the instrument."""
        self.instrument.close()

    def reset(self):
        """Reset the instrument to its default settings."""
        self._send_command("*RST")

    def set_channel_voltage(self, channel, voltage):
        """
        Set the voltage for a specific channel.

        Args:
            channel (int or str): The channel for which to set the voltage.
            voltage (float): The voltage value to set.
        """
        self._send_command(f"CHAN{channel}:VOLT {voltage}")

    def get_channel_voltage(self, channel):
        """
        Get the voltage for a specific channel.

        Args:
            channel (int or str): The channel for which to get the voltage.

        Returns:
            float: The voltage value for the channel.
        """
        response = self._query(f"CHAN{channel}:VOLT?")
        return float(response)

    def measure_frequency(self, channel):
        """
        Measure the frequency for a specific channel.

        Args:
            channel (int or str): The channel for which to measure the frequency.

        Returns:
            float: The measured frequency value for the channel.
        """
        response = self._query(f"MEAS:FREQ? CHAN{channel}")
        return float(response)
