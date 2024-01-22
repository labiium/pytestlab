from .instrument import Instrument
from ..errors import InstrumentConfigurationError
from ..config import MultimeterConfig

class Multimeter(Instrument):
    """
    A class representing a Digital Multimeter that inherits from the SCPIInstrument class.

    Provides methods for measuring voltage, current, resistance, frequency, and testing continuity.

    Attributes:
        visa_resource (str): The VISA address of the device.
        config (MultimeterConfig): A class containing the device configuration.
    """

    def __init__(self, visa_resource=None, config=None, debug_mode=False):
        """
        Initializes a DigitalMultimeter instance.

        Args:
            visa_resource (str): The VISA address of the device.
            config (MultimeterConfig): A class containing the device configuration.
        """
        if not isinstance(config, MultimeterConfig):
            raise InstrumentConfigurationError("MultimeterConfig required to initialize Multimeter")
        super().__init__(visa_resource=visa_resource, config=config, debug_mode=debug_mode)

    @classmethod
    def from_config(cls, config: MultimeterConfig, debug_mode=False):
        return cls(config=MultimeterConfig(**config), debug_mode=debug_mode)
    
    def measure_voltage(self, channel=1):
        """
        Measures the DC voltage on the specified channel.

        Args:
            channel (int, optional): The channel number. Default is 1.

        Returns:
            float: The measured voltage.

        Raises:
            ValueError: If an invalid channel is specified.
        """
        if channel not in self.description["voltage_channels"]:
            raise ValueError(f"Invalid voltage channel {channel}. Supported voltage channels: {self.description['voltage_channels']}")
        voltage = self._query(f"MEASURE:VOLTAGE:DC? (@{channel})")
        return float(voltage)

    def measure_current(self, channel=1):
        """
        Measures the DC current on the specified channel.

        Args:
            channel (int, optional): The channel number. Default is 1.

        Returns:
            float: The measured current.

        Raises:
            ValueError: If an invalid channel is specified.
        """
        if channel not in self.description["current_channels"]:
            raise ValueError(f"Invalid current channel {channel}. Supported current channels: {self.description['current_channels']}")
        current = self._query(f"MEASURE:CURRENT:DC? (@{channel})")
        return float(current)

    def measure_resistance(self, channel=1):
        """
        Measures the resistance on the specified channel.

        Args:
            channel (int, optional): The channel number. Default is 1.

        Returns:
            float: The measured resistance.

        Raises:
            ValueError: If an invalid channel is specified.
        """
        if channel not in self.description["resistance_channels"]:
            raise ValueError(f"Invalid resistance channel {channel}. Supported resistance channels: {self.description['resistance_channels']}")
        resistance = self._query(f"MEASURE:RESISTANCE? (@{channel})")
        return float(resistance)

    def measure_frequency(self, channel=1):
        """
        Measures the frequency on the specified channel.

        Args:
            channel (int, optional): The channel number. Default is 1.

        Returns:
            float: The measured frequency.

        Raises:
            ValueError: If an invalid channel is specified.
        """
        if channel not in self.description["frequency_channels"]:
            raise ValueError(f"Invalid frequency channel {channel}. Supported frequency channels: {self.description['frequency_channels']}")
        frequency = self._query(f"MEASURE:FREQUENCY? (@{channel})")
        return float(frequency)

    def test_continuity(self, channel=1):
        """
        Tests for electrical continuity on the specified channel.

        Args:
            channel (int, optional): The channel number. Default is 1.

        Returns:
            bool: True if continuity is present, False otherwise.

        Raises:
            ValueError: If an invalid channel is specified.
        """
        if channel not in self.description["continuity_channels"]:
            raise ValueError(f"Invalid continuity channel {channel}. Supported continuity channels: {self.description['continuity_channels']}")
        continuity = self._query(f"TEST:CONTINUITY? (@{channel})")
        return bool(int(continuity))  # Assuming continuity returns 1 for True and 0 for False
