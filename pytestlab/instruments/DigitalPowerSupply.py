from pytestlab.instruments.instrument import SCPIInstrument
from pytestlab.errors import SCPICommunicationError

class DigitalPowerSupply(SCPIInstrument):
    """
    A class representing a Digital Power Supply that inherits from the SCPIInstrument class.

    Provides methods for setting voltage and current, and for enabling or disabling the output.

    Attributes:
        visa_resource (str): The VISA address of the device.
        description (dict): A dictionary containing additional information about the device.
    """

    def __init__(self, visa_resource, description):
        """
        Initializes a DigitalPowerSupply instance.

        Args:
            visa_resource (str): The VISA address of the device.
            description (dict): A dictionary containing additional information about the device.
        """
        super().__init__(visa_resource)
        self.description = description

    def set_voltage(self, voltage, channel=1):
        """
        Sets the voltage for the specified channel.

        Args:
            voltage (float): The voltage value to set.
            channel (int, optional): The channel number. Default is 1.

        Raises:
            SCPICommunicationError: If there's a failure in sending the SCPI command.
        """
        self._check_channel_range(channel, voltage, "voltage")
        self._send_command(f"VOLTAGE{channel} {voltage}")

    def set_current(self, current, channel=1):
        """
        Sets the current for the specified channel.

        Args:
            current (float): The current value to set.
            channel (int, optional): The channel number. Default is 1.

        Raises:
            SCPICommunicationError: If there's a failure in sending the SCPI command.
        """
        self._check_channel_range(channel, current, "current")
        self._send_command(f"CURRENT{channel} {current}")

    def enable_output(self, channel=1):
        """
        Enables the output for the specified channel.

        Args:
            channel (int, optional): The channel number. Default is 1.

        Raises:
            SCPICommunicationError: If there's a failure in sending the SCPI command.
        """
        self._send_command(f"OUTPUT{channel} ON")

    def disable_output(self, channel=1):
        """
        Disables the output for the specified channel.

        Args:
            channel (int, optional): The channel number. Default is 1.

        Raises:
            SCPICommunicationError: If there's a failure in sending the SCPI command.
        """
        self._send_command(f"OUTPUT{channel} OFF")
