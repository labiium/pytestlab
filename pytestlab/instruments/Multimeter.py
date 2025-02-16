from dataclasses import dataclass
from .instrument import Instrument
from ..errors import InstrumentConfigurationError
from ..config import MultimeterConfig
from ..experiments import MeasurementResult

import numpy as np

@dataclass
class MultimeterConfigResult:
    """
    Data class to store the current measurement configuration of the multimeter.
    """
    measurement_mode: str
    range_value: float
    resolution: str
    units: str = ""

    def __str__(self):
        return (f"Measurement Mode: {self.measurement_mode}\n"
                f"Range: {self.range_value} {self.units}\n"
                f"Resolution: {self.resolution}")
    

class Multimeter(Instrument):
    """
    A class representing a Digital Multimeter that inherits from the Instrument class.

    Provides methods for measuring voltage, current, resistance, frequency, and testing continuity.

    Attributes:
        visa_resource (str): The VISA address of the device.
        config (MultimeterConfig): A class containing the device configuration.
    """

    def __init__(self, visa_resource=None, config=None, debug_mode=False):
        """
        Initializes a Multimeter instance.

        Args:
            visa_resource (str): The VISA address of the device.
            config (MultimeterConfig): A class containing the device configuration.
        """
        if not isinstance(config, MultimeterConfig):
            raise InstrumentConfigurationError("MultimeterConfig required to initialize Multimeter")
        super().__init__(config=config, debug_mode=debug_mode)

    @classmethod
    def from_config(cls, config: MultimeterConfig, debug_mode=False):
        return cls(config=MultimeterConfig(**config), debug_mode=debug_mode)
    
    def get_configuration(self):
        """
        (Legacy method) Queries the configuration string from the instrument and prints
        the parsed results. For a structured configuration result, use get_config().
        Will be deprecated in future versions.
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
        print(f"Measurement Range: {range_val} A")  # Assuming default units are Amperes

        # Extract and display the resolution
        print(f"Integration Time/Resolution: {res}")
    
    def get_config(self):
        """
        Retrieves the current measurement configuration from the multimeter.

        This method sends the "CONFigure?" command, parses the returned string,
        and returns a MultimeterConfigResult object containing the measurement mode,
        range, resolution, and appropriate units.

        Returns:
            MultimeterConfigResult: An object containing the current measurement configuration.
        """
        config_str = self._query("CONFigure?").replace('"', '').strip()
        try:
            mode_part, settings_part = config_str.split(maxsplit=1)
            range_str, resolution = settings_part.split(",")
            range_value = float(range_str)
        except Exception as e:
            raise ValueError(f"Failed to parse configuration string: {config_str}") from e

        # Determine human-friendly measurement mode and assign units based on mode
        measurement_mode = ""
        unit = ""
        mode_upper = mode_part.upper()
        if mode_upper.startswith("VOLT"):
            measurement_mode = "Voltage"
            unit = "V"
        elif mode_upper.startswith("CURR"):
            measurement_mode = "Current"
            unit = "A"
        elif mode_upper.startswith("RES"):
            measurement_mode = "Resistance"
            unit = "Ohm"
        elif mode_upper.startswith("FREQ"):
            measurement_mode = "Frequency"
            unit = "Hz"
        elif mode_upper.startswith("TEMP"):
            measurement_mode = "Temperature"
            unit = "°C"  # Default; could also be °F depending on settings
        else:
            measurement_mode = mode_part

        return MultimeterConfigResult(
            measurement_mode=measurement_mode,
            range_value=range_value,
            resolution=resolution,
            units=unit
        )

    def configure(self, mode="VOLT", ac_dc="DC", rang=None, res="MED"):
        """
        Configures the measurement settings of the multimeter.

        Args:
            mode (str): Measurement mode (e.g., "VOLT" for voltage, "CURR" for current).
            ac_dc (str): Type of signal - "AC" or "DC".
            rang: Measurement range. If None, defaults to AUTO.
            res (str): Resolution (e.g., "SLOW", "MED", "FAST"). If None, defaults to the instrument's default.
        """
        valid_ranges = {"VOLT": ["100mV", "1V", "10V", "100V", "750V"],
                        "CURR": ["10mA", "100mA", "1A", "3A", "10A"]}  # Example ranges; adjust as per actual specifications

        if rang is not None and rang not in valid_ranges.get(mode, []):
            raise ValueError(f"Invalid range for mode {mode}. Valid ranges are: {valid_ranges.get(mode)}")

        mode_string = f"{mode}:{ac_dc}" if mode in ["VOLT", "CURR"] else mode
        rang_str = f"{rang}" if rang is not None else "AUTO"
        res_str = f"{res}" if res is not None else ""

        command = f"CONF:{mode_string} {rang_str},{res_str}"
        self._send_command(command)

    def measure(self, measurement_type="VOLTAGE", mode="DC", rang=None, int_time="MED"):
        """
        Makes a measurement on the multimeter.

        Args:
            measurement_type (str): The type of measurement to make. Valid values: "VOLTAGE", "CURRENT".
            mode (str): The mode of the measurement. Valid values: "DC", "AC".
            rang: The measurement range. Default is "AUTO" if None.
            int_time (str): The integration time of the measurement. Default is "MED".

        Returns:
            MeasurementResult: The measured value with additional metadata.
        """
        valid_ranges = {"VOLT": ["100mV", "1V", "10V", "100V", "750V"],
                        "CURR": ["10mA", "100mA", "1A", "3A", "10A"]}  # Example ranges; adjust as needed

        key = measurement_type if measurement_type in ["VOLTAGE", "CURR"] else None
        if key is None:
            raise ValueError(f"Invalid measurement type {measurement_type}. Valid values: 'VOLTAGE', 'CURRENT'")

        if rang is not None and rang not in valid_ranges.get(key[:4], []):
            raise ValueError(f"Invalid range for mode {mode}. Valid ranges are: {valid_ranges.get(key[:4])}")

        rang_str = f"{rang}" if rang is not None else "AUTO"
        result = self._query(f"MEASURE:{measurement_type}:{mode}? {rang_str},{int_time}")

        # Determine units and human-friendly name based on measurement type.
        units = ""
        measurement_name = ""
        if measurement_type.upper() in ["VOLTAGE", "VOLT"]:
            units = "V"
            measurement_name = "Voltage"
        elif measurement_type.upper() in ["CURRENT", "CURR"]:
            units = "A"
            measurement_name = "Current"

        return MeasurementResult(
            values=np.float64(result),
            instrument=self.config.model,
            units=units,
            measurement_type=measurement_name,
        )
