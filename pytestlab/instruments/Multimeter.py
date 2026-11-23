# pytestlab/instruments/multimeter/multimeter.py


import math
from dataclasses import dataclass
from numbers import Real
from typing import Any

from pytestlab.config.multimeter_config import MultimeterConfig
from pytestlab.instruments.uncertainty_adapters import dmm_measurement_context
from pytestlab.instruments.uncertainty_adapters import dmm_range_value
from pytestlab.instruments.uncertainty_adapters import nominal_measurement_quantity
from pytestlab.instruments.uncertainty_adapters import nonzero_uncertainty_quantity
from pytestlab.uncertainty import Quantity

from ..errors import InstrumentConfigurationError
from ..errors import InstrumentDataError
from ..errors import InstrumentParameterError
from ..experiments.results import MeasurementResult
from .instrument import Instrument
from .operation_contract import OperationDescriptor


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
        OperationDescriptor("identify", public_method="id", safety_class="read"),
        OperationDescriptor(
            "measure",
            public_method="measure",
            safety_class="read",
        ),
        OperationDescriptor(
            "configure_measurement", public_method="configure_measurement", required=False
        ),
        OperationDescriptor("get_config", safety_class="read"),
        OperationDescriptor("reset", safety_class="state-changing"),
        OperationDescriptor(
            "set_trigger_source",
            public_method="set_trigger_source",
        ),
    )

    # The base class `__init__` is sufficient and will be used.
    # It correctly assigns self.config and self._backend.

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
            self._scpi_engine.build("get_config")
        except KeyError as exc:
            raise InstrumentConfigurationError(
                self.config.model, "Missing SCPI alias 'get_config' in YAML profile."
            ) from exc
        config_str = self._query_profile_alias("get_config")
        parsed = self._scpi_engine.parse("get_config", config_str)
        try:
            if isinstance(parsed, (list, tuple)):
                mode_part = str(parsed[0]).strip().strip('"')
                response = self._scpi_engine.describe("get_config").get("response") or {}
                mode_part = str(response.get("numeric_map", {}).get(mode_part, mode_part))
                range_str = str(parsed[1])
                resolution_str = str(parsed[2]) if len(parsed) > 2 else "N/A"
            else:
                parts = str(parsed).replace('"', "").strip().split()
                mode_part = parts[0]
                settings = " ".join(parts[1:])
                range_str, _, resolution_str = settings.partition(",")
                resolution_str = resolution_str or "N/A"
            range_value_float = float(range_str)
        except (ValueError, IndexError, TypeError) as exc:
            raise InstrumentDataError(
                self.config.model, f"Failed to parse configuration string: {config_str!r}"
            ) from exc

        functions = self.config.measurement_functions
        resolved = functions.function_for_transport_token(mode_part) if functions else None
        if resolved is None:
            raise InstrumentDataError(
                self.config.model,
                "The instrument reported a measurement mode that is not declared "
                f"by its profile: {mode_part!r}",
            )
        function_id, function_spec = resolved
        measurement_mode_str = function_spec.label or function_id
        unit_str = function_spec.unit or ""

        return MultimeterConfigResult(
            measurement_mode=measurement_mode_str,
            range_value=range_value_float,
            resolution=resolution_str.strip(),
            units=unit_str,
        )

    def set_trigger_source(self, source: str) -> None:
        """Sets the trigger source for initiating a measurement.

        The trigger source determines what event will cause the DMM to start
        taking a reading.
        - "IMM": Immediate, the DMM triggers as soon as it's ready.
        - "EXT": External, a hardware signal on the rear panel triggers the DMM.
        - "BUS": A software command (`*TRG`) triggers the DMM.

        Args:
            source: The desired trigger source.
        """
        resolved_source = self._resolve_operation_parameter("set_trigger_source", "source", source)
        try:
            cmds = self._scpi_engine.build(
                "set_trigger_source", source=resolved_source.transport_value
            )
        except KeyError as exc:
            raise InstrumentConfigurationError(
                self.config.model, "Missing SCPI alias 'set_trigger_source' in YAML profile."
            ) from exc
        for c in cmds:
            self._send_command(c)
        self._logger.info(f"Set trigger source to {source} via SCPIEngine")

    def _get_function_spec(self, function: str) -> Any | None:
        """Return the profile specification for a canonical function ID."""

        functions = self.config.measurement_functions
        spec = functions.function_spec(function) if functions is not None else None
        if spec is None:
            raise InstrumentParameterError(
                parameter="function",
                value=function,
                message="Profile does not declare the resolved measurement function.",
            )
        return spec

    def _nplc_parameters(self, alias: str, nplc: float | int | None) -> dict[str, object]:
        """Validate and bind optional profile-declared integration time."""
        if nplc is None:
            return {}
        if isinstance(nplc, bool) or not isinstance(nplc, Real):
            raise InstrumentParameterError(
                parameter="nplc", value=nplc, message="nplc must be a finite real number."
            )
        nplc_value = float(nplc)
        if not math.isfinite(nplc_value):
            raise InstrumentParameterError(
                parameter="nplc", value=nplc, message="nplc must be a finite real number."
            )
        try:
            parameters = self._scpi_engine.list_parameters(alias)
        except KeyError as exc:
            raise InstrumentConfigurationError(
                self.config.model, f"Profile alias '{alias}' does not declare nplc."
            ) from exc
        if "nplc" not in parameters:
            raise InstrumentConfigurationError(
                self.config.model,
                f"Profile alias '{alias}' does not declare nplc; refusing to ignore it.",
            )
        try:
            metadata = self._scpi_engine.describe_parameter(alias, "nplc")
        except (AttributeError, KeyError):
            metadata = {}
        if metadata.get("kind") == "range":
            minimum = metadata.get("min")
            maximum = metadata.get("max")
            out_of_range = (minimum is not None and nplc_value < float(minimum)) or (
                maximum is not None and nplc_value > float(maximum)
            )
            if out_of_range:
                raise InstrumentParameterError(
                    parameter="nplc",
                    value=nplc,
                    valid_range=(minimum, maximum),
                    message="nplc is outside the profile-declared range.",
                )
        return {"nplc": nplc}

    def measure(
        self,
        function: Any,
        range_val: str | float | None = None,
        resolution: str | float | None = None,
        *,
        uncertainty: bool = True,
        nplc: float | int | None = None,
    ) -> MeasurementResult:
        """Measure using profile semantics in a single serialized transaction."""
        with self._profile_transaction():
            return self._measure_unlocked(
                function, range_val, resolution, uncertainty=uncertainty, nplc=nplc
            )

    def _measure_unlocked(
        self,
        function: Any,
        range_val: str | float | None = None,
        resolution: str | float | None = None,
        *,
        uncertainty: bool = True,
        nplc: float | int | None = None,
    ) -> MeasurementResult:
        """Executes a measurement and returns the result.

        This method performs a measurement using the specified function, range,
        and resolution. It handles both autorange and fixed-range measurements,
        and incorporates measurement uncertainty based on the instrument's
        configuration.

        Args:
            function: A semantic ID or profile-declared alias.
            range_val: The requested measurement range (for example ``10`` or
                       ``"AUTO"``). If omitted, the profile's autorange command is used.
            resolution: The desired profile-supported resolution token. If omitted,
                        ``"DEF"`` is used.
            uncertainty: Apply profile-backed uncertainty metadata when true. Set false
                         for a nominal scalar result when uncertainty is outside the task
                         contract; transport error checking is unchanged.

        Returns:
            A `MeasurementResult` object containing the measured value (as a
            nominal float or native `Quantity`), units, and other metadata.

        Raises:
            InstrumentParameterError: If an unsupported `range_val` is provided.
        """
        is_autorange = range_val is None or str(range_val).strip().upper() == "AUTO"
        range_for_query = "AUTO" if is_autorange else range_val
        resolution_for_query = "DEF" if resolution is None else resolution

        function_resolution = self._resolve_operation_parameter("measure", "function", function)
        function_id = function_resolution.value
        function_option = function_resolution.option
        if function_option is None:
            raise InstrumentParameterError(
                parameter="function",
                value=function,
                message="Profile did not provide semantic metadata for the measurement function.",
            )

        function_spec = self._get_function_spec(function_id)
        transport = getattr(function_spec, "transport", None)
        if transport is None:
            raise InstrumentConfigurationError(
                self.config.model, "Measurement function has no private transport mapping."
            )
        measure_alias = str(transport.measure_alias)
        placeholders = self._scpi_engine.validate_placeholders(measure_alias)["placeholders"]
        measure_arguments = {"function": function_resolution.transport_value}
        measure_arguments.update(self._nplc_parameters(measure_alias, nplc))
        for parameter, supplied, effective, placeholder in (
            ("range_val", range_val, range_for_query, "range"),
            ("resolution", resolution, resolution_for_query, "resolution"),
        ):
            if placeholder not in placeholders:
                if supplied is None:
                    continue
                raise InstrumentParameterError(
                    parameter=parameter,
                    value=supplied,
                    message=(
                        f"Measurement function '{function_id}' does not accept '{parameter}'."
                    ),
                )
            resolved = self._resolve_operation_parameter(
                "measure", parameter, effective, context={"function": function_id}
            )
            measure_arguments[placeholder] = resolved.transport_value

        # The selected profile alias is the complete DMM operation. Functions
        # such as diode and continuity use a no-argument query alias rather than
        # receiving invalid generic range/resolution suffixes.
        try:
            commands = self._scpi_engine.build(measure_alias, **measure_arguments)
        except KeyError as exc:
            raise InstrumentConfigurationError(
                self.config.model,
                f"Profile must define the '{measure_alias}' SCPI alias.",
            ) from exc
        self._logger.debug(
            "Executing DMM measure query via SCPIEngine alias %s: %s",
            measure_alias,
            commands[-1],
        )
        response_str = self._query_profile_alias(measure_alias, **measure_arguments)

        try:
            reading = float(response_str)
        except ValueError as e:
            raise InstrumentDataError(
                self.config.model, f"Could not parse measurement reading: '{response_str}'"
            ) from e

        units_val = function_option.unit or ""
        measurement_name_val = function_option.label
        value_to_return: float | Quantity = reading
        if uncertainty:
            value_to_return = nominal_measurement_quantity(
                reading,
                units_val,
                function=function_id,
                output_name=measurement_name_val,
                reason=(
                    f"{self.config.model} {function_id} measurement has no applied uncertainty "
                    "metadata yet; result is nominal-only and non-report-grade."
                ),
            )

        # --- Uncertainty Calculation ---
        function_spec = function_spec if uncertainty else None
        if function_spec:
            try:
                matching_range_spec = None
                actual_instrument_range: float | str | None = None
                actual_instrument_range_numeric: float | None = None
                if function_spec.ranges:
                    self._logger.debug(f"Found {len(function_spec.ranges)} range specifications")
                    valid_ranges = []
                    for range_spec in function_spec.ranges:
                        range_value = dmm_range_value(function_id, range_spec)
                        if range_value is None:
                            self._logger.warning(
                                "Range spec %r has no nominal/max value; ignoring it for "
                                "uncertainty matching.",
                                range_spec,
                            )
                            continue
                        valid_ranges.append((range_spec, float(range_value)))
                    valid_ranges.sort(key=lambda item: item[1])

                    # A numeric range that exactly matches the loaded profile is
                    # already authoritative range context. Querying CONFigure?
                    # again would add I/O without improving uncertainty selection.
                    if not is_autorange and range_val is not None:
                        try:
                            requested_range = float(range_val)
                        except (TypeError, ValueError):
                            requested_range = None
                        if requested_range is not None:
                            for r_spec, profile_range in valid_ranges:
                                if profile_range == requested_range:
                                    actual_instrument_range = requested_range
                                    actual_instrument_range_numeric = requested_range
                                    matching_range_spec = r_spec
                                    break

                    if matching_range_spec is None:
                        current_instrument_config = self.get_config()
                        actual_instrument_range = current_instrument_config.range_value
                        self._logger.debug(f"Actual instrument range: {actual_instrument_range}")
                        try:
                            actual_instrument_range_numeric = float(actual_instrument_range)
                        except (TypeError, ValueError):
                            actual_instrument_range_numeric = None
                            self._logger.warning(
                                "Instrument range %r is not numeric; uncertainty result will "
                                "remain nominal-only until the range context is explicit.",
                                actual_instrument_range,
                            )

                    if matching_range_spec is None and actual_instrument_range_numeric is not None:
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
                            "nominal/max",
                            actual_instrument_range,
                        )
                    elif not valid_ranges:
                        self._logger.warning("No valid profile range values found")
                else:
                    # No accuracy-bearing ranges exist, so another instrument
                    # query cannot improve the uncertainty estimate.
                    self._logger.debug("No range specifications found")

                if matching_range_spec:
                    accuracy_spec = matching_range_spec.accuracy
                    if accuracy_spec:
                        context = dmm_measurement_context(
                            reading=reading,
                            unit=units_val,
                            function=function_id,
                            range_spec=matching_range_spec,
                            measurement_type=measurement_name_val,
                            config=self.config,
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
                                f"{self.config.model} {function_id}: could not determine range "
                                "value for uncertainty calculation; add a range value/resolution "
                                "to the profile or keep the result as non-report-grade."
                            )
                            value_to_return = nominal_measurement_quantity(
                                reading,
                                units_val,
                                function=function_id,
                                output_name=measurement_name_val,
                                reason=reason,
                            )
                            self._logger.warning(
                                "%s Returning nominal-only non-report-grade Quantity.", reason
                            )
                    else:
                        reason = (
                            f"{self.config.model} {function_id}: no applicable accuracy "
                            f"specification found at range {actual_instrument_range}; add an "
                            "accuracy entry to the matching range."
                        )
                        value_to_return = nominal_measurement_quantity(
                            reading,
                            units_val,
                            function=function_id,
                            output_name=measurement_name_val,
                            reason=reason,
                        )
                        self._logger.warning(
                            "%s Returning nominal-only non-report-grade Quantity.", reason
                        )
                else:
                    reason = (
                        f"{self.config.model} {function_id}: could not find a matching range "
                        f"specification at instrument range {actual_instrument_range}; add a "
                        "range spec or keep the result as non-report-grade."
                    )
                    value_to_return = nominal_measurement_quantity(
                        reading,
                        units_val,
                        function=function_id,
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
                    f"{self.config.model} {function_id}: uncertainty calculation failed: {e}; "
                    "result is nominal-only and non-report-grade."
                )
                value_to_return = nominal_measurement_quantity(
                    reading,
                    units_val,
                    function=function_id,
                    output_name=measurement_name_val,
                    reason=reason,
                )
                self._logger.error("%s", reason)
        elif uncertainty:
            self._logger.debug(
                "No measurement function specification in config for %r; returning nominal-only "
                "non-report-grade Quantity.",
                function_id,
            )

        return MeasurementResult(
            values=value_to_return,
            instrument=self.config.model,
            units=units_val,
            measurement_type=measurement_name_val,
        )

    def configure_measurement(
        self,
        function: Any,
        range_val: str | float | None = None,
        resolution: str | float | None = None,
        *,
        nplc: float | int | None = None,
    ) -> None:
        """Configure a profile-declared function without triggering a reading."""
        resolved = self._resolve_operation_parameter("measure", "function", function)
        params = {
            "function": resolved.transport_value,
            "range": "AUTO" if range_val is None else range_val,
            "resolution": "DEF" if resolution is None else resolution,
        }
        params.update(self._nplc_parameters("configure", nplc))
        commands = self._scpi_engine.build("configure", **params)
        with self._profile_transaction():
            for command in commands:
                self._send_command(command)
