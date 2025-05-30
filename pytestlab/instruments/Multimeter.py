from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Type, Union # Union for older Python if | not supported, but annotations helps

from .instrument import Instrument
from ..errors import InstrumentConfigurationError
from ..config import MultimeterConfig
from ..experiments import MeasurementResult

import numpy as np
from uncertainties import ufloat
from uncertainties.core import UFloat # For type hinting float | UFloat

@dataclass
class MultimeterConfigResult:
    """
    Data class to store the current measurement configuration of the multimeter.
    """
    measurement_mode: str
    range_value: float
    resolution: str
    units: str = ""

    def __str__(self) -> str:
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

    def __init__(self, visa_resource: Optional[str] = None, config: Optional[MultimeterConfig] = None, debug_mode: bool = False) -> None:
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
    def from_config(cls: Type[Multimeter], config: MultimeterConfig, debug_mode: bool = False) -> Multimeter:
        # Assuming MultimeterConfig can be instantiated from a dict-like config
        # If MultimeterConfig itself needs specific construction from a dict, that should be handled.
        # For now, assuming config is already a valid MultimeterConfig object or can be spread.
        # If config is a dict that needs to be passed to MultimeterConfig constructor:
        # return cls(config=MultimeterConfig(**config), debug_mode=debug_mode)
        # If config is already a MultimeterConfig instance:
        return cls(config=config, debug_mode=debug_mode)
    
    def get_configuration(self) -> None:
        """
        (Legacy method) Queries the configuration string from the instrument and prints
        the parsed results. For a structured configuration result, use get_config().
        Will be deprecated in future versions.
        """
        result: str = self._query("CONFigure?").replace('"', '')
        mode, other = result.split()
        rang, res = other.split(",")
        if mode == 'CURR':
            mode = 'Current'
        elif mode == 'VOLT':
            mode = 'Voltage'
        # Add more cases if there are other modes
        print(f"Measurement Mode: {mode}")

        # Extract and display the measurement range
        range_val: float = float(rang)
        print(f"Measurement Range: {range_val} A")  # Assuming default units are Amperes

        # Extract and display the resolution
        print(f"Integration Time/Resolution: {res}")
    
    def get_config(self) -> MultimeterConfigResult:
        """
        Retrieves the current measurement configuration from the multimeter.

        This method sends the "CONFigure?" command, parses the returned string,
        and returns a MultimeterConfigResult object containing the measurement mode,
        range, resolution, and appropriate units.

        Returns:
            MultimeterConfigResult: An object containing the current measurement configuration.
        """
        config_str: str = self._query("CONFigure?").replace('"', '').strip()
        try:
            mode_part, settings_part = config_str.split(maxsplit=1)
            range_str, resolution_str = settings_part.split(",") # Renamed resolution to avoid conflict
            range_value_float: float = float(range_str)
        except Exception as e:
            raise ValueError(f"Failed to parse configuration string: {config_str}") from e

        # Determine human-friendly measurement mode and assign units based on mode
        measurement_mode_str: str = "" # Renamed
        unit_str: str = "" # Renamed
        mode_upper: str = mode_part.upper()
        if mode_upper.startswith("VOLT"):
            measurement_mode_str = "Voltage"
            unit_str = "V"
        elif mode_upper.startswith("CURR"):
            measurement_mode_str = "Current"
            unit_str = "A"
        elif mode_upper.startswith("RES"):
            measurement_mode_str = "Resistance"
            unit_str = "Ohm"
        elif mode_upper.startswith("FREQ"):
            measurement_mode_str = "Frequency"
            unit_str = "Hz"
        elif mode_upper.startswith("TEMP"):
            measurement_mode_str = "Temperature"
            unit_str = "°C"  # Default; could also be °F depending on settings
        else:
            measurement_mode_str = mode_part

        return MultimeterConfigResult(
            measurement_mode=measurement_mode_str,
            range_value=range_value_float,
            resolution=resolution_str,
            units=unit_str
        )

    def configure(self, mode: str = "VOLT", ac_dc: str = "DC", rang: Optional[str] = None, res: str = "MED") -> None:
        """
        Configures the measurement settings of the multimeter.

        Args:
            mode (str): Measurement mode (e.g., "VOLT" for voltage, "CURR" for current).
            ac_dc (str): Type of signal - "AC" or "DC".
            rang: Measurement range. If None, defaults to AUTO.
            res (str): Resolution (e.g., "SLOW", "MED", "FAST"). If None, defaults to the instrument's default.
        """
        valid_ranges: dict[str, list[str]] = {"VOLT": ["100mV", "1V", "10V", "100V", "750V"],
                                              "CURR": ["10mA", "100mA", "1A", "3A", "10A"]}  # Example ranges; adjust as per actual specifications

        if rang is not None and rang not in valid_ranges.get(mode, []):
            raise ValueError(f"Invalid range for mode {mode}. Valid ranges are: {valid_ranges.get(mode)}")

        mode_string: str = f"{mode}:{ac_dc}" if mode in ["VOLT", "CURR"] else mode
        rang_str_cmd: str = f"{rang}" if rang is not None else "AUTO" # Renamed
        res_str_cmd: str = f"{res}" if res is not None else "" # Renamed

        command: str = f"CONF:{mode_string} {rang_str_cmd},{res_str_cmd}"
        self._send_command(command)

    def _get_canonical_range_str(self) -> str:
        """
        Gets the current range from the instrument and formats it as a canonical string
        for use in accuracy specification dictionary keys.
        Example: 10.0V -> "10v", 0.1V -> "0.1v"
        """
        # This method queries the instrument for its current configuration.
        # It should be called *after* a command that might auto-range (like MEASURE:...? AUTO)
        # if the goal is to get the range the instrument settled on.
        conf = self.get_config() # get_config queries "CONFigure?"
        val_str = str(conf.range_value) # e.g. "10.0"
        # Remove .0 if present for numbers that are whole integers
        if val_str.endswith(".0"):
            val_str = val_str[:-2]
        return f"{val_str}{conf.units}".lower() # e.g. "10v", "0.1v"

    def measure(self, measurement_type: str = "VOLTAGE", mode: str = "DC", rang: Optional[str] = None, int_time: str = "MED") -> MeasurementResult:
        """
        Makes a measurement on the multimeter. Incorporates uncertainty if configured.

        Args:
            measurement_type (str): The type of measurement to make. Valid values: "VOLTAGE", "CURRENT".
            mode (str): The mode of the measurement. Valid values: "DC", "AC".
            rang: The measurement range (e.g., "1V", "100mV"). Default is "AUTO" if None.
            int_time (str): The integration time of the measurement. Default is "MED".

        Returns:
            MeasurementResult: The measured value (float or ufloat) with additional metadata.
        """
        valid_ranges: dict[str, list[str]] = {
            "VOLT": ["100mV", "1V", "10V", "100V", "750V"], # TODO: These should come from config or profile
            "CURR": ["10mA", "100mA", "1A", "3A", "10A"]
        }

        m_type_upper = measurement_type.upper()
        if m_type_upper not in ["VOLTAGE", "VOLT", "CURRENT", "CURR"]:
            raise ValueError(f"Invalid measurement type {measurement_type}. Valid values: 'VOLTAGE', 'CURRENT'")

        # Validate range if specified
        # For key construction, we use measurement_type normalized to VOLTAGE or CURRENT
        current_m_type_for_dict_lookup = "VOLT" if m_type_upper in ["VOLTAGE", "VOLT"] else "CURR"
        if rang is not None and rang.upper() != "AUTO":
            if rang not in valid_ranges.get(current_m_type_for_dict_lookup, []):
                 raise ValueError(f"Invalid range '{rang}' for mode {current_m_type_for_dict_lookup}. Valid ranges are: {valid_ranges.get(current_m_type_for_dict_lookup)}")

        rang_for_query: str = rang if rang is not None else "AUTO"
        
        # SCPI command for Keysight DMMs often uses VOLT:DC, CURR:AC etc.
        # Ensure measurement_type for query is just VOLT or CURR if that's what the instrument expects for MEAS:
        # The original code used `measurement_type` directly, which could be "VOLTAGE".
        # Assuming instrument takes "VOLTAGE" or "CURRENT" for MEAS: command.
        scpi_measurement_type = "VOLT" if m_type_upper in ["VOLTAGE", "VOLT"] else "CURR"

        response_str: str = self._query(f"MEASURE:{scpi_measurement_type}:{mode.upper()}? {rang_for_query.upper()},{int_time.upper()}")
        reading: float = float(response_str)
        
        value_to_return: float | UFloat = reading # Default to float

        if self.config.measurement_accuracy:
            key_range_part: str
            if rang_for_query.upper() == "AUTO":
                # If auto-ranging, query the actual range the instrument used.
                # _get_canonical_range_str calls self.get_config() which queries the instrument.
                key_range_part = self._get_canonical_range_str()
            else:
                key_range_part = rang_for_query.lower() # e.g. "1v", "100mv"

            # Normalize measurement_type for key construction (e.g. "voltage", "current")
            m_type_key_name = "voltage" if scpi_measurement_type == "VOLT" else "current"
            
            # Construct the key based on convention: e.g., "dc_voltage_1v_range"
            # The prompt example was "dc_voltage_10V_range". My key_range_part is already lowercased.
            mode_key = f"{mode.lower()}_{m_type_key_name}_{key_range_part}_range"
            
            self._logger.debug(f"Attempting to find accuracy spec with key: '{mode_key}'")
            spec = self.config.measurement_accuracy.get(mode_key)

            if spec:
                # The current AccuracySpec.calculate_std_dev only uses reading_value.
                # If it needed range_value, we'd parse key_range_part or use self.get_config().range_value.
                # For now, passing None for range_value to calculate_std_dev.
                sigma = spec.calculate_std_dev(reading, range_value=None)
                if sigma > 0:
                    value_to_return = ufloat(reading, sigma)
                    self._logger.debug(f"Applied accuracy spec '{mode_key}', value: {value_to_return}")
                else:
                    self._logger.debug(f"Accuracy spec '{mode_key}' resulted in sigma=0. Returning float.")
            else:
                self._logger.debug(f"No accuracy spec found for mode '{mode_key}'. Returning float.")
        else:
            self._logger.debug("No measurement_accuracy configuration in instrument. Returning float.")

        # Determine units and human-friendly name based on measurement type.
        units_val: str = ""
        measurement_name_val: str = ""
        if scpi_measurement_type == "VOLT":
            units_val = "V"
            measurement_name_val = "Voltage"
        elif scpi_measurement_type == "CURR":
            units_val = "A"
            measurement_name_val = "Current"
        # Add other types like RES, FREQ if multimeter supports them and they need uncertainty

        return MeasurementResult(
            values=value_to_return, # This can be float or UFloat
            instrument=self.config.model,
            units=units_val,
            measurement_type=measurement_name_val,
        )
