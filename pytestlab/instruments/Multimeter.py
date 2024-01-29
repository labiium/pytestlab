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
    
    def get_configuration(self):
        """
        
        """
        result = self._query("CONFigure?").replace('"', '')
        mode, other = result.split()
        rang, res = other.split(",")
        if mode == 'CURR':
            mode = 'Current'
        elif mode == 'VOLT':
            mode = 'Voltage'
        # Add more cases if there are other modes
        print(f"Measurement Mode: {mode}")

        # Extract and display the measurement range
        range_val = float(rang)
        print(f"Measurement Range: {range_val} A")  # Assuming it's always in Amperes

        # Extract and display the integration time
        print(f"Integration Time/Resolution: {res}")
    

    def configure(self, mode="VOLT", ac_dc="DC", rang=None, res=None):
        """
        Configures the measurement settings of the multimeter.

        :param mode: Measurement mode (e.g., "VOLT" for voltage, "CURR" for current).
        :param ac_dc: Type of signal - "AC" or "DC".
        :param rang: Measurement range. If None, defaults to AUTO.
        :param res: Resolution (e.g., "SLOW", "MED", "FAST"). If None, defaults to the instrument's default.
        """
        valid_ranges = {"VOLT": ["100mV", "1V", "10V", "100V", "750V"],
                        "CURR": ["10mA", "100mA", "1A", "3A", "10A"]}  # Example ranges; adjust as per the actual specifications

        if rang is not None and rang not in valid_ranges.get(mode, []):
            raise ValueError(f"Invalid range for mode {mode}. Valid ranges are: {valid_ranges.get(mode)}")

        mode_string = f"{mode}:{ac_dc}" if mode in ["VOLT", "CURR"] else mode
        rang_str = f"{rang}" if rang is not None else "AUTO"
        res_str = f",{res}" if res is not None else ""

        command = f"CONF:{mode_string} {rang_str}{res_str}"
        self._send_command(command)


    def measure(self, measurement_type="VOLTAGE", mode="DC", ran="AUTO", int_time="MED"):
        """
        Measures the DC voltage on the specified channel.

        Args:
            measurement_type (str, optional): The type of measurement to perform. Default is "VOLTAGE".
            mode (str, optional): The measurement mode. Default is "DC".
            ran (str, optional): The measurement range. Default is "AUTO".
            int_time (str, optional): The integration time. Default is "SLOW".
        Returns:
            float: The measured voltage.

        Raises:
            ValueError: If an invalid channel is specified.
        """
        # TODO: REMOVE AND UPDATE
        # if channel not in self.description["voltage_channels"]:
        #     raise ValueError(f"Invalid voltage channel {channel}. Supported voltage channels: {self.description['voltage_channels']}")
        
        if measurement_type not in ["CURRENT", "VOLTAGE"]:
            raise ValueError(f"Invalid measurement type {measurement_type}. Supported measurement types: ['CURRENT', 'VOLTAGE']")
        
        if mode not in ["DC", "AC"]:
            raise ValueError(f"Invalid measurement mode {mode}. Supported measurement modes: ['DC', 'AC']")

        if ran not in ["AUTO", "100mV", "1V", "10V", "100V", "750V"]:
            raise ValueError(f"Invalid measurement range {ran}. Supported measurement ranges: ['AUTO', '100mV', '1V', '10V', '100V', '750V']")

        if int_time not in ["SLOW", "MED", "FAST"]:
            raise ValueError(f"Invalid integration time {int_time}. Supported integration times: ['SLOW', 'MED', 'FAST']")
        result = self._query(f"MEASURE:VOLTAGE:{mode}? {ran},{int_time}")
        return float(result)

    # def measure_current(self, channel=1, mode="DC"):
    #     """
    #     Measures the DC current on the specified channel.

    #     Args:
    #         channel (int, optional): The channel number. Default is 1.

    #     Returns:
    #         float: The measured current.

    #     Raises:
    #         ValueError: If an invalid channel is specified.
    #     """
    #     # if channel not in self.description["current_channels"]:
    #     #     raise ValueError(f"Invalid current channel {channel}. Supported current channels: {self.description['current_channels']}")
    #     current = self._query(f"MEASURE:CURRENT:${mode}?")
    #     return float(current)

    # def measure_resistance(self, channel=1):
    #     """
    #     Measures the resistance on the specified channel.

    #     Args:
    #         channel (int, optional): The channel number. Default is 1.

    #     Returns:
    #         float: The measured resistance.

    #     Raises:
    #         ValueError: If an invalid channel is specified.
    #     """
    #     if channel not in self.description["resistance_channels"]:
    #         raise ValueError(f"Invalid resistance channel {channel}. Supported resistance channels: {self.description['resistance_channels']}")
    #     resistance = self._query(f"MEASURE:RESISTANCE? (@{channel})")
    #     return float(resistance)

    # def measure_frequency(self, channel=1):
    #     """
    #     Measures the frequency on the specified channel.

    #     Args:
    #         channel (int, optional): The channel number. Default is 1.

    #     Returns:
    #         float: The measured frequency.

    #     Raises:
    #         ValueError: If an invalid channel is specified.
    #     """
    #     if channel not in self.description["frequency_channels"]:
    #         raise ValueError(f"Invalid frequency channel {channel}. Supported frequency channels: {self.description['frequency_channels']}")
    #     frequency = self._query(f"MEASURE:FREQUENCY? (@{channel})")
    #     return float(frequency)

    # def test_continuity(self, channel=1):
    #     """
    #     Tests for electrical continuity on the specified channel.

    #     Args:
    #         channel (int, optional): The channel number. Default is 1.

    #     Returns:
    #         bool: True if continuity is present, False otherwise.

    #     Raises:
    #         ValueError: If an invalid channel is specified.
    #     """
    #     if channel not in self.description["continuity_channels"]:
    #         raise ValueError(f"Invalid continuity channel {channel}. Supported continuity channels: {self.description['continuity_channels']}")
    #     continuity = self._query(f"TEST:CONTINUITY? (@{channel})")
    #     return bool(int(continuity))  # Assuming continuity returns 1 for True and 0 for False
