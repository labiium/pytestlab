from pytestlab.instruments.instrument import SCPIInstrument
from pytestlab.errors import SCPICommunicationError

class PowerSupply(SCPIInstrument):
    """
    A class representing a Digital Power Supply that inherits from the SCPIInstrument class.

    Provides methods for setting voltage and current, and for enabling or disabling the output.

    Attributes:
        visa_resource (str): The VISA address of the device.
        profile (dict): A dictionary containing additional information about the device.
    """

    def __init__(self, visa_resource=None, profile=None):
        """
        Initializes a DigitalPowerSupply instance.

        Args:
            visa_resource (str): The VISA address of the device.
            description (dict): A dictionary containing additional information about the device.
        """
        super().__init__(visa_resource=visa_resource, profile=profile)
        self.profile = profile

    # def _check_valid_channel(self, selected_channel):
    #     return super()._check_valid_channel(selected_channel)
    
    def set_voltage(self, channel, voltage):
        """
        Sets the voltage for the specified channel.

        Args:
            voltage (float): The voltage value to set.
            channel (int, optional): The channel number. Default is 1.

        Raises:
            SCPICommunicationError: If there's a failure in sending the SCPI command.
        """
        # self._check_channel_range(channel, voltage, "voltage")
        self._send_command(f"VOLTAGE {voltage}, (@{channel})")

    def set_current(self, channel, current):
        """
        Sets the current for the specified channel.

        Args:
            current (float): The current value to set.
            channel (int, optional): The channel number. Default is 1.

        Raises:
            SCPICommunicationError: If there's a failure in sending the SCPI command.
        """
        # self._check_channel_range(channel, current, "current")
        self._send_command(f"CURR {current}, (@{channel})")

    def output(self, channel, state=True):
        """
        Enables the output for the specified channel.

        Args:
            channel (list | int): The channels to enable.

        Raises:
            SCPICommunicationError: If there's a failure in sending the SCPI command.
            OUTPut[:STATe] ON | 1 | OFF | 0[, (@<chanlist>)]

        """
        
        # for chan in channel:
        #     self._check_valid_channel(chan)
        argument = ""
        if type(channel) == int:
            argument = str(channel)
        elif type(channel) == list:
            argument = ",".join([str(chan) for chan in channel])
        else:
            raise ValueError("Invalid channel type")
        # print(argument)
        self._send_command(f"OUTPut:STATe {'ON' if state else 'OFF'}, (@{argument})")


    def display(self, state):
        """
        Enables or disables the display.

        Args:
            state (bool): The state to set. True for on, False for off.

        Raises:
            SCPICommunicationError: If there's a failure in sending the SCPI command.

        DISPlay[:WINDow][:STATe] ON | OFF | 1 | 0
        """
        self._send_command(f"DISP {'ON' if state else 'OFF'}")