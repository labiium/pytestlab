import numpy as np
from pytestlab.errors import SCPIConnectionError, SCPICommunicationError
from pyscpi import usbtmc
import time

class SCPIInstrument:
    """
    A class representing an SCPI-compliant instrument.

    Attributes:
        visa_resource (str): The VISA resource string that identifies the instrument.
    """

    def __init__(self, visa_resource=None, profile=None, debug_mode=False):
        """
        Initialize the SCPIInstrument class.

        Args:
            visa_resource (str): The VISA resource string to use for the connection.
        """
        if visa_resource:
            self.visa_resource = visa_resource
            self._connect()
        elif "vendor_id" in profile and "product_id" in profile:
            self.instrument = usbtmc.Instrument(profile["vendor_id"], profile["product_id"])
        else:
            raise ValueError("Either a VISA resource string or a vendor and product ID must be provided.")
        self.profile = profile
        self._command_log = []
        self.debug_mode = debug_mode

    def _connect(self):
        """Connect to the instrument using the VISA resource string."""
        try:
            import pyvisa
            self.instrument = pyvisa.ResourceManager().open_resource(self.visa_resource)
        except Exception as e:
            raise SCPIConnectionError(f"Failed to connect to the instrument: {str(e)}")

    def _read_to_np(self) -> bytes:
        chunk_size = 1024
        data = self.instrument.read_raw(chunk_size)
        np.frombuffer(data[10:], dtype=np.uint8)
        header = data[2:10].decode('utf-8')
        data = np.frombuffer(data[10:], dtype=np.uint8)
        self._log(header)

        hpoints = int(header)

        while len(data) < hpoints:
            data = np.append(data, np.frombuffer(
                self.instrument.read_raw(chunk_size), dtype=np.uint8))

        return data[:-1]

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
            self._command_log.append({"command": command, "success": True, "type": "write", "timestamp":time.time})
        except Exception as e:
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
            response =  self.instrument.query(query)
            # self.lo
            # print(response)
            self._command_log.append({"command": query, "success": True, "type": "query", "timestamp":time.time, "response": response})
            self.instrument.query("*OPC?")
            return response
        except Exception as e:
            self._command_log.append({"command": query, "success": False, "type": "query", "timestamp":time.time})
            raise SCPICommunicationError(f"Failed to query instrument: {str(e)}")
        
    def _wait(self):
        """
        Blocks until all previous commands have been processed by the instrument.
        """
        self.instrument.query("*OPC?")

    def _log(self, message):
        """
        Log a message.

        Args:
            message (str): The message to log.
        """
        if self.debug_mode:
            print(message)

    def _history(self):
        """
        Prints history of executed commands
        """
        for command in self._command_log:
            print(command)
    def id(self):
        """
        Query the instrument for its identification.

        Returns:
            str: The identification string of the instrument.
        """
        return self._query("*IDN?")
    
    def _check_valid_channel(self, selected_channel):
        valid_channels = self.profile["channels"].keys()
        min_limit = min(valid_channels)
        max_limit = max(valid_channels)
        
        if not isinstance(selected_channel, int):
            raise ValueError(f"Channel must be an integer. Received: {selected_channel}")
        if selected_channel not in valid_channels:
            raise ValueError(f"Invalid Channel Selected: {selected_channel}. Available Channels: {min_limit} to {max_limit}")
        
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
        self._check_valid_channel(channel)
        self._send_command(f"CHAN{channel}:VOLT {voltage}")

    def get_channel_voltage(self, channel):
        """
        Get the voltage for a specific channel.

        Args:
            channel (int or str): The channel for which to get the voltage.

        Returns:
            float: The voltage value for the channel.
        """
        self._check_valid_channel(channel)
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
        self._check_valid_channel(channel)
        response = self._query(f"MEAS:FREQ? CHAN{channel}")
        return float(response)
