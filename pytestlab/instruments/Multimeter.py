from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal, Optional, Type, Union

import numpy as np
from uncertainties import ufloat
from uncertainties.core import UFloat  # For type hinting float | UFloat
import warnings

from ..config.multimeter_config import DMMFunction, MultimeterConfig
from ..errors import InstrumentConfigurationError, InstrumentParameterError
from ..experiments import MeasurementResult
from .instrument import Instrument


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

    def __init__(self, config: MultimeterConfig, debug_mode: bool = False, **kwargs) -> None:
        """
        Initializes a Multimeter instance.

        Args:
            config (MultimeterConfig): The configuration object for the multimeter.
            debug_mode (bool): Enable debug mode for the instrument.
        """
        super().__init__(config=config, debug_mode=debug_mode, **kwargs)
        # self.config is now an instance of MultimeterConfig, type hinted at class level

        # Initialize the DMM to its default function if specified in config
        if self.config.default_measurement_function:
            self.set_measurement_function_sync(self.config.default_measurement_function)
        if self.config.trigger_source:
            self.set_trigger_source_sync(self.config.trigger_source)
        # Apply other initial configurations based on self.config as needed

    @classmethod
    def from_config(cls: Type[Multimeter], config: MultimeterConfig, debug_mode: bool = False) -> Multimeter:
        # Assuming MultimeterConfig can be instantiated from a dict-like config
        # If MultimeterConfig itself needs specific construction from a dict, that should be handled.
        # For now, assuming config is already a valid MultimeterConfig object or can be spread.
        # If config is a dict that needs to be passed to MultimeterConfig constructor:
        # return cls(config=MultimeterConfig(**config), debug_mode=debug_mode)
        # If config is already a MultimeterConfig instance:
        return cls(config=config, debug_mode=debug_mode)
    
    async def get_config(self) -> MultimeterConfigResult:
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
        config_str: str = (await self._query("CONFigure?")).replace('"', '').strip()
        try:
            # Parse the string to extract the mode, range, and resolution.
            mode_part, settings_part = config_str.split(maxsplit=1)
            range_str, resolution_str = settings_part.split(",")
            range_value_float: float = float(range_str)
        except Exception as e:
            raise InstrumentDataError(
                self.config.model, f"Failed to parse configuration string: {config_str}"
            ) from e

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

    async def set_measurement_function(self, function: DMMFunction) -> None:
        """Configures the primary measurement function of the DMM.

        This method sets the DMM to measure a specific quantity, such as DC
        Voltage, AC Current, or Resistance.

        Args:
            function: The desired measurement function, as defined by the
                      `DMMFunction` enum.
        """
        scpi_command: str
        if self.config.scpi_commands and self.config.scpi_commands.set_function:
            try:
                scpi_command = self.config.scpi_commands.set_function.format(function_value=function.value)
            except KeyError:
                self._logger.error(f"SCPI command 'set_function' for {self.config.model} has incorrect format key. Using fallback.")
                scpi_command = f"FUNC '{function.value}'"
        else:
            scpi_command = f"FUNC '{function.value}'"
        
        await self._send_command(scpi_command) # Changed to await
        self._logger.info(f"Set measurement function to {function.name} ({function.value})")

    async def set_trigger_source(self, source: Literal["IMM", "EXT", "BUS"]) -> None:
        """Sets the trigger source for initiating a measurement.

        The trigger source determines what event will cause the DMM to start
        taking a reading.
        - "IMM": Immediate, the DMM triggers as soon as it's ready.
        - "EXT": External, a hardware signal on the rear panel triggers the DMM.
        - "BUS": A software command (`*TRG`) triggers the DMM.

        Args:
            source: The desired trigger source.
        """
        scpi_command: str
        if self.config.scpi_commands and self.config.scpi_commands.set_trigger_source:
            try:
                scpi_command = self.config.scpi_commands.set_trigger_source.format(source_value=source.upper())
            except KeyError:
                self._logger.error(f"SCPI command 'set_trigger_source' for {self.config.model} has incorrect format key. Using fallback.")
                scpi_command = f"TRIG:SOUR {source.upper()}"
        else:
            scpi_command = f"TRIG:SOUR {source.upper()}"

        await self._send_command(scpi_command) # Changed to await
        self._logger.info(f"Set trigger source to {source}")

    async def _format_range_for_accuracy_key(self, function: DMMFunction, range_numeric: float, range_units: str) -> str: # Keep async if get_config is async
        """
        Formats a numeric range and its units into a canonical string for accuracy keys.
        Example: 10.0, "V" -> "10v"
        """
        val_str = str(range_numeric)
        if val_str.endswith(".0"):
            val_str = val_str[:-2]
        
        unit_key_str = range_units.strip().lower()
        if not unit_key_str:
            if "VOLTAGE" in function.name.upper(): unit_key_str = "v"
            elif "CURRENT" in function.name.upper(): unit_key_str = "a"
            elif "RESISTANCE" in function.name.upper(): unit_key_str = "ohm"
            else: self._logger.warning(f"Could not determine unit for accuracy key for range {range_numeric} of function {function.name}")
        return f"{val_str}{unit_key_str}"

    async def measure(self, function: DMMFunction, range_val: Optional[str] = None, resolution: Optional[str] = None) -> MeasurementResult:
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

        # Validate the selected range against the supported ranges in the config
        if range_val is not None and range_val.upper() != "AUTO":
            supported_ranges: Optional[list[str]] = None
            if self.config.configuration:
                if function in [DMMFunction.DC_VOLTAGE, DMMFunction.AC_VOLTAGE] and self.config.configuration.voltage:
                    supported_ranges = self.config.configuration.voltage
                elif function in [DMMFunction.DC_CURRENT, DMMFunction.AC_CURRENT] and self.config.configuration.current:
                    supported_ranges = self.config.configuration.current
                elif function in [DMMFunction.RESISTANCE_2W, DMMFunction.RESISTANCE_4W] and self.config.configuration.resistance:
                    supported_ranges = self.config.configuration.resistance
                elif function == DMMFunction.FREQUENCY and self.config.configuration.frequency_ranges:
                     supported_ranges = self.config.configuration.frequency_ranges

            if supported_ranges:
                if not any(r.upper() == range_val.upper() for r in supported_ranges):
                    raise InstrumentParameterError(
                        parameter="range_val",
                        value=range_val,
                        valid_range=supported_ranges,
                        message=f"Unsupported range for function {function.name}.",
                    )
            elif self.config.configuration is None:
                 self._logger.warning(f"No DMMConfiguration in MultimeterConfig for {self.config.model}. Cannot validate range '{range_val}'.")

        range_for_query = range_val.upper() if range_val is not None else "AUTO"
        resolution_for_query = resolution.upper() if resolution is not None else "DEF"
        query_command = f"MEASURE:{scpi_function_val}? {range_for_query},{resolution_for_query}"
        
        self._logger.debug(f"Executing DMM measure query: {query_command}")
        response_str: str = await self._query(query_command)
        reading: float = float(response_str)
        value_to_return: Union[float, UFloat] = reading

        # If accuracy specs are provided, calculate the measurement uncertainty.
        if self.config.measurement_accuracy:
            key_range_part: str
            # Determine the range key for the accuracy lookup table.
            if range_for_query == "AUTO" or not range_val:
                # If auto-ranging, we need to query the DMM to find out what range it actually used.
                try:
                    current_instrument_config = await self.get_config()
                    key_range_part = await self._format_range_for_accuracy_key(function, current_instrument_config.range_value, current_instrument_config.units)
                except Exception as e:
                    self._logger.warning(f"Could not determine auto-range for accuracy key via get_config(): {e}. Accuracy may not be applied.")
                    key_range_part = "auto"
            else:
                # If a specific range was given, parse it.
                match_range = re.match(r"([+-]?\d*\.?\d+(?:[eE][+-]?\d+)?)\s*([a-zA-ZμΩ°]+)?", range_val)
                if match_range:
                    num_str, unit_str_parsed = match_range.group(1), (match_range.group(2) or "")
                    try:
                        num_float = float(num_str)
                        unit_to_use = unit_str_parsed
                        if not unit_to_use:  # Infer unit if not explicitly in the string
                            if "VOLTAGE" in function.name.upper(): unit_to_use = "V"
                            elif "CURRENT" in function.name.upper(): unit_to_use = "A"
                            elif "RESISTANCE" in function.name.upper(): unit_to_use = "Ohm"
                        key_range_part = await self._format_range_for_accuracy_key(function, num_float, unit_to_use)
                    except ValueError:
                        self._logger.warning(f"Could not parse numeric part of '{range_val}'. Using raw string for accuracy key.")
                        key_range_part = range_val.lower()
                else:
                    self._logger.warning(f"Could not parse explicit range '{range_val}'. Using raw string for accuracy key.")
                    key_range_part = range_val.lower()

            func_name_upper = function.name.upper()
            mode_prefix, m_type_key_name = "", ""
            if "VOLTAGE" in func_name_upper: m_type_key_name = "voltage"
            elif "CURRENT" in func_name_upper: m_type_key_name = "current"
            elif "RESISTANCE" in func_name_upper: m_type_key_name = "resistance"
            elif "FREQUENCY" in func_name_upper: m_type_key_name = "frequency"
            elif "PERIOD" in func_name_upper: m_type_key_name = "period"
            elif "TEMPERATURE" in func_name_upper: m_type_key_name = "temperature"
            elif "DIODE" in func_name_upper: m_type_key_name = "diode"
            elif "CONTINUITY" in func_name_upper: m_type_key_name = "continuity"

            if "DC" in func_name_upper: mode_prefix = "dc"
            elif "AC" in func_name_upper: mode_prefix = "ac"
            elif "2W" in func_name_upper: mode_prefix = "2w"
            elif "4W" in func_name_upper: mode_prefix = "4w"
            
            accuracy_key: Optional[str] = None
            if m_type_key_name:
                key_parts = [p for p in [mode_prefix, m_type_key_name, key_range_part if key_range_part != "auto" else None, "range"] if p]
                accuracy_key = "_".join(key_parts)
            else:
                self._logger.warning(f"Could not determine m_type_key_name for {function.name} for accuracy lookup.")

            spec = None
            if accuracy_key and self.config.measurement_accuracy:
                self._logger.debug(f"Attempting to find accuracy spec with key: '{accuracy_key}'")
                spec = self.config.measurement_accuracy.get(accuracy_key)

            if spec:
                numeric_range_for_spec: Optional[float] = None
                if key_range_part and key_range_part != "auto":
                    match = re.match(r"([+-]?\d*\.?\d+(?:[eE][+-]?\d+)?)\s*([a-zA-ZμΩ°]+)?", key_range_part)
                    if match:
                        num_val_str, unit_suffix_str = match.group(1), (match.group(2) or "").lower()
                        try:
                            num_val = float(num_val_str)
                            if unit_suffix_str in ["mv", "mω", "mhz", "ma"]: num_val /= 1000.0
                            elif unit_suffix_str in ["kv", "kω", "khz", "ka"]: num_val *= 1000.0
                            elif unit_suffix_str in ["mω", "mohm"]: num_val *= 1000000.0
                            numeric_range_for_spec = num_val
                        except ValueError:
                             self._logger.debug(f"Could not parse num value from '{num_val_str}' in '{key_range_part}'.")
                
                sigma = spec.calculate_std_dev(reading, range_value=numeric_range_for_spec)
                if sigma > 0:
                    value_to_return = ufloat(reading, sigma)
                    self._logger.debug(f"Applied accuracy spec '{accuracy_key}', value: {value_to_return}")
                else:
                    self._logger.debug(f"Accuracy spec '{accuracy_key}' resulted in sigma <= 0. Returning float.")
            elif accuracy_key:
                self._logger.warning(f"No accuracy spec found for key '{accuracy_key}'. Returning float.")
        else:
            self._logger.debug("No measurement_accuracy configuration in instrument. Returning float.")

        units_val = ""
        measurement_name_val = function.name.replace("_", " ").title()
        if "VOLTAGE" in func_name_upper: units_val = "V"
        elif "CURRENT" in func_name_upper: units_val = "A"
        elif "RESISTANCE" in func_name_upper: units_val = "Ω"
        elif "FREQUENCY" in func_name_upper: units_val = "Hz"
        elif "PERIOD" in func_name_upper: units_val = "s"
        elif "TEMPERATURE" in func_name_upper: units_val = self.config.temperature_unit if self.config and self.config.temperature_unit else "°C"
        elif "DIODE" in func_name_upper: units_val = "V"
        elif "CONTINUITY" in func_name_upper: units_val = "Ω"

        return MeasurementResult(
            values=value_to_return,
            instrument=self.config.model if self.config else "Multimeter",
            units=units_val,
            measurement_type=measurement_name_val,
        )

    def set_measurement_function_sync(self, function: DMMFunction) -> None:
        """
        Sets the measurement function of the DMM.
        """
        warnings.warn(
            "The 'set_measurement_function_sync' method is deprecated and will be removed in a future version. "
            "Please use the asynchronous 'set_measurement_function' method instead.",
            DeprecationWarning,
            stacklevel=2
        )
        self.set_measurement_function(function)

    def set_trigger_source_sync(self, source: Literal["IMM", "EXT", "BUS"]) -> None:
        """
        Sets the trigger source for the DMM.
        """
        warnings.warn(
            "The 'set_trigger_source_sync' method is deprecated and will be removed in a future version. "
            "Please use the asynchronous 'set_trigger_source' method instead.",
            DeprecationWarning,
            stacklevel=2
        )
        self.set_trigger_source(source)

    def measure_sync(self, function: DMMFunction, range_val: Optional[str] = None, resolution: Optional[str] = None) -> MeasurementResult:
        """
        Makes a measurement on the multimeter. Incorporates uncertainty if configured.
        """
        warnings.warn(
            "The 'measure_sync' method is deprecated and will be removed in a future version. "
            "Please use the asynchronous 'measure' method instead.",
            DeprecationWarning,
            stacklevel=2
        )
        return self.measure(function, range_val, resolution)
