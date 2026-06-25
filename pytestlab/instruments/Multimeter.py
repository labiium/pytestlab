# pytestlab/instruments/multimeter/multimeter.py


from dataclasses import dataclass
from typing import Literal

from pytestlab.config.instrument_config import InstrumentConfig
from pytestlab.config.multimeter_config import MultimeterConfig
from pytestlab.instruments.uncertainty_adapters import dmm_measurement_context
from pytestlab.instruments.uncertainty_adapters import nominal_measurement_quantity
from pytestlab.instruments.uncertainty_adapters import nonzero_uncertainty_quantity
from pytestlab.uncertainty import Quantity

from .._log import get_logger
from ..config.multimeter_config import DMMFunction
from ..config.multimeter_config import FunctionSpec
from ..errors import InstrumentCommunicationError
from ..errors import InstrumentDataError
from ..experiments.results import MeasurementResult
from .instrument import Instrument
from .operation_contract import OperationDescriptor

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

    OPERATION_CONTRACT: tuple[OperationDescriptor, ...] = (
        OperationDescriptor("identify", required_aliases=("identify",), safety_class="read"),
        OperationDescriptor("read", required_aliases=("read",), safety_class="read"),
        OperationDescriptor("measure", required_aliases=("measure",), safety_class="read"),
        OperationDescriptor("configure", required_aliases=("configure",)),
        OperationDescriptor("get_config", required_aliases=("get_config",), safety_class="read"),
        OperationDescriptor("set_function", required_aliases=("set_function",)),
        OperationDescriptor("set_range_auto", required_aliases=("set_range_auto",)),
        OperationDescriptor("set_resolution", required_aliases=("set_resolution",)),
        OperationDescriptor("set_trigger_source", required_aliases=("set_trigger_source",)),
    )

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
        try:
            config_str: str = (
                (self._query(self.scpi_engine.build("get_config")[0])).replace('"', "").strip()
            )
        except Exception as e:
            from ..errors import InstrumentConfigurationError

            raise InstrumentConfigurationError(
                self.config.model, "Missing SCPI alias 'get_config' in YAML profile."
            ) from e
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
        try:
            cmds = self.scpi_engine.build("set_function", function=function.value)
        except Exception as e:
            from ..errors import InstrumentConfigurationError

            raise InstrumentConfigurationError(
                self.config.model, "Missing SCPI alias 'set_function' in YAML profile."
            ) from e
        for c in cmds:
            self._send_command(c)
        self._logger.info(f"Set measurement function to {function} via SCPIEngine")

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
        try:
            cmds = self.scpi_engine.build("set_trigger_source", source=source)
        except Exception as e:
            from ..errors import InstrumentConfigurationError

            raise InstrumentConfigurationError(
                self.config.model, "Missing SCPI alias 'set_trigger_source' in YAML profile."
            ) from e
        for c in cmds:
            self._send_command(c)
        self._logger.info(f"Set trigger source to {source} via SCPIEngine")

    def _get_function_spec(self, function: DMMFunction) -> FunctionSpec | None:
        """Maps a DMMFunction enum to the corresponding spec in the config."""
        mf = self.config.measurement_functions
        func_map: dict[DMMFunction, FunctionSpec | None] = {}
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
        spec = func_map.get(function)
        if spec is None:
            logger.warning(f"No measurement specification found for function {function}")
        return spec

    def _get_measurement_unit_and_type(self, function: DMMFunction) -> tuple[str, str]:
        """Gets the appropriate unit and name for the MeasurementResult."""
        function_str = function.value  # Use the enum value instead of str(function)
        nice_name = function_str.replace(":", " ").replace("_", " ").title()

        if "VOLT" in function_str:
            return "V", nice_name
        elif "CURR" in function_str:
            return "A", nice_name
        elif "RES" in function_str:
            return "Ω", nice_name
        elif "CAP" in function_str:
            return "F", nice_name
        elif "FREQ" in function_str:
            return "Hz", nice_name
        elif "TEMP" in function_str:
            return "°C", nice_name
        elif "DIOD" in function_str:
            return "V", nice_name
        elif "CONT" in function_str:
            return "Ω", nice_name
        return "", nice_name

    def measure(
        self, function: DMMFunction, range_val: str | None = None, resolution: str | None = None
    ) -> MeasurementResult:
        """Executes a measurement and returns the result.

        This method performs a measurement using the specified function, range,
        and resolution. It handles both autorange and fixed-range measurements,
        and incorporates measurement uncertainty based on the instrument's
        configuration.

        Args:
            function: The measurement function to use (e.g., VOLTAGE_DC, CURRENT_AC).
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
        # Check for and clear any existing errors before measurement
        try:
            self.clear_status()
            errors = self.get_all_errors()
            if errors:
                self._logger.warning(
                    f"Cleared {len(errors)} existing errors before measurement: {errors}"
                )
        except Exception as e:
            self._logger.warning(f"Failed to clear errors before measurement: {e}")

        # Verify instrument is responsive
        # Determine if ID preflight should run (avoid mocked SCPI identify alias)
        do_id_check = True
        try:
            ident_candidate = self.scpi_engine.build("identify")[0]
            if not isinstance(ident_candidate, str) or "IDN" not in ident_candidate.upper():
                do_id_check = False
        except Exception:
            # Leave do_id_check as True; id() will fallback to *IDN?
            pass
        try:
            if do_id_check:
                self.id()  # This should work if instrument is not in error state
        except Exception as e:
            self._logger.warning(f"Instrument not responsive before measurement: {e}")
            # Try to recover from error state
            if self.attempt_error_recovery():
                self._logger.info("Successfully recovered instrument from error state")
            else:
                self._logger.error("Failed to recover instrument from error state")
                raise InstrumentCommunicationError(
                    instrument=self.config.model,
                    message=f"Instrument not responsive and recovery failed: {e}",
                ) from e

        scpi_function_val = function.value
        is_autorange = range_val is None or range_val.upper() == "AUTO"

        # The MEASure command is a combination of CONFigure, INITiate, and FETCh.
        # This is convenient but makes querying the actual range used in autorange tricky.
        # For accurate uncertainty, we will use CONFigure separately when in autorange.
        if is_autorange:
            self.set_measurement_function(function)
            # Autorange ON
            try:
                cmds = self.scpi_engine.build(
                    "set_range_auto", function=scpi_function_val, state=True
                )
            except Exception as e:
                from ..errors import InstrumentConfigurationError

                raise InstrumentConfigurationError(
                    self.config.model, "Missing SCPI alias 'set_range_auto' in YAML profile."
                ) from e
            for c in cmds:
                self._send_command(c)

            # Resolution
            default_resolution = resolution.upper() if resolution is not None else "DEF"
            try:
                cmds = self.scpi_engine.build(
                    "set_resolution", function=scpi_function_val, resolution=default_resolution
                )
            except Exception as e:
                from ..errors import InstrumentConfigurationError

                raise InstrumentConfigurationError(
                    self.config.model, "Missing SCPI alias 'set_resolution' in YAML profile."
                ) from e
            for c in cmds:
                self._send_command(c)

            # Read
            try:
                q = self.scpi_engine.build("read")[0]
            except Exception as e:
                from ..errors import InstrumentConfigurationError

                raise InstrumentConfigurationError(
                    self.config.model, "Missing SCPI alias 'read' in YAML profile."
                ) from e
            response_str = self._query(q)
        else:
            # Use the combined MEASure? command for fixed range
            range_for_query = range_val.upper() if range_val is not None else "AUTO"
            resolution_for_query = resolution.upper() if resolution is not None else "DEF"
            try:
                q = self.scpi_engine.build(
                    "measure",
                    function=scpi_function_val,
                    range=range_for_query,
                    resolution=resolution_for_query,
                )[0]
            except Exception as e:
                from ..errors import InstrumentConfigurationError

                raise InstrumentConfigurationError(
                    self.config.model, "Missing SCPI alias 'measure' in YAML profile."
                ) from e
            self._logger.debug(f"Executing DMM measure query via SCPIEngine: {q}")
            response_str = self._query(q)

        try:
            reading = float(response_str)
        except ValueError as e:
            raise InstrumentDataError(
                self.config.model, f"Could not parse measurement reading: '{response_str}'"
            ) from e

        units_val, measurement_name_val = self._get_measurement_unit_and_type(function)
        value_to_return: float | Quantity = nominal_measurement_quantity(
            reading,
            units_val,
            function=str(getattr(function, "value", function)),
            output_name=measurement_name_val,
            reason=(
                f"{self.config.model} {function!s} measurement has no applied uncertainty "
                "metadata yet; result is nominal-only and non-report-grade."
            ),
        )

        # --- Uncertainty Calculation ---
        function_spec = self._get_function_spec(function)
        if function_spec:
            try:
                # Determine the actual range used by the instrument to find the correct spec
                current_instrument_config = self.get_config()
                actual_instrument_range = current_instrument_config.range_value
                self._logger.debug(f"Actual instrument range: {actual_instrument_range}")
                try:
                    actual_instrument_range_numeric = float(actual_instrument_range)
                except (TypeError, ValueError):
                    actual_instrument_range_numeric = None
                    self._logger.warning(
                        "Instrument range %r is not numeric; uncertainty result will remain "
                        "nominal-only until the range context is explicit.",
                        actual_instrument_range,
                    )

                # Find the matching range specification
                matching_range_spec = None
                # Find the smallest nominal range that is >= the actual range used.
                # Assumes specs in YAML are sorted by nominal value, which is typical.
                if function_spec.ranges:
                    self._logger.debug(f"Found {len(function_spec.ranges)} range specifications")
                    # Debug: show the structure of the first range spec
                    if function_spec.ranges:
                        first_range = function_spec.ranges[0]
                        self._logger.debug(f"First range spec structure: {first_range}")
                        self._logger.debug(f"First range spec dir: {dir(first_range)}")
                        self._logger.debug(
                            f"First range spec dict: {first_range.__dict__ if hasattr(first_range, '__dict__') else 'No __dict__'}"
                        )

                    # Handle different range field names based on function type
                    range_field = None
                    # Map function types to their corresponding range field names
                    if function == DMMFunction.VOLTAGE_DC or function == DMMFunction.VOLTAGE_AC:
                        if hasattr(function_spec.ranges[0], "nominal_V"):
                            range_field = "nominal_V"
                    elif function == DMMFunction.CURRENT_DC or function == DMMFunction.CURRENT_AC:
                        if hasattr(function_spec.ranges[0], "nominal_A"):
                            range_field = "nominal_A"
                    elif function == DMMFunction.RESISTANCE or function == DMMFunction.FRESISTANCE:
                        if hasattr(function_spec.ranges[0], "nominal_ohm"):
                            range_field = "nominal_ohm"
                    elif function == DMMFunction.CAPACITANCE:
                        if hasattr(function_spec.ranges[0], "nominal_F"):
                            range_field = "nominal_F"

                    # Fallback to generic fields if specific ones aren't found
                    if range_field is None:
                        if hasattr(function_spec.ranges[0], "max"):
                            range_field = "max"
                        elif hasattr(function_spec.ranges[0], "max_val"):
                            range_field = "max_val"

                    self._logger.debug(f"Using range field: {range_field}")

                    if range_field and actual_instrument_range_numeric is not None:
                        valid_ranges = []
                        for r in function_spec.ranges:
                            raw_range_value = getattr(r, range_field, None)
                            if raw_range_value is None:
                                self._logger.warning(
                                    f"Range spec {r} has None value for {range_field}"
                                )
                                continue
                            try:
                                valid_ranges.append((r, float(raw_range_value)))
                            except (TypeError, ValueError):
                                self._logger.warning(
                                    "Range spec %r has non-numeric %s=%r; ignoring it for "
                                    "uncertainty matching.",
                                    r,
                                    range_field,
                                    raw_range_value,
                                )

                        valid_ranges.sort(key=lambda item: item[1])
                        for r_spec, range_value in valid_ranges:
                            self._logger.debug(
                                f"Checking range spec: {range_value} >= {actual_instrument_range_numeric}"
                            )
                            if range_value >= actual_instrument_range_numeric:
                                matching_range_spec = r_spec
                                self._logger.debug(f"Found matching range spec: {range_value}")
                                break
                        if valid_ranges and matching_range_spec is None:
                            self._logger.warning(
                                "No configured %s range covers instrument range %r; result "
                                "will remain nominal-only rather than reusing an unrelated range.",
                                range_field,
                                actual_instrument_range,
                            )
                        elif not valid_ranges:
                            self._logger.warning(f"No valid ranges found for field {range_field}")
                else:
                    self._logger.debug("No range specifications found")

                if matching_range_spec:
                    accuracy_spec = matching_range_spec.accuracy
                    if accuracy_spec:
                        context = dmm_measurement_context(
                            reading=reading,
                            unit=units_val,
                            function=function,
                            range_spec=matching_range_spec,
                            measurement_type=measurement_name_val,
                            instrument_key=self._uncertainty_source_key(),
                        )
                        if context is not None:
                            quantity = nonzero_uncertainty_quantity(
                                accuracy_spec,
                                context,
                                logger=self._logger,
                                label=f"accuracy spec for range {context.range_value}",
                                strict=self.config.uncertainty_strict,
                            )
                            if quantity is not None:
                                value_to_return = quantity
                        else:
                            reason = (
                                f"{self.config.model} {function!s}: could not determine range "
                                "value for uncertainty calculation; add a range value/resolution "
                                "to the profile or keep the result as non-report-grade."
                            )
                            value_to_return = nominal_measurement_quantity(
                                reading,
                                units_val,
                                function=str(getattr(function, "value", function)),
                                output_name=measurement_name_val,
                                reason=reason,
                            )
                            self._logger.warning(
                                "%s Returning nominal-only non-report-grade Quantity.", reason
                            )
                    else:
                        reason = (
                            f"{self.config.model} {function!s}: no applicable accuracy "
                            f"specification found at range {actual_instrument_range}; add an "
                            "accuracy entry to the matching range."
                        )
                        value_to_return = nominal_measurement_quantity(
                            reading,
                            units_val,
                            function=str(getattr(function, "value", function)),
                            output_name=measurement_name_val,
                            reason=reason,
                        )
                        self._logger.warning(
                            "%s Returning nominal-only non-report-grade Quantity.", reason
                        )
                else:
                    reason = (
                        f"{self.config.model} {function!s}: could not find a matching range "
                        f"specification at instrument range {actual_instrument_range}; add a "
                        "range spec or keep the result as non-report-grade."
                    )
                    value_to_return = nominal_measurement_quantity(
                        reading,
                        units_val,
                        function=str(getattr(function, "value", function)),
                        output_name=measurement_name_val,
                        reason=reason,
                    )
                    self._logger.warning(
                        "%s Returning nominal-only non-report-grade Quantity.", reason
                    )

            except Exception as e:
                if self.config.uncertainty_strict:
                    raise
                reason = (
                    f"{self.config.model} {function!s}: uncertainty calculation failed: {e}; "
                    "result is nominal-only and non-report-grade."
                )
                value_to_return = nominal_measurement_quantity(
                    reading,
                    units_val,
                    function=str(getattr(function, "value", function)),
                    output_name=measurement_name_val,
                    reason=reason,
                )
                self._logger.error("%s", reason)
        else:
            self._logger.debug(
                "No measurement function specification in config for %r; returning nominal-only "
                "non-report-grade Quantity.",
                function,
            )

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
        scpi_function_val = function.value
        range_for_query = range_val.upper() if range_val is not None else "AUTO"
        resolution_for_query = resolution.upper() if resolution is not None else "DEF"
        try:
            cmds = self.scpi_engine.build(
                "configure",
                function=scpi_function_val,
                range=range_for_query,
                resolution=resolution_for_query,
            )
        except Exception as e:
            from ..errors import InstrumentConfigurationError

            raise InstrumentConfigurationError(
                self.config.model, "Missing SCPI alias 'configure' in YAML profile."
            ) from e
        for c in cmds:
            self._send_command(c)
        self._logger.info(
            f"Configured DMM for {function} with range={range_for_query}, resolution={resolution_for_query}"
        )
