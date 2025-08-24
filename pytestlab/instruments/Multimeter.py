# pytestlab/instruments/multimeter/multimeter.py


from dataclasses import dataclass
from typing import Literal

from uncertainties import ufloat
from uncertainties.core import UFloat  # For type hinting float | UFloat

from pytestlab.config.instrument_config import InstrumentConfig
from pytestlab.config.multimeter_config import MultimeterConfig

from .._log import get_logger
from ..config.multimeter_config import DMMFunction
from ..config.multimeter_config import FunctionSpec
from ..errors import InstrumentDataError
from ..experiments.results import MeasurementResult
from .instrument import Instrument

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
        return (
            f"Measurement Mode: {self.measurement_mode}\n"
            f"Range: {self.range_value} {self.units}\n"
            f"Resolution: {self.resolution}"
        )


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
    def from_config(
        cls: type["Multimeter"], config: InstrumentConfig, debug_mode: bool = False
    ) -> "Multimeter":
        # This method is generally handled by the `AutoInstrument` factory.
        # It's provided here for completeness but direct instantiation is preferred
        # when not using the factory.
        # If config is a dict that needs to be passed to MultimeterConfig constructor:
        # return cls(config=MultimeterConfig(**config), debug_mode=debug_mode)
        # If config is already a MultimeterConfig instance:
        # Creation of concrete instrument drivers is handled by AutoInstrument.from_config().
        # Keep this stub for legacy API compatibility while matching the base signature expectations.
        raise NotImplementedError(
            "Instantiate via AutoInstrument.from_config(); direct construction is disabled."
        )

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
        config_str: str = (self._query("CONFigure?")).replace('"', "").strip()
        try:
            # Handle cases where resolution is not returned, e.g., "FRES 1.000000E+02"
            parts = config_str.split()
            mode_part = parts[0]

            # Settings part can be complex, find first comma
            settings_part = " ".join(parts[1:])
            if "," in settings_part:
                range_str, resolution_str = settings_part.split(",", 1)
            else:
                range_str = settings_part
                resolution_str = "N/A"  # Resolution not specified in query response

            # Parse the string to extract the mode, range, and resolution.
            range_value_float: float = float(range_str)
        except (ValueError, IndexError) as e:
            raise InstrumentDataError(
                self.config.model, f"Failed to parse configuration string: '{config_str}'"
            ) from e

        # Determine human-friendly measurement mode and assign units based on mode
        measurement_mode_str: str = ""  # Renamed
        unit_str: str = ""  # Renamed
        mode_upper: str = mode_part.upper()
        if mode_upper.startswith("VOLT"):
            measurement_mode_str = "Voltage"
            unit_str = "V"
        elif mode_upper.startswith("CURR"):
            measurement_mode_str = "Current"
            unit_str = "A"
        elif "RES" in mode_upper:  # Catches RES and FRES
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
            units=unit_str,
        )

    def set_measurement_function(self, function: DMMFunction) -> None:
        """Configures the primary measurement function of the DMM.

        This method sets the DMM to measure a specific quantity, such as DC
        Voltage, AC Current, or Resistance.

        Args:
            function: The desired measurement function, as defined by the
                      `DMMFunction` enum.
        """
        # Prefer SCPIEngine if a profile is provided; fall back to legacy command
        try:
            cmds = self.scpi_engine.build("set_function", function=function)
            for c in cmds:
                self._send_command(c)
            self._logger.info(f"Set measurement function to {function} via SCPIEngine")
            return
        except Exception:
            pass

        # Legacy path
        self._send_command(f'SENSe:FUNCtion "{function}"')
        self._logger.info(f"Set measurement function to {function} (legacy)")

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

    def _get_function_spec(self, function: DMMFunction) -> FunctionSpec | None:
        """Maps a DMMFunction enum to the corresponding spec in the config."""
        mf = self.config.measurement_functions
        func_map: dict[str, FunctionSpec | None] = {}
        if mf is not None:
            func_map = {
                DMMFunction.VOLTAGE_DC: mf.dc_voltage,
                DMMFunction.VOLTAGE_AC: mf.ac_voltage,
                DMMFunction.CURRENT_DC: mf.dc_current,
                DMMFunction.CURRENT_AC: mf.ac_current,
                DMMFunction.RESISTANCE: mf.resistance,
                DMMFunction.FRESISTANCE: mf.resistance_4wire,
                DMMFunction.CAPACITANCE: mf.capacitance,
                DMMFunction.FREQUENCY: mf.frequency,
                DMMFunction.TEMPERATURE: mf.temperature,
            }
        spec = func_map.get(str(function))
        if spec is None:
            logger.warning(f"No measurement specification found for function {function}")
        return spec

    def _get_measurement_unit_and_type(self, function: DMMFunction) -> tuple[str, str]:
        """Gets the appropriate unit and name for the MeasurementResult."""
        function_str = str(function)
        nice_name = function_str.replace("_", " ").title()

        if "VOLTAGE" in function_str:
            return "V", nice_name
        elif "CURRENT" in function_str:
            return "A", nice_name
        elif "RESISTANCE" in function_str:
            return "Ω", nice_name
        elif "CAPACITANCE" in function_str:
            return "F", nice_name
        elif "FREQUENCY" in function_str:
            return "Hz", nice_name
        elif "TEMPERATURE" in function_str:
            return "°C", nice_name
        elif "DIODE" in function_str:
            return "V", nice_name
        elif "CONTINUITY" in function_str:
            return "Ω", nice_name
        return "", nice_name

    def measure(
        self, function: DMMFunction, range_val: str | None = None, resolution: str | None = None
    ) -> MeasurementResult:
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
        scpi_function_val = function
        is_autorange = range_val is None or range_val.upper() == "AUTO"

        # The MEASure command is a combination of CONFigure, INITiate, and FETCh.
        # This is convenient but makes querying the actual range used in autorange tricky.
        # For accurate uncertainty, we will use CONFigure separately when in autorange.
        if is_autorange:
            self.set_measurement_function(function)
            # Try SCPI engine for autorange and resolution, fall back otherwise
            try:
                for c in self.scpi_engine.build("set_range_auto", function=function, state=True):
                    self._send_command(c)
                if resolution:
                    for c in self.scpi_engine.build(
                        "set_resolution", function=function, resolution=resolution.upper()
                    ):
                        self._send_command(c)
                response_str = self.scpi_engine.parse(
                    "read", self._query(self.scpi_engine.build("read")[0])
                )
            except Exception:
                self._send_command(f"{function}:RANGe:AUTO ON")
                if resolution:
                    self._send_command(f"{function}:RESolution {resolution.upper()}")
                response_str = self._query("READ?")
        else:
            # Use the combined MEASure? command for fixed range
            range_for_query = range_val.upper() if range_val is not None else "AUTO"
            resolution_for_query = resolution.upper() if resolution is not None else "DEF"
            # Try SCPIEngine first
            try:
                q = self.scpi_engine.build(
                    "measure",
                    function=scpi_function_val,
                    range=range_for_query,
                    resolution=resolution_for_query,
                )[0]
                self._logger.debug(f"Executing DMM measure query via SCPIEngine: {q}")
                response_str = self._query(q)
                # Parsing handled below as float
            except Exception:
                query_command = (
                    f"MEASURE:{scpi_function_val}? {range_for_query},{resolution_for_query}"
                )
                self._logger.debug(f"Executing DMM measure query (legacy): {query_command}")
                response_str = self._query(query_command)

        try:
            reading = float(response_str)
        except ValueError as e:
            raise InstrumentDataError(
                self.config.model, f"Could not parse measurement reading: '{response_str}'"
            ) from e

        value_to_return: float | UFloat = reading

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
                sorted_ranges = (
                    sorted(function_spec.ranges, key=lambda r: r.max)
                    if function_spec.ranges
                    else []
                )
                for r_spec in sorted_ranges:
                    if r_spec.max >= actual_instrument_range:
                        matching_range_spec = r_spec
                        break

                # Fallback to the largest range if no suitable one is found (e.g. if actual > largest max)
                if not matching_range_spec and function_spec.ranges:
                    matching_range_spec = max(function_spec.ranges, key=lambda r: r.max)

                if matching_range_spec:
                    accuracy_spec = matching_range_spec.accuracy
                    if accuracy_spec:
                        # Use the spec's max value for the '% of range' calculation
                        range_for_calc = matching_range_spec.max
                        std_dev = accuracy_spec.calculate_std_dev(reading, range_for_calc)
                        if std_dev > 0:
                            value_to_return = ufloat(reading, std_dev)
                            self._logger.debug(
                                f"Applied accuracy spec for range {range_for_calc}, value: {value_to_return}"
                            )
                        else:
                            self._logger.debug("Calculated uncertainty is zero. Returning float.")
                    else:
                        self._logger.warning(
                            f"No applicable accuracy specification found for function '{function}' at range {actual_instrument_range}. Returning float."
                        )
                else:
                    self._logger.warning(
                        f"Could not find a matching range specification for function '{function}' at range {actual_instrument_range}. Returning float."
                    )

            except Exception as e:
                self._logger.error(f"Error during uncertainty calculation: {e}. Returning float.")
        else:
            self._logger.debug(
                f"No measurement function specification in config for '{function}'. Returning float."
            )

        units_val, measurement_name_val = self._get_measurement_unit_and_type(function)

        return MeasurementResult(
            values=value_to_return,
            instrument=self.config.model,
            units=units_val,
            measurement_type=measurement_name_val,
        )

    def configure_measurement(
        self, function: DMMFunction, range_val: str | None = None, resolution: str | None = None
    ):
        """Configures the instrument for a measurement without triggering it."""
        scpi_function_val = function
        range_for_query = range_val.upper() if range_val is not None else "AUTO"
        resolution_for_query = resolution.upper() if resolution is not None else "DEF"
        # Using CONFigure command as per programming guide page 44
        cmd = f"CONFigure:{scpi_function_val} {range_for_query},{resolution_for_query}"
        self._send_command(cmd)
        self._logger.info(
            f"Configured DMM for {function} with range={range_for_query}, resolution={resolution_for_query}"
        )
