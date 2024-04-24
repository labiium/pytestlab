from .instrument import Instrument
from ..errors import InstrumentConfigurationError
from ..config import PowerSupplyConfig

class PowerSupply(Instrument):
    """
    A class representing a Digital Power Supply that inherits from the SCPIInstrument class.

    Provides methods for setting voltage and current, and for enabling or disabling the output.

    Attributes:
        visa_resource (str): The VISA address of the device.
        profile (dict): A dictionary containing additional information about the device.
    """

    def __init__(self, config=None, debug_mode=False):
        """
        Initializes a DigitalPowerSupply instance.

        Args:
            visa_resource (str): The VISA address of the device.
            description (dict): A dictionary containing additional information about the device.
        """
        if not isinstance(config, PowerSupplyConfig):
            raise InstrumentConfigurationError("PowerSupplyConfig required to initialize PowerSupply")
        super().__init__(config=config, debug_mode=debug_mode)
    
    @classmethod
    def from_config(cls, config: PowerSupplyConfig, debug_mode=False):
        return cls(config=PowerSupplyConfig(**config), debug_mode=debug_mode)
    
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