# pytestlab/instruments/multimeter/multimeter.py


import re
from dataclasses import dataclass
from typing import Any, Literal, Optional, Type, Union, Tuple

from uncertainties import ufloat
from uncertainties.core import UFloat  # For type hinting float | UFloat
import warnings
import math

from ..config.multimeter_config import DMMFunction, MultimeterConfig, FunctionSpec
from ..errors import InstrumentConfigurationError, InstrumentParameterError, InstrumentDataError
from ..experiments.results import MeasurementResult
from .instrument import Instrument
from .._log import get_logger

logger = get_logger(__name__)
@dataclass
class MultimeterConfigResult:
    """Stores the current measurement configuration of the multimeter.

    This data class holds the state of the multimeter's configuration at a
    point in time, such as the measurement mode, range, and resolution. It is
    typically returned by methods that query the instrument's status.

    Attributes:
        measurement_mode: The type of measurement being made (e.g., "Voltage").
        range_value: The configured measurement range.
        resolution: The configured resolution.
        units: The units for the measurement range (e.g., "V", "A").
    """
    measurement_mode: str
    range_value: float
    resolution: str
    units: str = ""

    def __str__(self) -> str:
        return (f"Measurement Mode: {self.measurement_mode}\n"
                f"Range: {self.range_value} {self.units}\n"
                f"Resolution: {self.resolution}")


class Multimeter(Instrument[MultimeterConfig]):
    """Drives a Digital Multimeter (DMM) for various measurements.

    This class provides a high-level interface for controlling a DMM, building
    upon the base `Instrument` class. It includes methods for common DMM
    operations such as measuring voltage, current, resistance, and frequency.
    It also handles instrument-specific configurations and can incorporate
    measurement uncertainty based on the provided configuration.

    Attributes:
        config: The Pydantic configuration object (`MultimeterConfig`)
                containing settings specific to this DMM.
    """
    config: MultimeterConfig

    # The base class `__init__` is sufficient and will be used.
    # It correctly assigns self.config and self._backend.

    # from_config is handled by AutoInstrument, so we don't need a custom implementation here.
    @classmethod
    def from_config(cls: Type["Multimeter"], config: MultimeterConfig, debug_mode: bool = False) -> "Multimeter":
        # This method is generally handled by the `AutoInstrument` factory.
        # It's provided here for completeness but direct instantiation is preferred
        # when not using the factory.
        # If config is a dict that needs to be passed to MultimeterConfig constructor:
        # return cls(config=MultimeterConfig(**config), debug_mode=debug_mode)
        # If config is already a MultimeterConfig instance:
        raise NotImplementedError("Please use AutoInstrument.from_config() to create instrument instances.")
    
    def get_config(self) -> MultimeterConfigResult:
        """Retrieves the current measurement configuration from the DMM.

        This method queries the instrument to determine its current settings,
        such as the active measurement function, range, and resolution. It then
        parses this information into a structured `MultimeterConfigResult` object.

        Returns:
            A `MultimeterConfigResult` dataclass instance with the DMM's current
            configuration.

        Raises:
            InstrumentDataError: If the configuration string from the DMM
                                 cannot be parsed.
        """
        # Query the instrument for its current configuration. The response is typically
        # a string like '"VOLT:DC 10,0.0001"'.
        config_str: str = (self._query("CONFigure?")).replace('"', '').strip()
        try:
            # Handle cases where resolution is not returned, e.g., "FRES 1.000000E+02"
            parts = config_str.split()
            mode_part = parts[0]
            
            # Settings part can be complex, find first comma
            settings_part = " ".join(parts[1:])
            if ',' in settings_part:
                range_str, resolution_str = settings_part.split(",", 1)
            else:
                range_str = settings_part
                resolution_str = "N/A" # Resolution not specified in query response
            
            # Parse the string to extract the mode, range, and resolution.
            range_value_float: float = float(range_str)
        except (ValueError, IndexError) as e:
            raise InstrumentDataError(self.config.model, f"Failed to parse configuration string: '{config_str}'") from e

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
        elif "RES" in mode_upper: # Catches RES and FRES
            measurement_mode_str = "Resistance"
            unit_str = "Ohm"
        elif "FREQ" in mode_upper:
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
            resolution=resolution_str.strip(),
            units=unit_str
        )

    def set_measurement_function(self, function: DMMFunction) -> None:
        """Configures the primary measurement function of the DMM.

        This method sets the DMM to measure a specific quantity, such as DC
        Voltage, AC Current, or Resistance.

        Args:
            function: The desired measurement function, as defined by the
                      `DMMFunction` enum.
        """
        # Using the recommended SCPI command from the programming guide (page 145)
        self._send_command(f'SENSe:FUNCtion "{function.value}"')
        self._logger.info(f"Set measurement function to {function.name} ({function.value})")

    def set_trigger_source(self, source: Literal["IMM", "EXT", "BUS"]) -> None:
        """Sets the trigger source for initiating a measurement.

        The trigger source determines what event will cause the DMM to start
        taking a reading.
        - "IMM": Immediate, the DMM triggers as soon as it's ready.
        - "EXT": External, a hardware signal on the rear panel triggers the DMM.
        - "BUS": A software command (`*TRG`) triggers the DMM.

        Args:
            source: The desired trigger source.
        """
        self._send_command(f"TRIG:SOUR {source.upper()}")
        self._logger.info(f"Set trigger source to {source}")

    def _get_function_spec(self, function: DMMFunction) -> Optional[FunctionSpec]:
        """Maps a DMMFunction enum to the corresponding spec in the config."""
        func_map = {
            DMMFunction.VOLTAGE_DC: self.config.measurement_functions.dc_voltage,
            DMMFunction.VOLTAGE_AC: self.config.measurement_functions.ac_voltage,
            DMMFunction.CURRENT_DC: self.config.measurement_functions.dc_current,
            DMMFunction.CURRENT_AC: self.config.measurement_functions.ac_current,
            DMMFunction.RESISTANCE: self.config.measurement_functions.resistance,
            DMMFunction.FRESISTANCE: self.config.measurement_functions.resistance_4wire,
            DMMFunction.CAPACITANCE: self.config.measurement_functions.capacitance,
            DMMFunction.FREQUENCY: self.config.measurement_functions.frequency,
            DMMFunction.TEMPERATURE: self.config.measurement_functions.temperature,
        }
        spec = func_map.get(function)
        if spec is None:
            logger.warning(f"No measurement specification found for function {function.name}")
        return spec

    def _get_measurement_unit_and_type(self, function: DMMFunction) -> Tuple[str, str]:
        """Gets the appropriate unit and name for the MeasurementResult."""
        if "VOLTAGE" in function.name: return "V", function.name.replace("_", " ").title()
        if "CURRENT" in function.name: return "A", function.name.replace("_", " ").title()
        if "RESISTANCE" in function.name: return "Ω", function.name.replace("_", " ").title()
        if "CAPACITANCE" in function.name: return "F", function.name.replace("_", " ").title()
        if "FREQUENCY" in function.name: return "Hz", function.name.replace("_", " ").title()
        if "TEMPERATURE" in function.name: return "°C", function.name.replace("_", " ").title()
        if "DIODE" in function.name: return "V", function.name.replace("_", " ").title()
        if "CONTINUITY" in function.name: return "Ω", function.name.replace("_", " ").title()
        return "", function.name.replace("_", " ").title()

    def measure(self, function: DMMFunction, range_val: Optional[str] = None, resolution: Optional[str] = None) -> MeasurementResult:
        """Performs a measurement and returns the result.

        This is the primary method for acquiring data from the DMM. It configures
        the measurement, triggers it, and reads the result. If measurement
        accuracy specifications are provided in the instrument's configuration,
        this method will calculate the uncertainty and return the value as a
        `UFloat` object.

        Args:
            function: The measurement function to perform (e.g., DC Voltage).
            range_val: The measurement range (e.g., "1V", "AUTO"). If not provided,
                       "AUTO" is used. The value is validated against the ranges
                       defined in the instrument's configuration.
            resolution: The desired resolution (e.g., "MIN", "MAX", "DEF"). If not
                        provided, "DEF" (default) is used.

        Returns:
            A `MeasurementResult` object containing the measured value (as a float
            or `UFloat`), units, and other metadata.

        Raises:
            InstrumentParameterError: If an unsupported `range_val` is provided.
        """
        scpi_function_val = function.value
        is_autorange = range_val is None or range_val.upper() == "AUTO"

        # The MEASure command is a combination of CONFigure, INITiate, and FETCh.
        # This is convenient but makes querying the actual range used in autorange tricky.
        # For accurate uncertainty, we will use CONFigure separately when in autorange.
        if is_autorange:
            self.set_measurement_function(function)
            self._send_command(f"{function.value}:RANGe:AUTO ON")
            if resolution:
                self._send_command(f"{function.value}:RESolution {resolution.upper()}")
            
            response_str = self._query("READ?")
        else:
            # Use the combined MEASure? command for fixed range
            range_for_query = range_val.upper() if range_val is not None else "AUTO"
            resolution_for_query = resolution.upper() if resolution is not None else "DEF"
            query_command = f"MEASURE:{scpi_function_val}? {range_for_query},{resolution_for_query}"
            self._logger.debug(f"Executing DMM measure query: {query_command}")
            response_str = self._query(query_command)

        try:
            reading = float(response_str)
        except ValueError:
            raise InstrumentDataError(self.config.instrument['model'], f"Could not parse measurement reading: '{response_str}'")
        
        value_to_return: Union[float, UFloat] = reading

        # --- Uncertainty Calculation ---
        function_spec = self._get_function_spec(function)
        if function_spec:
            try:
                # Determine the actual range used by the instrument to find the correct spec
                current_instrument_config = self.get_config()
                actual_instrument_range = current_instrument_config.range_value

                # Find the matching range specification
                matching_range_spec = None
                # Find the smallest nominal range that is >= the actual range used.
                # Assumes specs in YAML are sorted by nominal value, which is typical.
                for r_spec in sorted(function_spec.ranges, key=lambda r: r.nominal):
                    if r_spec.nominal >= actual_instrument_range:
                        matching_range_spec = r_spec
                        break
                
                # Fallback to the largest range if no suitable one is found (e.g. if actual > largest nominal)
                if not matching_range_spec:
                    matching_range_spec = max(function_spec.ranges, key=lambda r: r.nominal)

                if matching_range_spec:
                    accuracy_spec = matching_range_spec.default_accuracy
                    if accuracy_spec:
                        # Use the spec's nominal value for the '% of range' calculation
                        range_for_calc = matching_range_spec.nominal
                        std_dev = accuracy_spec.calculate_uncertainty(reading, range_for_calc)
                        if std_dev > 0:
                            value_to_return = ufloat(reading, std_dev)
                            self._logger.debug(f"Applied accuracy spec for range {range_for_calc}, value: {value_to_return}")
                        else:
                             self._logger.debug(f"Calculated uncertainty is zero. Returning float.")
                    else:
                        self._logger.warning(f"No applicable accuracy specification found for function '{function.name}' at range {actual_instrument_range}. Returning float.")
                else:
                    self._logger.warning(f"Could not find a matching range specification for function '{function.name}' at range {actual_instrument_range}. Returning float.")

            except Exception as e:
                self._logger.error(f"Error during uncertainty calculation: {e}. Returning float.")
        else:
            self._logger.debug(f"No measurement function specification in config for '{function.name}'. Returning float.")

        units_val, measurement_name_val = self._get_measurement_unit_and_type(function)

        return MeasurementResult(
            values=value_to_return,
            instrument=self.config.model,
            units=units_val,
            measurement_type=measurement_name_val,
        )

    def configure_measurement(self, function: DMMFunction, range_val: Optional[str] = None, resolution: Optional[str] = None):
        """Configures the instrument for a measurement without triggering it."""
        scpi_function_val = function.value
        range_for_query = range_val.upper() if range_val is not None else "AUTO"
        resolution_for_query = resolution.upper() if resolution is not None else "DEF"
        # Using CONFigure command as per programming guide page 44
        cmd = f"CONFigure:{scpi_function_val} {range_for_query},{resolution_for_query}"
        self._send_command(cmd)
        self._logger.info(f"Configured DMM for {function.name} with range={range_for_query}, resolution={resolution_for_query}")