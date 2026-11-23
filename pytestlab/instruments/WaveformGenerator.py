"""
Module providing a high-level interface for Keysight EDU33210 Series
Trueform Arbitrary Waveform Generators.
"""

from __future__ import annotations

import math
import re
import warnings
from dataclasses import dataclass
from dataclasses import field
from typing import Any
from typing import Self

import numpy as np
from pydantic import validate_call

from ..config import InstrumentConfig
from ..config import WaveformGeneratorConfig
from ..errors import InstrumentCommunicationError
from ..errors import InstrumentConfigurationError
from ..errors import InstrumentParameterError
from .instrument import Instrument
from .operation_contract import OperationDescriptor


class WGChannelFacade:
    """Fluent handle for one waveform generator output channel.


    Returned by :meth:`WaveformGenerator.channel`. Methods return the facade so
    calls can be chained, for example
    ``awg.channel(1).setup_sine(1000, 1.0).enable()``.
    """

    def __init__(self, wg: WaveformGenerator, channel_num: int):
        self._wg = wg
        self._channel = channel_num

    @validate_call
    def setup_sine(
        self, frequency: float, amplitude: float, offset: float = 0.0, phase: float | None = None
    ) -> Self:
        """Configure this channel to output a sine wave.


        Args:
            frequency: Frequency in Hz.
            amplitude: Peak-to-peak amplitude in volts.
            offset: DC offset in volts.
            phase: Optional phase in the current angle unit (degrees by default).

        Returns:
            This facade, so calls can be chained.
        """
        commands = self._wg._build_function_commands(
            self._channel,
            "sine",
            {},
            {"frequency": frequency, "amplitude": amplitude, "offset": offset},
            phase=phase,
            amplitude_unit="VPP",
        )
        for command in commands:
            self._wg._send_command(command)
        return self

    @validate_call
    def setup_square(
        self,
        frequency: float,
        amplitude: float,
        offset: float = 0.0,
        duty_cycle: float = 50.0,
        phase: float | None = None,
    ) -> Self:
        """Configure this channel to output a square wave.


        Args:
            frequency: Frequency in Hz.
            amplitude: Peak-to-peak amplitude in volts.
            offset: DC offset in volts.
            duty_cycle: High-time percentage of the period.

        Returns:
            This facade, so calls can be chained.
        """
        commands = self._wg._build_function_commands(
            self._channel,
            "square",
            {"set_square_duty_cycle": {"duty_cycle": duty_cycle}},
            {"frequency": frequency, "amplitude": amplitude, "offset": offset},
            phase=phase,
            amplitude_unit="VPP",
        )
        for command in commands:
            self._wg._send_command(command)
        return self

    @validate_call
    def setup_ramp(
        self,
        frequency: float,
        amplitude: float,
        offset: float = 0.0,
        symmetry: float = 50.0,
        phase: float | None = None,
    ) -> Self:
        """Configure this channel to output a ramp or triangle wave.


        Args:
            frequency: Frequency in Hz.
            amplitude: Peak-to-peak amplitude in volts.
            offset: DC offset in volts.
            symmetry: Rising-edge percentage; 50 gives a triangle wave.

        Returns:
            This facade, so calls can be chained.
        """
        commands = self._wg._build_function_commands(
            self._channel,
            "ramp",
            {"set_ramp_symmetry": {"symmetry": symmetry}},
            {"frequency": frequency, "amplitude": amplitude, "offset": offset},
            phase=phase,
            amplitude_unit="VPP",
        )
        for command in commands:
            self._wg._send_command(command)
        return self

    @validate_call
    def setup_pulse(
        self,
        frequency: float,
        amplitude: float,
        offset: float = 0.0,
        width: float | None = None,
        duty_cycle: float | None = None,
        transition_both: float | None = None,
        phase: float | None = None,
    ) -> Self:
        """Configure this channel to output a pulse train.


        Args:
            frequency: Pulse repetition frequency in Hz.
            amplitude: Peak-to-peak amplitude in volts.
            offset: DC offset in volts.
            width: Pulse width in seconds.
            duty_cycle: High-time percentage when width is not provided.
            transition_both: Leading and trailing edge transition time in seconds.
            phase: Optional phase in the current angle unit.

        Returns:
            This facade, so calls can be chained.
        """
        if frequency <= 0:
            raise InstrumentParameterError(
                parameter="frequency", value=frequency, message="Must be > 0 for pulse setup."
            )
        period = 1.0 / frequency

        pulse_params = {"set_pulse_period": {"period": period}}
        if width is not None:
            pulse_params["set_pulse_width"] = {"width": width}
        elif duty_cycle is not None:
            pulse_params["set_pulse_duty_cycle"] = {"duty_cycle": duty_cycle}
        else:
            pulse_params["set_pulse_duty_cycle"] = {"duty_cycle": 50.0}

        if transition_both is not None:
            pulse_params["set_pulse_transition_both"] = {"transition_both": transition_both}

        commands = self._wg._build_function_commands(
            self._channel,
            "pulse",
            pulse_params,
            {"amplitude": amplitude, "offset": offset},
            phase=phase,
            amplitude_unit="VPP",
        )
        for command in commands:
            self._wg._send_command(command)
        return self

    @validate_call
    def setup_arbitrary(
        self,
        arb_name: str,
        sample_rate: float,
        amplitude: float,
        offset: float = 0.0,
        phase: float | None = None,
    ) -> Self:
        """Configure this channel to replay a stored arbitrary waveform.


        Args:
            arb_name: Name of a waveform already downloaded to the instrument.
            sample_rate: Playback sample rate in samples per second.
            amplitude: Peak-to-peak amplitude in volts.
            offset: DC offset in volts.

        Returns:
            This facade, so calls can be chained.
        """
        self._wg.set_function(self._channel, "arbitrary")
        self._wg.select_arbitrary_waveform(self._channel, arb_name)
        self._wg.set_arbitrary_waveform_sample_rate(self._channel, sample_rate)
        self._wg.set_offset(self._channel, offset)
        self._wg.set_voltage_unit(self._channel, "VPP")
        self._wg.set_amplitude(self._channel, amplitude)
        if phase is not None:
            self._wg.set_phase(self._channel, phase)
        return self

    @validate_call
    def setup_dc(self, offset: float) -> Self:
        """Configure this channel to output a constant DC level.


        Args:
            offset: Output level in volts.

        Returns:
            This facade, so calls can be chained.
        """
        self._wg.set_function(self._channel, "dc")
        self._wg.set_offset(self._channel, offset)
        return self

    @validate_call
    def enable(self) -> Self:
        """Turn this channel's output on.


        Returns:
            This facade, so calls can be chained.
        """
        self._wg.set_output_state(self._channel, True)
        return self

    @validate_call
    def disable(self) -> Self:
        """Turn this channel's output off.


        Returns:
            This facade, so calls can be chained.
        """
        self._wg.set_output_state(self._channel, False)
        return self

    @validate_call
    def set_load_impedance(self, impedance: float | str) -> Self:
        """Set the expected load impedance for this channel.


        The instrument uses this to scale the programmed amplitude. Pass ``50`` for
        a 50 ohm load or ``"INFinity"`` for a high-impedance load.

        Returns:
            This facade, so calls can be chained.
        """
        self._wg.set_output_load_impedance(self._channel, impedance)
        return self

    @validate_call
    def set_voltage_unit(self, unit: str) -> Self:
        """Set the unit amplitudes are programmed in for this channel.


        Args:
            unit: Vpp, Vrms or dBm.

        Returns:
            This facade, so calls can be chained.
        """
        self._wg.set_voltage_unit(self._channel, unit)
        return self


@dataclass
class WaveformConfigResult:
    """
    Data class storing the retrieved waveform configuration of a channel.

    Provides a structured way to access key parameters of the channel's current state,
    obtained by querying multiple SCPI commands.

    Attributes:
        channel (int): The channel number (1 or 2).
        function (str): The short SCPI name of the active waveform function (e.g., "SIN", "RAMP").
        frequency (float): The current frequency in Hz (or sample rate in Sa/s for ARB).
        amplitude (float): The current amplitude in the configured voltage units.
        offset (float): The current DC offset voltage in Volts.
        phase (Optional[float]): The current phase offset in the configured angle units (None if not applicable).
        symmetry (Optional[float]): The current symmetry percentage for RAMP/TRIANGLE (None otherwise).
        duty_cycle (Optional[float]): The current duty cycle percentage for SQUARE/PULSE (None otherwise).
        output_state (Optional[bool]): The current state of the main output (True=ON, False=OFF).
        load_impedance (Optional[Union[float, str]]): The configured load impedance (Ohms or "INFinity").
        voltage_unit (Optional[str]): The currently configured voltage unit ("VPP", "VRMS", "DBM").

    Note:
        Consider adding fields for active modulation/sweep/burst state if needed.
    """

    channel: int
    function: str
    frequency: float
    amplitude: float
    offset: float
    phase: float | None = None
    symmetry: float | None = None
    duty_cycle: float | None = None
    output_state: bool | None = None
    load_impedance: float | str | None = None
    voltage_unit: str | None = None


@dataclass
class FileSystemInfo:
    """
    Data class representing the results of a directory listing query (`list_directory`).

    Contains information about memory usage and the files/folders found in the queried path.

    Attributes:
        bytes_used (int): Total bytes used on the specified memory volume (INT or USB).
        bytes_free (int): Total bytes free on the specified memory volume.
        files (List[Dict[str, Any]]): A list of dictionaries, each representing a file or folder.
                                      Example entry: `{'name': 'f.txt', 'type': 'FILE', 'size': 1024}`.
                                      Type might be 'FILE', 'FOLDER', 'ARB', 'STAT', etc., depending on the file
                                      extension and instrument response. Size is in bytes.
    """

    bytes_used: int
    bytes_free: int
    files: list[dict[str, Any]] = field(default_factory=list)


class WaveformGenerator(Instrument[WaveformGeneratorConfig]):
    """Profile-driven SCPI interface for arbitrary waveform generators.

    Concrete command syntax, channel count, limits, and supported features come
    from :class:`WaveformGeneratorConfig`; the driver is not restricted to one
    Keysight model family.
    """

    config: WaveformGeneratorConfig  # Type hint for validated config

    OPERATION_CONTRACT: tuple[OperationDescriptor, ...] = (
        OperationDescriptor(
            "set_function",
            public_method="set_function",
        ),
        OperationDescriptor(
            "apply_waveform_settings",
            public_method="apply_waveform_settings",
        ),
        OperationDescriptor(
            "get_function",
            public_method="get_function",
            safety_class="read",
        ),
        OperationDescriptor(
            "set_frequency",
            public_method="set_frequency",
        ),
        OperationDescriptor(
            "get_frequency",
            public_method="get_frequency",
            safety_class="read",
        ),
        OperationDescriptor(
            "set_amplitude",
            public_method="set_amplitude",
        ),
        OperationDescriptor(
            "get_amplitude",
            public_method="get_amplitude",
            safety_class="read",
        ),
        OperationDescriptor(
            "set_offset",
            public_method="set_offset",
        ),
        OperationDescriptor(
            "get_offset",
            public_method="get_offset",
            safety_class="read",
        ),
        OperationDescriptor(
            "set_output_state",
            public_method="set_output_state",
        ),
        OperationDescriptor(
            "get_output_state",
            public_method="get_output_state",
            safety_class="read",
        ),
    ) + tuple(
        OperationDescriptor(
            alias,
            public_method=alias,
            required=alias
            not in {
                "get_output_load_impedance",
                "get_arbitrary_waveform_points",
                "get_pulse_transition_both",
                "get_channel_configuration_summary",
                "get_complete_config",
                "download_arbitrary_waveform_data",
                "download_arbitrary_waveform_data_binary",
            },
            safety_class="read" if alias.startswith("get_") else "state-changing",
        )
        for alias in (
            "reset",
            "get_angle_unit",
            "set_phase",
            "set_phase_reference",
            "synchronize_phase_all_channels",
            "set_phase_unlock_error_state",
            "set_output_load_impedance",
            "set_output_polarity",
            "set_voltage_unit",
            "set_voltage_limits_state",
            "set_voltage_limit_high",
            "set_voltage_limit_low",
            "set_voltage_autorange_state",
            "set_sync_output_state",
            "set_sync_output_mode",
            "set_sync_output_polarity",
            "set_sync_output_source",
            "select_arbitrary_waveform",
            "set_arbitrary_waveform_sample_rate",
            "clear_volatile_arbitrary_waveforms",
            "enable_modulation",
            "set_am_depth",
            "set_am_source",
            "set_fm_deviation",
            "enable_sweep",
            "set_sweep_time",
            "set_sweep_start_frequency",
            "set_sweep_stop_frequency",
            "set_sweep_spacing",
            "enable_burst",
            "set_burst_mode",
            "set_burst_cycles",
            "set_burst_period",
            "set_trigger_source",
            "set_trigger_slope",
            "trigger_now",
            "set_angle_unit",
            "download_arbitrary_waveform_data_csv",
            "list_directory",
            "delete_file_or_folder",
            "get_phase",
            "get_phase_unlock_error_state",
            "get_output_polarity",
            "get_voltage_unit",
            "get_voltage_limits_state",
            "get_voltage_limit_high",
            "get_voltage_limit_low",
            "get_voltage_autorange_state",
            "get_sync_output_state",
            "get_sync_output_mode",
            "get_sync_output_polarity",
            "get_sync_output_source",
            "get_selected_arbitrary_waveform_name",
            "get_arbitrary_waveform_sample_rate",
            "get_free_volatile_arbitrary_memory",
            "get_pulse_duty_cycle",
            "get_pulse_period",
            "get_pulse_width",
            "get_pulse_transition_leading",
            "get_pulse_transition_trailing",
            "get_pulse_hold_mode",
            "get_square_duty_cycle",
            "get_square_period",
            "get_ramp_symmetry",
            "get_output_load_impedance",
            "get_arbitrary_waveform_points",
            "get_pulse_transition_both",
            "get_channel_configuration_summary",
            "get_complete_config",
            "download_arbitrary_waveform_data",
            "download_arbitrary_waveform_data_binary",
        )
    )
    model_config = {"arbitrary_types_allowed": True}

    def _profile_bool_token(self, value: bool | str) -> str:
        """Resolve a semantic boolean through the profile's state choices."""
        semantic = getattr(value, "value", value)
        if isinstance(semantic, bool):
            semantic = "on" if semantic else "off"
        return str(self._scpi_engine.resolve_parameter("set_output_state", "state", semantic))

    def _profile_bool_response(self, response: str, command: str) -> bool:
        """Convert a profile-declared state response to a semantic boolean."""
        value = response.strip().casefold()
        for choice in self._scpi_engine.list_options("set_output_state", "state"):
            semantic = str(choice.get("value", "")).casefold()
            keys = {semantic, str(choice.get("token", "")).casefold()}
            keys.update(str(alias).casefold() for alias in choice.get("aliases", []) or [])
            if value in keys:
                return semantic == "on"
        raise InstrumentCommunicationError(
            instrument=self.config.model,
            command=command,
            message=f"Unexpected response: {response!r}",
        )

    def _profile_enum_value(self, alias: str, parameter: str, response: str) -> str:
        value = response.strip().casefold()
        for choice in self._scpi_engine.list_options(alias, parameter):
            semantic = str(choice.get("value", ""))
            keys = {semantic.casefold(), str(choice.get("token", "")).casefold()}
            keys.update(str(item).casefold() for item in choice.get("aliases", []) or [])
            if value in keys:
                return semantic
        raise InstrumentCommunicationError(
            instrument=self.config.model,
            command=f"{parameter} readback",
            message=f"Unexpected response: {response!r}",
        )

    def _profile_special_value(self, value: str) -> str | None:
        """Resolve a generic special value through profile metadata."""
        options = getattr(self.config, "operation_options", None)
        parameter = options.parameter("special_values", "value") if options is not None else None
        if parameter is None:
            return None
        key = value.strip().casefold()
        for option in parameter.options:
            keys = {str(option.value).casefold(), *(str(a).casefold() for a in option.aliases)}
            if key in keys:
                transport = option.transport
                return (
                    str(getattr(transport, "value", transport)) if transport is not None else None
                )
        return None

    def _profile_limit_query(
        self,
        alias: str,
        channel: int,
        query_type: str | None,
        *,
        label: str = "limit",
        query_token: str | None = None,
    ) -> tuple[str, str]:
        command = self._scpi_engine.build(alias, channel=channel)[0]
        if query_type is None:
            return command, ""
        semantic = str(getattr(query_type, "name", query_type))
        transport = query_token or self._profile_special_value(semantic)
        if transport is None:
            raise InstrumentParameterError(
                parameter="query_type",
                value=query_type,
                message="Query type is not declared by the profile.",
            )
        return f"{command} {transport}", f" ({semantic} {label})"

    def _native_bound_query_token(self, operation_id: str, query_type: str | None) -> str | None:
        """Resolve a getter's declared query selector through the loaded profile."""
        if query_type is None:
            return None
        options = getattr(self.config, "operation_options", None)
        spec = options.parameter(operation_id, "query_type") if options is not None else None
        if spec is None:
            raise InstrumentParameterError(
                parameter="query_type",
                value=query_type,
                message="This getter's profile does not declare query selectors.",
            )
        try:
            resolved = self._resolve_operation_parameter(operation_id, "query_type", query_type)
        except ValueError as exc:
            raise InstrumentParameterError(
                parameter="query_type",
                value=query_type,
                message="Query type is not declared by the getter's profile contract.",
            ) from exc
        token = getattr(resolved.transport_value, "value", resolved.transport_value)
        return str(token) if token is not None else None

    def _validate_native_numeric_setting(
        self, operation_id: str, parameter: str, channel: int, value: Any
    ) -> Any:
        """Check a numeric setter against this channel's current native limits."""
        if isinstance(value, str) and self._profile_special_value(value) is not None:
            return value
        try:
            numeric = float(value)
        except (TypeError, ValueError) as exc:
            raise InstrumentParameterError(
                parameter=parameter, value=value, message="Expected a numeric value."
            ) from exc
        if not math.isfinite(numeric):
            raise InstrumentParameterError(
                parameter=parameter, value=value, message="Value must be finite."
            )

        options = getattr(self.config, "operation_options", None)
        operation = options.operation(operation_id) if options is not None else None
        queries = getattr(operation, "context_queries", {}) if operation is not None else {}
        minimum_alias = queries.get("native_minimum")
        maximum_alias = queries.get("native_maximum")
        if not minimum_alias or not maximum_alias:
            return numeric

        bounds: dict[str, float] = {}
        for bound, alias in (("minimum", minimum_alias), ("maximum", maximum_alias)):
            query, _ = self._profile_limit_query(alias, channel, bound)
            response = self._query(query).strip()
            try:
                bound_value = float(response)
            except ValueError as exc:
                raise InstrumentCommunicationError(
                    instrument=self.config.model,
                    command=query,
                    message=f"Native {bound} response was not numeric: {response!r}",
                ) from exc
            if not math.isfinite(bound_value):
                raise InstrumentCommunicationError(
                    instrument=self.config.model,
                    command=query,
                    message=f"Native {bound} response was not finite: {response!r}",
                )
            bounds[bound] = bound_value
        low, high = bounds["minimum"], bounds["maximum"]
        if low > high:
            raise InstrumentCommunicationError(
                instrument=self.config.model,
                command=f"{minimum_alias}/{maximum_alias}",
                message=f"Native limits are inconsistent ({low} > {high}).",
            )
        if numeric < low or numeric > high:
            raise InstrumentParameterError(
                parameter=parameter,
                value=value,
                valid_range=(low, high),
                message="Value is outside the instrument's current native limits.",
            )
        if numeric == low:
            return "MINimum"
        if numeric == high:
            return "MAXimum"
        return numeric

    def _awg_native_contract(self, operation_id: str) -> dict[str, Any]:
        options = getattr(self.config, "operation_options", None)
        spec = options.parameter(operation_id, "function_type") if options is not None else None
        constraints = getattr(spec, "constraints", {}) if spec is not None else {}
        return constraints

    @staticmethod
    def _awg_numeric(value: Any) -> float | None:
        if isinstance(value, str):
            if value.strip().casefold() in {"minimum", "min", "maximum", "max", "default", "def"}:
                return None
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        return numeric if math.isfinite(numeric) else None

    @classmethod
    def _awg_value_at_native_bound(cls, value: Any, low: float, high: float) -> float | None:
        numeric = cls._awg_numeric(value)
        if numeric is not None:
            return numeric
        if isinstance(value, str):
            key = value.strip().casefold()
            if key in {"minimum", "min"}:
                return low
            if key in {"maximum", "max"}:
                return high
        return None

    def _awg_resolve_setting_for_budget(
        self,
        channel: int,
        getter: str,
        value: Any,
        *,
        function: str | None = None,
        unit: str | None = None,
        load: float | str | None = None,
    ) -> float | None:
        """Resolve a special setting to its live numeric value for joint validation."""
        numeric = self._awg_numeric(value)
        if getter == "get_amplitude":
            function = (function or self.get_function(channel)).casefold()
            unit = (unit or self.get_voltage_unit(channel)).upper()
            load = self.get_output_load_impedance(channel) if load is None else load
            function_contract = (
                self._awg_native_contract("set_function").get("functions", {}).get(function)
            )
            if isinstance(function_contract, dict):
                exact = self._awg_amplitude_limits(function_contract, unit, load)
                advertised = self._awg_compound_amplitude_endpoints(
                    channel, function, unit, load, function_contract, value
                ) or self._awg_advertised_amplitude_limits(function_contract, unit, load)
                if numeric is not None:
                    if exact is not None and advertised is not None:
                        if numeric == advertised[0]:
                            return exact[0]
                        if numeric == advertised[1]:
                            return exact[1]
                    return numeric
                if isinstance(value, str) and exact is not None:
                    key = value.strip().casefold()
                    if key in {"min", "minimum"}:
                        return exact[0]
                    if key in {"max", "maximum"}:
                        return exact[1]
        if numeric is not None:
            return numeric
        if not isinstance(value, str):
            return None
        key = value.strip().casefold()
        query_type = {
            "minimum": "minimum",
            "min": "minimum",
            "maximum": "maximum",
            "max": "maximum",
            "default": "default",
            "def": "default",
        }.get(key)
        if query_type == "default":
            defaults = self._awg_native_contract("set_function").get("defaults", {})
            if getter == "get_voltage_limit_high":
                value = defaults.get("voltage_limit_high_v")
                return float(value) if value is not None else None
            if getter == "get_voltage_limit_low":
                value = defaults.get("voltage_limit_low_v")
                return float(value) if value is not None else None
            if getter == "get_offset":
                return float(defaults.get("offset_v", 0.0))
            if getter == "get_frequency":
                return float(defaults.get("frequency_hz", 1000.0))
            if getter != "get_amplitude":
                return None
            function = (function or self.get_function(channel)).casefold()
            unit = (unit or self.get_voltage_unit(channel)).upper()
            load = self.get_output_load_impedance(channel) if load is None else load
            contract = self._awg_native_contract("set_function")
            try:
                source = float(contract["source_impedance_ohm"])
                default_vpp_50 = float(defaults["amplitude_vpp_at_50_ohm"])
            except (KeyError, TypeError, ValueError):
                return None
            if isinstance(load, str) and load.casefold() in {"infinity", "inf"}:
                load_factor = 2.0
            else:
                try:
                    impedance = float(load)
                    if not math.isfinite(impedance) or impedance <= 0:
                        return None
                    load_factor = 2.0 * impedance / (impedance + source)
                except (TypeError, ValueError):
                    return None
            default_vpp = default_vpp_50 * load_factor
            if unit == "VPP":
                return default_vpp
            if unit not in {"VRMS", "DBM"}:
                return None
            function_contract = contract.get("functions", {}).get(function, {})
            try:
                peak_factor = float(function_contract["rms_peak_factor"])
                rms = default_vpp / (2.0 * peak_factor)
            except (KeyError, TypeError, ValueError, ZeroDivisionError):
                return None
            if unit == "VRMS":
                return rms
            if isinstance(load, str):
                return None
            impedance = float(load)
            return 10.0 * math.log10((rms * rms) / (impedance * 0.001))
        if query_type is None or self._profile_special_value(query_type) is None:
            return None
        return float(getattr(self, getter)(channel, query_type=query_type))

    def _awg_load_key(self, load: float | str) -> str | None:
        if isinstance(load, str) and load.casefold() in {"infinity", "inf"}:
            return "infinity"
        try:
            value = float(load)
            if not math.isfinite(value) or value <= 0:
                return None
            if math.isclose(value, 50.0, rel_tol=0.0, abs_tol=1e-9):
                return "50"
            return str(value)
        except (TypeError, ValueError):
            return None

    def _awg_unit_load_requirement(self, unit: str) -> float | None:
        options = getattr(self.config, "operation_options", None)
        spec = options.parameter("set_voltage_unit", "unit") if options is not None else None
        if spec is None:
            return None
        for option in spec.options:
            if str(option.value).upper() == unit.upper():
                required = option.constraints.get("load_impedance")
                return float(required) if required is not None else None
        return None

    def _awg_unit_requires_finite_load(self, unit: str) -> bool:
        options = getattr(self.config, "operation_options", None)
        spec = options.parameter("set_voltage_unit", "unit") if options is not None else None
        if spec is None:
            return False
        return any(
            str(option.value).upper() == unit.upper()
            and bool(option.constraints.get("requires_finite_load"))
            for option in spec.options
        )

    def _awg_load_matches(self, channel: int, required: float) -> bool:
        load = self.get_output_load_impedance(channel)
        if isinstance(load, str) and load.casefold() in {"infinity", "inf"}:
            return False
        try:
            return math.isclose(float(load), required, rel_tol=0.0, abs_tol=1e-9)
        except (TypeError, ValueError):
            return False

    def _awg_load_is_finite_positive(self, channel: int) -> bool:
        load = self.get_output_load_impedance(channel)
        try:
            value = float(load)
            return math.isfinite(value) and value > 0
        except (TypeError, ValueError):
            return False

    def _awg_load_peak_limit(self, load: float | str, contract: dict[str, Any]) -> float | None:
        contexts = contract.get("load_contexts", {})
        if isinstance(load, str) and load.casefold() in {"infinity", "inf"}:
            value = contexts.get("infinity", {}).get("output_peak_v")
            return float(value) if value is not None else None
        try:
            impedance = float(load)
            source = float(contract["source_impedance_ohm"])
            maximum_vpp = float(contract["max_output_vpp_infinity"])
        except (KeyError, TypeError, ValueError):
            return None
        if not math.isfinite(impedance) or impedance <= 0 or source <= 0:
            return None
        return maximum_vpp * impedance / (impedance + source) / 2.0

    def _awg_amplitude_limits(
        self, function_contract: dict[str, Any], unit: str, load: float | str
    ) -> tuple[float, float] | None:
        unit_contract = function_contract.get("units", {}).get(unit)
        if not isinstance(unit_contract, dict):
            return None
        vpp = function_contract.get("units", {}).get("VPP", {})
        if not isinstance(vpp, dict):
            return None
        if isinstance(load, str) and load.casefold() in {"infinity", "inf"}:
            load_key = "infinity"
            vpp_scale = 1.0
        else:
            try:
                impedance = float(load)
                source = float(self._awg_native_contract("set_function")["source_impedance_ohm"])
                if not math.isfinite(impedance) or impedance <= 0 or source <= 0:
                    return None
                vpp_scale = 2.0 * impedance / (impedance + source)
                load_key = "50"
            except (KeyError, TypeError, ValueError):
                return None
        min_vpp = vpp.get(f"min_{load_key}")
        if min_vpp is None:
            return None
        if load_key == "infinity":
            max_vpp = float(self._awg_native_contract("set_function")["max_output_vpp_infinity"])
            min_vpp = float(min_vpp)
        else:
            max_vpp = (
                float(self._awg_native_contract("set_function")["max_output_vpp_infinity"])
                * float(load)
                / (
                    float(load)
                    + float(self._awg_native_contract("set_function")["source_impedance_ohm"])
                )
            )
            min_vpp = float(min_vpp) * vpp_scale
        if unit == "VPP":
            return float(min_vpp), float(max_vpp)
        peak_factor = float(
            function_contract.get(
                f"rms_peak_factor_{load_key}", function_contract.get("rms_peak_factor", 1.0)
            )
        )
        if peak_factor <= 0 or not math.isfinite(peak_factor):
            return None
        rms_low, rms_high = (
            float(min_vpp) / (2.0 * peak_factor),
            float(max_vpp) / (2.0 * peak_factor),
        )
        if unit == "VRMS":
            return rms_low, rms_high
        if unit == "DBM":
            if isinstance(load, str):
                return None
            load_ohms = float(load)
            if load_ohms <= 0 or not math.isfinite(load_ohms):
                return None
            return (
                10.0 * math.log10((rms_low * rms_low) / (load_ohms * 0.001)),
                10.0 * math.log10((rms_high * rms_high) / (load_ohms * 0.001)),
            )
        return None

    def _awg_advertised_amplitude_limits(
        self, function_contract: dict[str, Any], unit: str, load: float | str
    ) -> tuple[float, float] | None:
        """Return profile-recorded rounded values used by native MIN/MAX readback."""
        unit_contract = function_contract.get("units", {}).get(unit)
        if not isinstance(unit_contract, dict):
            return None
        if isinstance(load, str) and load.casefold() in {"infinity", "inf"}:
            key, factor = "infinity", 1.0
        else:
            try:
                impedance = float(load)
                source = float(self._awg_native_contract("set_function")["source_impedance_ohm"])
                if not math.isfinite(impedance) or impedance <= 0:
                    return None
                key = "50"
                factor = 2.0 * impedance / (impedance + source)
            except (KeyError, TypeError, ValueError):
                return None
        low = unit_contract.get(f"min_{key}", unit_contract.get("min"))
        high = unit_contract.get(f"max_{key}", unit_contract.get("max"))
        if low is None or high is None:
            return None
        low, high = float(low), float(high)
        if unit == "DBM":
            if isinstance(load, str):
                return None
            shift = 10.0 * math.log10((factor * factor * 50.0) / float(load))
            return low + shift, high + shift
        return low * factor, high * factor

    def _awg_normalize_amplitude_endpoint(
        self, channel: int, function: str, unit: str, load: float | str, value: Any
    ) -> Any:
        """Use the instrument's native endpoint token for rounded endpoint values."""
        numeric = self._awg_numeric(value)
        contract = (
            self._awg_native_contract("set_function").get("functions", {}).get(function.casefold())
        )
        if numeric is None or not isinstance(contract, dict):
            return value
        advertised = self._awg_compound_amplitude_endpoints(
            channel, function, unit, load, contract, value
        ) or self._awg_advertised_amplitude_limits(contract, unit.upper(), load)
        if advertised is not None:
            if numeric == advertised[0]:
                return "MINimum"
            if numeric == advertised[1]:
                return "MAXimum"
        return value

    def _awg_is_native_max_amplitude(
        self,
        value: Any,
        function_contract: dict[str, Any],
        unit: str,
        load: float | str,
        advertised: tuple[float, float] | None = None,
    ) -> bool:
        if isinstance(value, str) and value.strip().casefold() in {"max", "maximum"}:
            return True
        numeric = self._awg_numeric(value)
        advertised = advertised or self._awg_advertised_amplitude_limits(
            function_contract, unit, load
        )
        return numeric is not None and advertised is not None and numeric == advertised[1]

    def _awg_compound_amplitude_endpoints(
        self,
        channel: int,
        function: str,
        unit: str,
        load: float | str,
        function_contract: dict[str, Any],
        value: Any,
    ) -> tuple[float, float] | None:
        """Use live native endpoints only when the compound call keeps current context."""
        exact = self._awg_amplitude_limits(function_contract, unit, load)
        profile = self._awg_advertised_amplitude_limits(function_contract, unit, load)
        numeric = self._awg_numeric(value)
        special = isinstance(value, str) and value.strip().casefold() in {
            "min",
            "minimum",
            "max",
            "maximum",
        }
        table_endpoint_differs = (
            numeric is not None
            and exact is not None
            and profile is not None
            and profile != exact
            and numeric in profile
        )
        needs_live = (
            special
            or table_endpoint_differs
            or (
                numeric is not None
                and exact is not None
                and (numeric < exact[0] or numeric > exact[1])
            )
        )
        if not needs_live:
            return None
        if self.get_function(channel).casefold() != function.casefold():
            return None
        if self.get_voltage_unit(channel).upper() != unit.upper():
            return None
        try:
            minimum = self.get_amplitude(channel, query_type="minimum")
            maximum = self.get_amplitude(channel, query_type="maximum")
        except InstrumentParameterError:
            return None
        if math.isfinite(minimum) and math.isfinite(maximum) and minimum <= maximum:
            return minimum, maximum
        return None

    def _validate_direct_peak_budget(
        self, channel: int, *, amplitude: Any = None, offset: Any = None
    ) -> None:
        """Validate direct amplitude/offset updates against the current channel state."""
        contract = self._awg_native_contract("set_function")
        function = self.get_function(channel).casefold()
        function_contract = contract.get("functions", {}).get(function)
        if not isinstance(function_contract, dict):
            # Arbitrary waveform peak/RMS readback is not exposed by this profile.
            return
        load = self.get_output_load_impedance(channel)
        peak_limit = self._awg_load_peak_limit(load, contract)
        unit = self.get_voltage_unit(channel).upper()
        if self._awg_unit_requires_finite_load(unit) and (
            isinstance(load, str) or not math.isfinite(float(load)) or float(load) <= 0
        ):
            raise InstrumentParameterError(
                parameter="unit",
                value=unit,
                message="dBm requires a finite positive load impedance.",
            )
        bounds = self._awg_amplitude_limits(function_contract, unit, load)
        amplitude_was_requested = amplitude is not None
        requested_amplitude, requested_offset = amplitude, offset
        if amplitude is None:
            amplitude = self.get_amplitude(channel)
        advertised_amplitude = self._awg_compound_amplitude_endpoints(
            channel, function, unit, load, function_contract, amplitude
        ) or self._awg_advertised_amplitude_limits(function_contract, unit, load)
        if offset is None:
            offset = self.get_offset(channel)
        if bounds is None:
            return
        numeric_amplitude = self._awg_resolve_setting_for_budget(
            channel, "get_amplitude", amplitude, function=function, unit=unit, load=load
        )
        numeric_offset = self._awg_resolve_setting_for_budget(channel, "get_offset", offset)
        if numeric_amplitude is not None and not bounds[0] <= numeric_amplitude <= bounds[1]:
            raise InstrumentParameterError(
                parameter="amplitude",
                value=amplitude,
                valid_range=bounds,
                message="Amplitude exceeds the exact native amplitude envelope.",
            )
        excursion = (
            self._awg_amplitude_peak(
                channel, numeric_amplitude, function, unit, self._awg_load_key(load)
            )
            if numeric_amplitude is not None
            else None
        )
        if (
            excursion is not None
            and peak_limit is not None
            and function != "dc"
            and self._awg_is_native_max_amplitude(
                amplitude, function_contract, unit, load, advertised_amplitude
            )
        ):
            excursion = peak_limit
        if excursion is None or numeric_offset is None:
            return
        self._validate_enabled_protection_extents(
            channel, (numeric_offset - excursion, numeric_offset + excursion)
        )
        if peak_limit is not None and abs(numeric_offset) + excursion > peak_limit:
            raise InstrumentParameterError(
                parameter="amplitude" if amplitude_was_requested else "offset",
                value=requested_amplitude if amplitude_was_requested else requested_offset,
                message="Offset and waveform amplitude exceed the profile's output peak budget.",
            )

    def _validate_enabled_protection_extents(
        self, channel: int, extents: tuple[float, float]
    ) -> None:
        """Reject a target signal excluded by the channel's enabled native limits."""
        if not self.get_voltage_limits_state(channel):
            return
        low = self.get_voltage_limit_low(channel)
        high = self.get_voltage_limit_high(channel)
        if extents[0] < low or extents[1] > high:
            raise InstrumentParameterError(
                parameter="voltage_limits",
                value=extents,
                valid_range=(low, high),
                message="Enabled voltage limits exclude the requested output waveform.",
            )

    def _awg_active_output_extents(self, channel: int) -> tuple[float, float] | None:
        """Return the profile-supported current signal's minimum and maximum volts."""
        function = self.get_function(channel).casefold()
        function_contract = (
            self._awg_native_contract("set_function").get("functions", {}).get(function)
        )
        if not isinstance(function_contract, dict):
            return None
        unit = self.get_voltage_unit(channel).upper()
        load = self.get_output_load_impedance(channel)
        bounds = self._awg_amplitude_limits(function_contract, unit, load)
        if bounds is None:
            return None
        raw_amplitude = self.get_amplitude(channel)
        advertised_amplitude = self._awg_compound_amplitude_endpoints(
            channel, function, unit, load, function_contract, raw_amplitude
        ) or self._awg_advertised_amplitude_limits(function_contract, unit, load)
        amplitude = self._awg_resolve_setting_for_budget(
            channel,
            "get_amplitude",
            raw_amplitude,
            function=function,
            unit=unit,
            load=load,
        )
        offset = self.get_offset(channel)
        if amplitude is None:
            return None
        if amplitude < bounds[0] or amplitude > bounds[1]:
            raise InstrumentParameterError(
                parameter="amplitude",
                value=amplitude,
                valid_range=bounds,
                message="Current amplitude is outside the native profile envelope.",
            )
        peak = self._awg_amplitude_peak(
            channel, amplitude, function, unit, self._awg_load_key(load)
        )
        if peak is None:
            return None
        peak_limit = self._awg_load_peak_limit(load, self._awg_native_contract("set_function"))
        if (
            peak_limit is not None
            and function != "dc"
            and self._awg_is_native_max_amplitude(
                raw_amplitude, function_contract, unit, load, advertised_amplitude
            )
        ):
            peak = peak_limit
        return offset - peak, offset + peak

    def _awg_voltage_limit_default(self, getter: str) -> float | None:
        defaults = self._awg_native_contract("set_function").get("defaults", {})
        key = (
            "voltage_limit_high_v" if getter == "get_voltage_limit_high" else "voltage_limit_low_v"
        )
        value = defaults.get(key)
        return float(value) if value is not None else None

    def _validate_voltage_limit_candidate(self, channel: int, which: str, value: Any) -> None:
        setter = f"set_voltage_limit_{which}"
        getter = f"get_voltage_limit_{which}"
        candidate = self._awg_resolve_setting_for_budget(channel, getter, value)
        if candidate is None:
            raise InstrumentParameterError(
                parameter="voltage",
                value=value,
                message="Could not resolve this voltage-limit setting for preflight.",
            )
        self._validate_native_numeric_setting(setter, "voltage", channel, candidate)
        other_getter = "get_voltage_limit_low" if which == "high" else "get_voltage_limit_high"
        other = self._awg_resolve_setting_for_budget(
            channel, other_getter, getattr(self, other_getter)(channel)
        )
        low, high = (other, candidate) if which == "high" else (candidate, other)
        if low is not None and high is not None and low > high:
            raise InstrumentParameterError(
                parameter="voltage",
                value=value,
                valid_range=(low, high),
                message="Low voltage limit must not exceed high voltage limit.",
            )
        if self.get_voltage_limits_state(channel):
            extents = self._awg_active_output_extents(channel)
            if extents is not None:
                if which == "high" and candidate < extents[1]:
                    raise InstrumentParameterError(
                        parameter="voltage",
                        value=value,
                        valid_range=(extents[1], high),
                        message="Enabled voltage limits must include the current output peak.",
                    )
                if which == "low" and candidate > extents[0]:
                    raise InstrumentParameterError(
                        parameter="voltage",
                        value=value,
                        valid_range=(low, extents[0]),
                        message="Enabled voltage limits must include the current output peak.",
                    )

    def _awg_amplitude_peak(
        self, channel: int, amplitude: float, function: str, unit: str, load_key: str | None
    ) -> float | None:
        """Convert a profile-supported amplitude into its peak excursion in volts."""
        function = function.casefold()
        unit = unit.upper()
        if function == "dc":
            return 0.0
        if unit == "VPP":
            return abs(amplitude) / 2.0
        contract = self._awg_native_contract("set_function")["functions"].get(function)
        if not isinstance(contract, dict):
            return None
        factor = contract.get(f"rms_peak_factor_{load_key}", contract.get("rms_peak_factor"))
        try:
            factor = float(factor)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(factor) or factor <= 0:
            return None
        if unit == "VRMS":
            return abs(amplitude) * factor
        if unit == "DBM":
            load = self.get_output_load_impedance(channel)
            try:
                load_ohms = float(load)
                rms_volts = math.sqrt(load_ohms * 0.001 * (10.0 ** (amplitude / 10.0)))
            except (TypeError, ValueError, OverflowError):
                return None
            return rms_volts * factor
        return None

    def _validate_compound_settings(
        self,
        channel: int,
        operation_id: str,
        function_type: str,
        settings: dict[str, Any],
        *,
        amplitude_unit: str | None = None,
    ) -> float | None:
        """Preflight target waveform settings against profile limits and peak budget."""
        contract = self._awg_native_contract(operation_id)
        functions = contract.get("functions")
        if not isinstance(functions, dict):
            return None
        function = function_type.casefold()
        function_contract = functions.get(function)
        if not isinstance(function_contract, dict):
            # Do not invent limits for profile functions without an envelope.
            return None

        raw_frequency = settings.get("frequency")
        if raw_frequency is None and operation_id == "set_function":
            raw_frequency = self.get_frequency(channel)
        if raw_frequency is not None:
            low = float(contract["frequency_min"])
            high = float(function_contract["frequency_max"])
            frequency = self._awg_value_at_native_bound(raw_frequency, low, high)
            if frequency is not None:
                if frequency < low or frequency > high:
                    raise InstrumentParameterError(
                        parameter="frequency",
                        value=raw_frequency,
                        valid_range=(low, high),
                        message=f"Frequency is outside the native range for {function_type}.",
                    )

        load = self.get_output_load_impedance(channel)
        load_key = self._awg_load_key(load)
        unit = (amplitude_unit or self.get_voltage_unit(channel)).upper()
        units = function_contract.get("units", {})
        unit_contract = units.get(unit) if isinstance(units, dict) else None
        if not isinstance(unit_contract, dict):
            raise InstrumentParameterError(
                parameter="unit",
                value=unit,
                message=f"Profile does not support {unit} amplitude for waveform {function_type}.",
            )
        required_load = unit_contract.get("load")
        if unit_contract.get("requires_finite_load") and (
            isinstance(load, str) or not math.isfinite(float(load)) or float(load) <= 0
        ):
            raise InstrumentParameterError(
                parameter="unit",
                value=unit,
                message=f"A finite positive load impedance is required for {unit} operation.",
            )
        if required_load is not None and not self._awg_load_matches(channel, float(required_load)):
            raise InstrumentParameterError(
                parameter="unit",
                value=unit,
                message=f"The profile requires a {required_load} ohm load for {unit} operation.",
            )

        amp_key = "amplitude"
        raw_amplitude = settings.get(amp_key)
        if raw_amplitude is None:
            raw_amplitude = self.get_amplitude(channel)
        amplitude_bounds = self._awg_amplitude_limits(function_contract, unit, load)
        amplitude_low, amplitude_high = amplitude_bounds or (None, None)
        advertised_bounds = self._awg_compound_amplitude_endpoints(
            channel, function, unit, load, function_contract, raw_amplitude
        ) or self._awg_advertised_amplitude_limits(function_contract, unit, load)
        if isinstance(raw_amplitude, str) and raw_amplitude.strip().casefold() in {
            "def",
            "default",
        }:
            amplitude = self._awg_resolve_setting_for_budget(
                channel,
                "get_amplitude",
                raw_amplitude,
                function=function,
                unit=unit,
                load=load,
            )
        else:
            numeric_amplitude = self._awg_numeric(raw_amplitude)
            if (
                numeric_amplitude is not None
                and amplitude_bounds is not None
                and advertised_bounds is not None
                and numeric_amplitude == advertised_bounds[0]
            ):
                amplitude = amplitude_bounds[0]
            elif (
                numeric_amplitude is not None
                and amplitude_bounds is not None
                and advertised_bounds is not None
                and numeric_amplitude == advertised_bounds[1]
            ):
                amplitude = amplitude_bounds[1]
            else:
                amplitude = (
                    self._awg_value_at_native_bound(raw_amplitude, amplitude_low, amplitude_high)
                    if amplitude_low is not None and amplitude_high is not None
                    else numeric_amplitude
                )
        if amplitude is not None and amplitude_low is not None and amplitude_high is not None:
            if amplitude < amplitude_low or amplitude > amplitude_high:
                raise InstrumentParameterError(
                    parameter="amplitude",
                    value=raw_amplitude,
                    valid_range=(amplitude_low, amplitude_high),
                    message=f"Amplitude is outside the native {unit} range for {function_type}.",
                )

        raw_offset = settings.get("offset")
        if raw_offset is None:
            raw_offset = self.get_offset(channel)
        offset = (
            self._awg_resolve_setting_for_budget(
                channel, "get_offset", raw_offset, function=function, unit=unit, load=load
            )
            if isinstance(raw_offset, str) and raw_offset.strip().casefold() in {"def", "default"}
            else self._awg_numeric(raw_offset)
        )
        resolved_joint_offset: float | None = None
        peak_limit = self._awg_load_peak_limit(load, contract)
        excursion = (
            self._awg_amplitude_peak(channel, amplitude, function, unit, load_key)
            if amplitude is not None
            else None
        )
        if (
            excursion is not None
            and peak_limit is not None
            and function != "dc"
            and self._awg_is_native_max_amplitude(
                raw_amplitude, function_contract, unit, load, advertised_bounds
            )
        ):
            excursion = peak_limit
        if peak_limit is not None and isinstance(raw_offset, str) and excursion is not None:
            offset_bound = peak_limit - excursion
            offset = self._awg_value_at_native_bound(raw_offset, -offset_bound, offset_bound)
            if raw_offset.strip().casefold() in {"min", "minimum", "max", "maximum"}:
                resolved_joint_offset = offset
        if (
            peak_limit is not None
            and offset is not None
            and excursion is not None
            and abs(offset) + excursion > peak_limit
        ):
            raise InstrumentParameterError(
                parameter="offset",
                value=raw_offset,
                valid_range=(-peak_limit + excursion, peak_limit - excursion),
                message="Offset and waveform amplitude exceed the profile's output peak budget.",
            )
        if offset is not None:
            if excursion is not None:
                self._validate_enabled_protection_extents(
                    channel, (offset - excursion, offset + excursion)
                )
        return resolved_joint_offset

    def _send_resolved_operation(self, operation_id: str, arguments: dict[str, Any]) -> None:
        resolved = self._resolve_operation_arguments(operation_id, arguments)
        for alias, parameters in resolved.items():
            self._send_profile_alias(alias, **parameters)

    def __init__(
        self, config: WaveformGeneratorConfig, debug_mode: bool = False, **kwargs: Any
    ) -> None:
        """
        Initializes the WaveformGenerator instance.
        """
        super().__init__(config=config, debug_mode=debug_mode, **kwargs)  # Pass kwargs to base
        # self.config is already set by base Instrument's __init__ due to Generic type

        # Determine channel count from the length of the channels list in the config
        if hasattr(self.config, "channels") and isinstance(self.config.channels, list):
            self._channel_count = len(self.config.channels)
        else:
            # This case should ideally be caught by Pydantic validation of WaveformGeneratorConfig
            self._logger.warning("config.channels is not a list. Defaulting channel count to 0.")
            self._channel_count = 0

        if self._channel_count <= 0:
            self._logger.warning(
                f"Channel count determined as {self._channel_count}. Check instrument configuration."
            )
            # Consider if raising an error is more appropriate if channel_count is essential and expected to be > 0
            # For now, logging a warning to allow flexibility if some AWGs might be configured with 0 channels initially.

        self._logger.debug(f"Detected {self._channel_count} channels from configuration.")

    def _log(self, message: str, level: str = "debug") -> None:
        """
        Helper method for logging messages at different levels.

        Args:
            message: The message to log
            level: The logging level ('debug', 'info', 'warning', 'error')
        """
        level_lower = level.lower()
        if level_lower == "debug":
            self._logger.debug(message)
        elif level_lower == "info":
            self._logger.info(message)
        elif level_lower == "warning":
            self._logger.warning(message)
        elif level_lower == "error":
            self._logger.error(message)
        else:
            self._logger.debug(message)  # fallback to debug

    @property
    def channel_count(self) -> int:
        """
        Returns the number of output channels supported by this instrument, based on configuration.
        """
        return self._channel_count

    def _write_binary(self, cmd_prefix: str, data: bytes) -> None:
        """
        Internal helper to transmit a SCPI definite-length binary block.

        This formats a definite-length binary block (#<N><len><data>) and sends
        it following the provided command prefix.

        Backends with richer binary-transfer support can override or extend this.
        """
        n = len(data)
        header = f"#{len(str(n))}{n}".encode("ascii")
        block = header + data

        # Some instruments accept the block appended directly after the command.
        # Use latin1 to preserve byte values in a Python str.
        payload_str = block.decode("latin1")
        self._send_command(f"{cmd_prefix}{payload_str}")

    @classmethod
    def from_config(
        cls: type[Self],
        config: InstrumentConfig,
        debug_mode: bool = False,
        **kwargs: Any,
    ) -> Self:
        """Build a waveform generator driver from an instrument configuration."""
        if not isinstance(config, WaveformGeneratorConfig):
            raise InstrumentConfigurationError(
                cls.__name__, "from_config expects a WaveformGeneratorConfig object."
            )
        return cls(config=config, debug_mode=debug_mode, **kwargs)

    def _validate_channel(self, channel: int | str) -> int:
        """
        Validates the provided channel identifier and returns the integer channel number (1-based).
        """
        ch_num: int
        if isinstance(channel, str):
            ch_str = channel.strip().upper()
            if ch_str.startswith("CH"):
                match = re.match(r"CH(?:ANNEL)?(\d+)", ch_str)
                if match:
                    try:
                        ch_num = int(match.group(1))
                    except ValueError as e:
                        raise InstrumentParameterError(
                            parameter="channel",
                            value=channel,
                            message="Could not parse channel number from string.",
                        ) from e
                else:
                    raise InstrumentParameterError(
                        parameter="channel",
                        value=channel,
                        message="Invalid channel string format. Use integer, 'CHx', or 'CHANNELx'.",
                    )
            else:
                try:
                    ch_num = int(channel)
                except ValueError as e:
                    raise InstrumentParameterError(
                        parameter="channel",
                        value=channel,
                        message="Invalid channel string format. Use integer, 'CHx', or 'CHANNELx'.",
                    ) from e
        elif isinstance(channel, int):
            ch_num = channel
        else:
            raise InstrumentParameterError(
                parameter="channel",
                value=channel,
                message=f"Invalid channel type: {type(channel)}. Expected int or str.",
            )

        # Validate against the number of channels defined in the config
        # self.config.channels is List[AWGChannelConfig]
        if not (
            1 <= ch_num <= self.channel_count
        ):  # Use self.channel_count which is derived from len(self.config.channels)
            raise InstrumentParameterError(
                parameter="channel",
                value=ch_num,
                valid_range=(1, self.channel_count),
                message="Channel number is out of range.",
            )
        return ch_num

    def _format_value_min_max_def(self, value: float | int | str) -> str:
        """Format numeric values or profile-declared semantic special values."""

        value = getattr(value, "value", value)

        if isinstance(value, str):
            val_upper = value.upper().strip()

            special = self._profile_special_value(val_upper)
            if special is not None:
                return special

            try:
                num_val = float(value)
            except ValueError as e:  # noqa: B904 (re-raise with context not needed here)
                raise InstrumentParameterError(
                    parameter="value",
                    value=value,
                    message=(
                        "Invalid parameter string. Expected a number or a "
                        "profile-declared special value."
                    ),
                ) from e
            return f"{num_val:.12G}"

        if isinstance(value, int | float):
            return f"{float(value):.12G}"

        raise InstrumentParameterError(
            parameter="value",
            value=value,
            message=f"Invalid parameter type: {type(value)}. Expected a number or string.",
        )

    def _build_function_commands(
        self,
        channel: int | str,
        function_type: str,
        shape_settings: dict[str, dict[str, Any]],
        standard_settings: dict[str, Any] | None = None,
        *,
        phase: float | None = None,
        amplitude_unit: str | None = None,
    ) -> list[str]:
        """Validate and build a complete function change without I/O."""
        ch = self._validate_channel(channel)
        args = {"channel": ch, "function_type": function_type}
        args.update(standard_settings or {})
        resolved = self._resolve_operation_arguments("set_function", args)
        semantic_function = self._resolve_operation_parameter(
            "set_function", "function_type", function_type
        ).value
        validation_settings = dict(standard_settings or {})
        pulse_period = shape_settings.get("set_pulse_period", {}).get("period")
        if str(semantic_function).casefold() == "pulse" and pulse_period is not None:
            if pulse_period <= 0:
                raise InstrumentParameterError(
                    parameter="period", value=pulse_period, message="Time must be positive."
                )
            validation_settings["frequency"] = 1.0 / pulse_period
        joint_offset = self._validate_compound_settings(
            ch,
            "set_function",
            str(semantic_function),
            validation_settings,
            amplitude_unit=amplitude_unit,
        )
        if joint_offset is not None and "set_offset" in resolved:
            resolved["set_offset"]["offset"] = joint_offset
        function = str(resolved["set_function"]["function"])
        function_commands = self._scpi_engine.build("set_function", channel=ch, function=function)
        aliases = (
            ("set_frequency", "set_offset", "set_amplitude")
            if amplitude_unit is not None
            else ("set_frequency", "set_amplitude", "set_offset")
        )
        setting_commands: dict[str, list[str]] = {}
        current_load = self.get_output_load_impedance(ch) if "set_amplitude" in resolved else None
        for alias in aliases:
            if alias in resolved:
                alias_commands: list[str] = []
                if alias == "set_amplitude" and amplitude_unit is not None:
                    alias_commands.extend(
                        self._scpi_engine.build("set_voltage_unit", channel=ch, unit=amplitude_unit)
                    )
                alias_arguments = dict(resolved[alias])
                if alias == "set_amplitude":
                    unit_for_command = (amplitude_unit or self.get_voltage_unit(ch)).upper()
                    alias_arguments["amplitude"] = self._awg_normalize_amplitude_endpoint(
                        ch,
                        str(semantic_function),
                        unit_for_command,
                        current_load
                        if current_load is not None
                        else self.get_output_load_impedance(ch),
                        alias_arguments["amplitude"],
                    )
                alias_commands.extend(self._scpi_engine.build(alias, channel=ch, **alias_arguments))
                setting_commands[alias] = alias_commands
        pre_function_commands: list[str] = []
        native_functions = self._awg_native_contract("set_function").get("functions", {})
        target_contract = native_functions.get(str(semantic_function).casefold(), {})
        old_contract: dict[str, Any] = {}
        old_function = ""
        current_frequency: float | None = None
        target_frequency = validation_settings.get("frequency")
        if isinstance(target_contract, dict) and "frequency_max" in target_contract:
            old_function = str(self.get_function(ch)).casefold()
            old_contract = native_functions.get(old_function, {})
            current_frequency = self.get_frequency(ch)
        target_frequency_numeric = self._awg_numeric(target_frequency)
        if target_frequency_numeric is None and isinstance(target_contract, dict):
            target_frequency_numeric = self._awg_value_at_native_bound(
                target_frequency,
                float(self._awg_native_contract("set_function").get("frequency_min", 0.0)),
                float(target_contract.get("frequency_max", math.inf)),
            )
        target_frequency_max = float(target_contract.get("frequency_max", math.inf))
        if current_frequency is not None and current_frequency > target_frequency_max:
            if target_frequency_numeric is None:
                raise InstrumentParameterError(
                    parameter="frequency",
                    value=target_frequency,
                    valid_range=(
                        float(self._awg_native_contract("set_function")["frequency_min"]),
                        target_frequency_max,
                    ),
                    message="Current frequency exceeds the target waveform range; provide a valid frequency.",
                )
            old_frequency_max = float(old_contract.get("frequency_max", math.inf))
            if target_frequency_numeric <= old_frequency_max:
                setting_commands.pop("set_frequency", None)
                pre_function_commands.extend(
                    self._scpi_engine.build(
                        "set_frequency", channel=ch, frequency=target_frequency_numeric
                    )
                )
            else:
                bridge_frequency = min(old_frequency_max, target_frequency_max)
                if not math.isfinite(bridge_frequency):
                    raise InstrumentParameterError(
                        parameter="frequency",
                        value=target_frequency,
                        message="No shared native frequency is available for a safe waveform transition.",
                    )
                pre_function_commands.extend(
                    self._scpi_engine.build("set_frequency", channel=ch, frequency=bridge_frequency)
                )

        if (
            "set_amplitude" in setting_commands
            and isinstance(target_contract, dict)
            and isinstance(old_contract, dict)
        ):
            if current_load is None:
                current_load = self.get_output_load_impedance(ch)
            current_unit = self.get_voltage_unit(ch).upper()
            current_amplitude = self.get_amplitude(ch)
            target_amp_raw = standard_settings.get("amplitude") if standard_settings else None
            target_unit = (amplitude_unit or current_unit).upper()
            target_bounds = self._awg_amplitude_limits(target_contract, target_unit, current_load)
            target_transition_bounds = self._awg_amplitude_limits(
                target_contract, current_unit, current_load
            )
            old_bounds = self._awg_amplitude_limits(old_contract, current_unit, current_load)
            current_advertised_bounds = self._awg_compound_amplitude_endpoints(
                ch,
                str(semantic_function),
                current_unit,
                current_load,
                target_contract,
                current_amplitude,
            ) or self._awg_advertised_amplitude_limits(target_contract, current_unit, current_load)
            if (
                target_transition_bounds is not None
                and current_advertised_bounds is not None
                and current_amplitude == current_advertised_bounds[1]
            ):
                current_amplitude = target_transition_bounds[1]
            target_advertised_bounds = self._awg_compound_amplitude_endpoints(
                ch,
                str(semantic_function),
                target_unit,
                current_load,
                target_contract,
                target_amp_raw,
            ) or self._awg_advertised_amplitude_limits(target_contract, target_unit, current_load)
            raw_target_numeric = self._awg_numeric(target_amp_raw)
            if (
                target_bounds is not None
                and target_advertised_bounds is not None
                and raw_target_numeric == target_advertised_bounds[1]
            ):
                target_amp = target_bounds[1]
            elif target_bounds is not None:
                target_amp = self._awg_value_at_native_bound(target_amp_raw, *target_bounds)
            else:
                target_amp = raw_target_numeric
            target_transition_contains_current = (
                target_transition_bounds is not None
                and target_transition_bounds[0] <= current_amplitude <= target_transition_bounds[1]
            )
            if (
                target_bounds is not None
                and target_transition_bounds is not None
                and old_bounds is not None
                and target_amp is not None
                and not target_transition_contains_current
            ):
                if amplitude_unit is None:
                    bridge_amplitude = target_amp
                    if not old_bounds[0] <= bridge_amplitude <= old_bounds[1]:
                        raise InstrumentParameterError(
                            parameter="amplitude",
                            value=target_amp_raw,
                            valid_range=old_bounds,
                            message="No valid amplitude bridge is available for the waveform transition.",
                        )
                    self._validate_direct_peak_budget(ch, amplitude=bridge_amplitude)
                    pre_function_commands.extend(
                        self._scpi_engine.build(
                            "set_amplitude", channel=ch, amplitude=bridge_amplitude
                        )
                    )
                    setting_commands.pop("set_amplitude", None)
                else:
                    bridge_low = max(old_bounds[0], target_transition_bounds[0])
                    bridge_high = min(old_bounds[1], target_transition_bounds[1])
                    if bridge_low > bridge_high:
                        raise InstrumentParameterError(
                            parameter="amplitude",
                            value=target_amp_raw,
                            valid_range=(bridge_low, bridge_high),
                            message="No common native amplitude is available for the waveform transition.",
                        )
                    bridge_amplitude = min(max(target_amp, bridge_low), bridge_high)
                    self._validate_direct_peak_budget(ch, amplitude=bridge_amplitude)
                    pre_function_commands.extend(
                        self._scpi_engine.build(
                            "set_amplitude", channel=ch, amplitude=bridge_amplitude
                        )
                    )

        if (
            amplitude_unit is None
            and "set_amplitude" in setting_commands
            and "set_offset" in setting_commands
            and isinstance(target_contract, dict)
        ):
            if current_load is None:
                current_load = self.get_output_load_impedance(ch)
            current_unit = self.get_voltage_unit(ch).upper()
            current_amplitude = self.get_amplitude(ch)
            current_offset = self.get_offset(ch)
            target_amplitude = self._awg_resolve_setting_for_budget(
                ch,
                "get_amplitude",
                validation_settings.get("amplitude", current_amplitude),
                function=str(semantic_function),
                unit=current_unit,
                load=current_load,
            )
            target_offset = self._awg_resolve_setting_for_budget(
                ch, "get_offset", validation_settings.get("offset", current_offset)
            )
            factor_key = self._awg_load_key(current_load)
            peak_limit = self._awg_load_peak_limit(
                current_load, self._awg_native_contract("set_function")
            )
            if (
                target_amplitude is not None
                and target_offset is not None
                and peak_limit is not None
            ):
                old_peak = self._awg_amplitude_peak(
                    ch, current_amplitude, str(semantic_function), current_unit, factor_key
                )
                new_peak = self._awg_amplitude_peak(
                    ch, target_amplitude, str(semantic_function), current_unit, factor_key
                )
                if old_peak is not None and new_peak is not None:
                    protection_bounds = None
                    if self.get_voltage_limits_state(ch):
                        protection_bounds = (
                            self.get_voltage_limit_low(ch),
                            self.get_voltage_limit_high(ch),
                        )

                    def within_transition_limits(offset_value: float, peak_value: float) -> bool:
                        if abs(offset_value) + peak_value > peak_limit:
                            return False
                        if protection_bounds is None:
                            return True
                        low_limit, high_limit = protection_bounds
                        return (
                            offset_value - peak_value >= low_limit
                            and offset_value + peak_value <= high_limit
                        )

                    amplitude_first_safe = within_transition_limits(current_offset, new_peak)
                    offset_first_safe = within_transition_limits(target_offset, old_peak)
                    if not amplitude_first_safe and offset_first_safe:
                        aliases = ("set_frequency", "set_offset", "set_amplitude")
        commands = pre_function_commands + function_commands
        for alias in aliases:
            commands.extend(setting_commands.get(alias, []))
        shape_settings = dict(shape_settings)
        if phase is not None:
            shape_settings["set_phase"] = {"phase": phase}
        for alias, values in shape_settings.items():
            if alias not in self._scpi_engine.list_names():
                raise InstrumentConfigurationError(
                    self.config.model, f"Profile does not declare shape command alias {alias!r}."
                )
            for parameter, value in values.items():
                if not isinstance(value, (int, float)) or not math.isfinite(value):
                    raise InstrumentParameterError(
                        parameter=parameter,
                        value=value,
                        message="Setting must be finite and numeric.",
                    )
                if parameter in {"duty_cycle", "symmetry"} and not 0 <= value <= 100:
                    raise InstrumentParameterError(
                        parameter=parameter,
                        value=value,
                        message="Percentage must be between 0 and 100.",
                    )
                if parameter in {"period", "width", "transition_both"} and value <= 0:
                    raise InstrumentParameterError(
                        parameter=parameter, value=value, message="Time must be positive."
                    )
            commands.extend(self._scpi_engine.build(alias, channel=ch, **values))
        return commands

    @validate_call
    def set_function(
        self,
        channel: int | str,
        function_type: str,
        *,
        frequency: float | str | None = None,
        amplitude: float | str | None = None,
        offset: float | str | None = None,
    ) -> None:
        """Set a waveform function and optional standard channel settings."""
        ch = self._validate_channel(channel)
        commands = self._build_function_commands(
            ch,
            function_type,
            {},
            {
                "frequency": frequency,
                "amplitude": amplitude,
                "offset": offset,
            },
        )
        for command in commands:
            self._send_command(command)
        self._logger.debug(f"Channel {ch}: Function set to {function_type}")

    def get_function(self, channel: int | str) -> str:
        """Read back which waveform shape a channel is currently generating."""
        ch = self._validate_channel(channel)
        query = self._scpi_engine.build("get_function", channel=ch)[0]
        response = self._query(query).strip()
        function = str(self._resolve_transport_response("set_function", "function_type", response))
        self._logger.debug(f"Channel {ch}: Current function is {function}")
        return function

    @validate_call
    def set_frequency(self, channel: int | str, frequency: float | str) -> None:
        """Set the output frequency of a channel, in Hz."""
        ch = self._validate_channel(channel)
        resolved = self._resolve_operation_arguments(
            "set_frequency", {"channel": ch, "frequency": frequency}
        ).get("set_frequency", {})
        frequency = resolved.get("frequency", frequency)
        frequency = self._validate_native_numeric_setting(
            "set_frequency", "frequency", ch, frequency
        )
        for cmd in self._scpi_engine.build("set_frequency", channel=ch, frequency=frequency):
            self._send_command(cmd)
        self._logger.debug(f"Channel {ch}: Frequency set to {frequency} Hz")

    @validate_call
    def get_frequency(self, channel: int | str, query_type: str | None = None) -> float:
        """Read back the output frequency of a channel, in Hz."""
        ch = self._validate_channel(channel)
        token = self._native_bound_query_token("get_frequency", query_type)
        q, type_str = self._profile_limit_query("get_frequency", ch, query_type, query_token=token)
        response = (self._query(q)).strip()
        try:
            freq = float(response)
        except ValueError as e:
            raise InstrumentCommunicationError(
                instrument=self.config.model,
                command=q,
                message=f"Failed to parse frequency float from response: '{response}'",
            ) from e
        self._logger.debug(f"Channel {ch}: Frequency{type_str} is {freq} Hz")
        return freq

    @validate_call
    def set_amplitude(self, channel: int | str, amplitude: float | str) -> None:
        """Set the output amplitude of a channel.


        The value is interpreted in the channel's current voltage unit, which is
        peak-to-peak volts unless changed with :meth:`set_voltage_unit`.
        """
        ch = self._validate_channel(channel)
        resolved = self._resolve_operation_arguments(
            "set_amplitude", {"channel": ch, "amplitude": amplitude}
        ).get("set_amplitude", {})
        amplitude = resolved.get("amplitude", amplitude)
        amplitude = self._validate_native_numeric_setting(
            "set_amplitude", "amplitude", ch, amplitude
        )
        self._validate_direct_peak_budget(ch, amplitude=amplitude)
        for cmd in self._scpi_engine.build("set_amplitude", channel=ch, amplitude=amplitude):
            self._send_command(cmd)
        self._logger.debug(
            f"Channel {ch}: Amplitude set to {amplitude} in the current voltage unit"
        )

    @validate_call
    def get_amplitude(self, channel: int | str, query_type: str | None = None) -> float:
        """Read back the output amplitude of a channel in its current voltage unit."""
        ch = self._validate_channel(channel)
        token = self._native_bound_query_token("get_amplitude", query_type)
        q, type_str = self._profile_limit_query("get_amplitude", ch, query_type, query_token=token)
        response = (self._query(q)).strip()
        try:
            amp = float(response)
        except ValueError as e:
            raise InstrumentCommunicationError(
                instrument=self.config.model,
                command=q,
                message=f"Failed to parse amplitude float from response: '{response}'",
            ) from e
        unit = self.get_voltage_unit(ch)
        self._logger.debug(f"Channel {ch}: Amplitude{type_str} is {amp} {unit}")
        return amp

    @validate_call
    def set_offset(self, channel: int | str, offset: float | str) -> None:
        """Set the DC offset of a channel, in volts."""
        ch = self._validate_channel(channel)
        resolved = self._resolve_operation_arguments(
            "set_offset", {"channel": ch, "offset": offset}
        ).get("set_offset", {})
        offset = resolved.get("offset", offset)
        offset = self._validate_native_numeric_setting("set_offset", "offset", ch, offset)
        self._validate_direct_peak_budget(ch, offset=offset)
        for cmd in self._scpi_engine.build("set_offset", channel=ch, offset=offset):
            self._send_command(cmd)
        self._logger.debug(f"Channel {ch}: Offset set to {offset} V")

    @validate_call
    def get_offset(self, channel: int | str, query_type: str | None = None) -> float:
        """Read back the DC offset of a channel, in volts."""
        ch = self._validate_channel(channel)
        token = self._native_bound_query_token("get_offset", query_type)
        q, type_str = self._profile_limit_query("get_offset", ch, query_type, query_token=token)
        response = (self._query(q)).strip()
        try:
            offs = float(response)
        except ValueError as e:
            raise InstrumentCommunicationError(
                instrument=self.config.model,
                command=q,
                message=f"Failed to parse offset float from response: '{response}'",
            ) from e
        self._logger.debug(f"Channel {ch}: Offset{type_str} is {offs} V")
        return offs

    @validate_call
    def set_phase(self, channel: int | str, phase: float | str) -> None:
        """Set the output phase of a channel, in the current angle unit."""
        ch = self._validate_channel(channel)
        value = getattr(phase, "value", phase)
        if isinstance(value, str):
            try:
                value = float(value)
            except ValueError:
                value = self._format_value_min_max_def(value)
        if isinstance(value, (int, float)) and not math.isfinite(value):
            raise InstrumentParameterError(
                parameter="phase", value=value, message="Phase must be finite."
            )
        for command in self._scpi_engine.build("set_phase", channel=ch, phase=value):
            self._send_command(command)
        self._logger.debug(f"Channel {ch}: Phase set to {phase} in the current angle unit")

    @validate_call
    def get_phase(self, channel: int | str, query_type: str | None = None) -> float:
        """Read back the output phase of a channel, in the current angle unit."""
        ch = self._validate_channel(channel)
        cmd = self._scpi_engine.build("get_phase", channel=ch)[0]
        type_str = ""
        if query_type:
            semantic_query = str(getattr(query_type, "name", query_type))
            transport_query = self._profile_special_value(semantic_query)
            if transport_query is None:
                raise InstrumentParameterError(
                    parameter="query_type",
                    value=query_type,
                    message="Query type is not declared by the profile.",
                )
            cmd += f" {transport_query}"
            type_str = f" ({semantic_query} limit)"
        response = (self._query(cmd)).strip()
        try:
            ph = float(response)
        except ValueError as e:
            raise InstrumentCommunicationError(
                instrument=self.config.model,
                command=cmd,
                message=f"Failed to parse phase float from response: '{response}'",
            ) from e
        unit = self.get_angle_unit()
        self._logger.debug(f"Channel {ch}: Phase{type_str} is {ph} {unit}")
        return ph

    @validate_call
    def set_phase_reference(self, channel: int | str) -> None:
        """Reset a channel's phase reference so subsequent phase settings are relative to now."""
        ch = self._validate_channel(channel)
        self._send_command(self._scpi_engine.build("set_phase_reference", channel=ch)[0])
        self._logger.debug(f"Channel {ch}: Phase reference reset (current phase defined as 0).")

    @validate_call
    def synchronize_phase_all_channels(self) -> None:
        """Align the phase of every channel to a common reference.


        Use this before measuring a phase relationship between two outputs.
        """
        if self.channel_count < 2:
            self._logger.warning(
                "Warning: Phase synchronization command sent, but primarily intended for multi-channel instruments."
            )
        self._send_command(self._scpi_engine.build("synchronize_phase_all_channels")[0])
        self._logger.debug("All channels/internal phase generators synchronized.")

    @validate_call
    def set_phase_unlock_error_state(self, state: bool | str) -> None:
        """Enable or disable reporting of phase-unlock errors."""
        self._send_command(
            self._scpi_engine.build(
                "set_phase_unlock_error_state", channel=1, state=self._profile_bool_token(state)
            )[0]
        )
        self._logger.debug(f"Phase unlock error state set to {state}")

    @validate_call
    def get_phase_unlock_error_state(self) -> bool:
        """Read back whether phase-unlock error reporting is enabled."""
        cmd = self._scpi_engine.build("get_phase_unlock_error_state", channel=1)[0]
        response = (self._query(cmd)).strip()
        state = self._profile_bool_response(response, cmd)
        self._logger.debug(f"Phase unlock error state is {state}")
        return state

    @validate_call
    def set_output_state(self, channel: int | str, state: bool | str) -> None:
        """Turn a channel's output on or off."""
        ch = self._validate_channel(channel)
        resolved = self._resolve_operation_arguments(
            "set_output_state", {"channel": ch, "state": state}
        ).get("set_output_state", {})
        transport_state = resolved.get("state", getattr(state, "value", state))
        for cmd in self._scpi_engine.build("set_output_state", channel=ch, state=transport_state):
            self._send_command(cmd)
        self._logger.debug(f"Channel {ch}: Output state set to {transport_state}")

    @validate_call
    def get_output_state(self, channel: int | str) -> bool:
        """Read back whether a channel's output is on or off."""
        ch = self._validate_channel(channel)
        q = self._scpi_engine.build("get_output_state", channel=ch)[0]
        response = self._query(q)
        state = self._profile_bool_response(response, q)
        self._logger.debug(f"Channel {ch}: Output state is {state}")
        return state

    @validate_call
    def set_output_load_impedance(self, channel: int | str, impedance: float | str) -> None:
        """Set the expected load impedance a channel drives, in ohms.


        Accepts a number, or ``"INFinity"`` for a high-impedance load. The
        instrument scales the programmed amplitude to suit this load.
        """
        ch = self._validate_channel(channel)
        resolved = self._resolve_operation_arguments(
            "set_output_load_impedance", {"channel": ch, "impedance": impedance}
        ).get("set_output_load_impedance", {})
        impedance = resolved.get("impedance", impedance)
        cmd_impedance = self._format_value_min_max_def(impedance)
        target_is_infinite = isinstance(impedance, str) and impedance.casefold() in {
            "inf",
            "infinity",
            "infinite",
        }
        if not target_is_infinite:
            try:
                numeric_load = float(impedance)
                sentinel = self.config.operation_options.parameter("load_sentinel", "value")
                target_is_infinite = (
                    sentinel is not None
                    and sentinel.default is not None
                    and abs(numeric_load - float(sentinel.default)) < 1e30
                )
            except (TypeError, ValueError):
                pass
        if target_is_infinite and self._awg_unit_requires_finite_load(self.get_voltage_unit(ch)):
            raise InstrumentParameterError(
                parameter="impedance",
                value=impedance,
                message="Cannot select high impedance while the amplitude unit is dBm.",
            )
        for cmd in self._scpi_engine.build(
            "set_output_load_impedance", channel=ch, impedance=cmd_impedance
        ):
            self._send_command(cmd)
        self._logger.debug(
            f"Channel {ch}: Output load impedance setting updated to {impedance} (using SCPI value: {cmd_impedance})"
        )

    @validate_call
    def get_output_load_impedance(
        self, channel: int | str, query_type: str | None = None
    ) -> float | str:
        """Read back the expected load impedance of a channel, in ohms."""
        ch = self._validate_channel(channel)
        cmd, type_str = self._profile_limit_query("get_output_load_impedance", ch, query_type)
        response = (self._query(cmd)).strip()
        self._logger.debug(f"Channel {ch}: Raw impedance response{type_str} is '{response}'")
        try:
            numeric_response = float(response)
            sentinel_spec = self.config.operation_options.parameter("load_sentinel", "value")
            if sentinel_spec is None or sentinel_spec.default is None:
                raise InstrumentConfigurationError(
                    self.config.model, "Profile does not declare the high-impedance sentinel."
                )
            sentinel = sentinel_spec.default
            if abs(numeric_response - float(sentinel)) < 1e30:
                return "infinity"
            else:
                return numeric_response
        except ValueError as e:
            special = self.config.operation_options.parameter("special_values", "value")
            if special is not None:
                for option in special.options:
                    token = getattr(option.transport, "value", None)
                    if token is not None and response.casefold() == str(token).casefold():
                        return str(option.value)
            raise InstrumentCommunicationError(
                instrument=self.config.model,
                command=cmd,
                message=f"Could not parse impedance response: '{response}'",
            ) from e

    @validate_call
    def set_output_polarity(self, channel: int | str, polarity: str) -> None:
        """Set a channel's output polarity to normal or inverted."""
        ch = self._validate_channel(channel)
        self._send_command(
            self._scpi_engine.build("set_output_polarity", channel=ch, polarity=polarity)[0]
        )
        self._logger.debug(f"Channel {ch}: Output polarity set to {polarity}")

    @validate_call
    def get_output_polarity(self, channel: int | str) -> str:
        """Read back a channel's output polarity."""
        ch = self._validate_channel(channel)
        cmd = self._scpi_engine.build("get_output_polarity", channel=ch)[0]
        response = (self._query(cmd)).strip().upper()
        return self._profile_enum_value("set_output_polarity", "polarity", response)

    @validate_call
    def set_voltage_unit(self, channel: int | str, unit: str) -> None:
        """Set the unit amplitudes are programmed in: Vpp, Vrms or dBm."""
        ch = self._validate_channel(channel)
        resolved = self._resolve_operation_arguments(
            "set_voltage_unit", {"channel": ch, "unit": unit}
        ).get("set_voltage_unit", {})
        transport_unit = resolved.get("unit", unit)
        required_load = self._awg_unit_load_requirement(str(transport_unit))
        if self._awg_unit_requires_finite_load(
            str(transport_unit)
        ) and not self._awg_load_is_finite_positive(ch):
            raise InstrumentParameterError(
                parameter="unit",
                value=unit,
                message="dBm requires a finite positive load impedance.",
            )
        if required_load is not None and not self._awg_load_matches(ch, required_load):
            raise InstrumentParameterError(
                parameter="unit",
                value=unit,
                message=f"The profile requires a {required_load} ohm load for {transport_unit} operation.",
            )
        self._send_command(
            self._scpi_engine.build("set_voltage_unit", channel=ch, unit=transport_unit)[0]
        )
        self._logger.debug(f"Channel {ch}: Voltage unit set to {transport_unit}")

    @validate_call
    def get_voltage_unit(self, channel: int | str) -> str:
        """Read back the unit amplitudes are currently programmed in."""
        ch = self._validate_channel(channel)
        cmd = self._scpi_engine.build("get_voltage_unit", channel=ch)[0]
        response = (self._query(cmd)).strip().upper()
        return self._profile_enum_value("set_voltage_unit", "unit", response)

    @validate_call
    def set_voltage_limits_state(self, channel: int | str, state: bool | str) -> None:
        """Enable or disable the channel's output voltage limits."""
        ch = self._validate_channel(channel)
        token = self._profile_bool_token(state)
        if token.casefold() in {"on", "1", "true"}:
            extents = self._awg_active_output_extents(ch)
            low = self.get_voltage_limit_low(ch)
            high = self.get_voltage_limit_high(ch)
            if low > high:
                raise InstrumentParameterError(
                    parameter="state",
                    value=state,
                    message="Low voltage limit exceeds high voltage limit.",
                )
            if extents is not None and (extents[0] < low or extents[1] > high):
                raise InstrumentParameterError(
                    parameter="state",
                    value=state,
                    valid_range=(extents[0], extents[1]),
                    message="Cannot enable voltage limits that exclude the current output.",
                )
        self._send_command(
            self._scpi_engine.build("set_voltage_limits_state", channel=ch, state=token)[0]
        )
        self._logger.debug(f"Channel {ch}: Voltage limits state set to {state}")

    @validate_call
    def get_voltage_limits_state(self, channel: int | str) -> bool:
        """Read back whether the channel's output voltage limits are enabled."""
        ch = self._validate_channel(channel)
        response = (
            self._query(self._scpi_engine.build("get_voltage_limits_state", channel=ch)[0])
        ).strip()
        state = self._profile_bool_response(
            response, self._scpi_engine.build("get_voltage_limits_state", channel=ch)[0]
        )
        self._logger.debug(f"Channel {ch}: Voltage limits state is {state}")
        return state

    @validate_call
    def set_voltage_limit_high(self, channel: int | str, voltage: float | str) -> None:
        """Set the upper output voltage limit of a channel, in volts."""
        ch = self._validate_channel(channel)
        resolved = self._resolve_operation_arguments(
            "set_voltage_limit_high", {"channel": ch, "voltage": voltage}
        ).get("set_voltage_limit_high", {})
        voltage = resolved.get("voltage", voltage)
        self._validate_voltage_limit_candidate(ch, "high", voltage)
        cmd_val = self._format_value_min_max_def(voltage)
        self._send_command(
            self._scpi_engine.build("set_voltage_limit_high", channel=ch, voltage=cmd_val)[0]
        )
        self._logger.debug(
            f"Channel {ch}: Voltage high limit set to {voltage} V (using SCPI value: {cmd_val})"
        )

    @validate_call
    def get_voltage_limit_high(self, channel: int | str, query_type: str | None = None) -> float:
        """Read back the upper output voltage limit of a channel, in volts."""
        ch = self._validate_channel(channel)
        token = self._native_bound_query_token("get_voltage_limit_high", query_type)
        cmd, type_str = self._profile_limit_query(
            "get_voltage_limit_high", ch, query_type, label="possible", query_token=token
        )
        response = (self._query(cmd)).strip()
        try:
            val = float(response)
        except ValueError as e:
            raise InstrumentCommunicationError(
                instrument=self.config.model,
                command=cmd,
                message=f"Failed to parse high limit float from response: '{response}'",
            ) from e
        self._logger.debug(f"Channel {ch}: Voltage high limit{type_str} is {val} V")
        return val

    @validate_call
    def set_voltage_limit_low(self, channel: int | str, voltage: float | str) -> None:
        """Set the lower output voltage limit of a channel, in volts."""
        ch = self._validate_channel(channel)
        resolved = self._resolve_operation_arguments(
            "set_voltage_limit_low", {"channel": ch, "voltage": voltage}
        ).get("set_voltage_limit_low", {})
        voltage = resolved.get("voltage", voltage)
        self._validate_voltage_limit_candidate(ch, "low", voltage)
        cmd_val = self._format_value_min_max_def(voltage)
        self._send_command(
            self._scpi_engine.build("set_voltage_limit_low", channel=ch, voltage=cmd_val)[0]
        )
        self._logger.debug(
            f"Channel {ch}: Voltage low limit set to {voltage} V (using SCPI value: {cmd_val})"
        )

    @validate_call
    def get_voltage_limit_low(self, channel: int | str, query_type: str | None = None) -> float:
        """Read back the lower output voltage limit of a channel, in volts."""
        ch = self._validate_channel(channel)
        token = self._native_bound_query_token("get_voltage_limit_low", query_type)
        cmd, type_str = self._profile_limit_query(
            "get_voltage_limit_low", ch, query_type, label="possible", query_token=token
        )
        response = (self._query(cmd)).strip()
        try:
            val = float(response)
        except ValueError as e:
            raise InstrumentCommunicationError(
                instrument=self.config.model,
                command=cmd,
                message=f"Failed to parse low limit float from response: '{response}'",
            ) from e
        self._logger.debug(f"Channel {ch}: Voltage low limit{type_str} is {val} V")
        return val

    @validate_call
    def set_voltage_autorange_state(self, channel: int | str, state: bool | str) -> None:
        """Enable or disable automatic output voltage ranging on a channel."""
        ch = self._validate_channel(channel)
        self._send_command(
            self._scpi_engine.build(
                "set_voltage_autorange_state", channel=ch, state=self._profile_bool_token(state)
            )[0]
        )
        self._logger.debug(f"Channel {ch}: Voltage autorange state set to {state}")

    @validate_call
    def get_voltage_autorange_state(self, channel: int | str) -> bool:
        """Read back whether automatic output voltage ranging is enabled."""
        ch = self._validate_channel(channel)
        response = (
            self._query(self._scpi_engine.build("get_voltage_autorange_state", channel=ch)[0])
        ).strip()
        state = self._profile_bool_response(
            response, self._scpi_engine.build("get_voltage_autorange_state", channel=ch)[0]
        )
        self._logger.debug(f"Channel {ch}: Voltage autorange state is {state}")
        return state

    @validate_call
    def set_sync_output_state(self, state: bool | str) -> None:
        """Turn the front-panel sync output on or off."""
        self._send_command(
            self._scpi_engine.build("set_sync_output_state", state=self._profile_bool_token(state))[
                0
            ]
        )
        self._logger.debug(f"Sync output state set to {state}")

    @validate_call
    def get_sync_output_state(self) -> bool:
        """Read back whether the sync output is on or off."""
        cmd = self._scpi_engine.build("get_sync_output_state")[0]
        response = (self._query(cmd)).strip()
        state = self._profile_bool_response(response, cmd)
        self._logger.debug(f"Sync output state is {state}")
        return state

    @validate_call
    def set_sync_output_mode(self, channel: int | str, mode: str) -> None:
        """Set which edge or event the sync output marks for a channel."""
        ch = self._validate_channel(channel)
        self._send_command(
            self._scpi_engine.build("set_sync_output_mode", channel=ch, mode=mode)[0]
        )
        self._logger.debug(f"Channel {ch}: Sync output mode set to {mode}")

    @validate_call
    def get_sync_output_mode(self, channel: int | str) -> str:
        """Read back the sync output mode of a channel."""
        ch = self._validate_channel(channel)
        cmd = self._scpi_engine.build("get_sync_output_mode", channel=ch)[0]
        response = (self._query(cmd)).strip().upper()
        return self._profile_enum_value("set_sync_output_mode", "mode", response)

    @validate_call
    def set_sync_output_polarity(self, channel: int | str, polarity: str) -> None:
        """Set the sync output polarity to normal or inverted."""
        ch = self._validate_channel(channel)
        self._send_command(
            self._scpi_engine.build("set_sync_output_polarity", channel=ch, polarity=polarity)[0]
        )
        self._logger.debug(f"Channel {ch}: Sync output polarity set to {polarity}")

    @validate_call
    def get_sync_output_polarity(self, channel: int | str) -> str:
        """Read back the sync output polarity."""
        ch = self._validate_channel(channel)
        cmd = self._scpi_engine.build("get_sync_output_polarity", channel=ch)[0]
        response = (self._query(cmd)).strip().upper()
        return self._profile_enum_value("set_sync_output_polarity", "polarity", response)

    @validate_call
    def set_sync_output_source(self, source_channel: int) -> None:
        """Choose which channel drives the sync output."""
        resolved = self._resolve_operation_parameter(
            "set_sync_output_source", "source_channel", source_channel
        )
        self._send_command(
            self._scpi_engine.build("set_sync_output_source", channel=resolved.transport_value)[0]
        )
        self._logger.debug(f"Sync output source set to channel {resolved.value}")

    @validate_call
    def get_sync_output_source(self) -> int:
        """Read back which channel drives the sync output."""
        cmd = self._scpi_engine.build("get_sync_output_source")[0]
        response = (self._query(cmd)).strip().upper()
        spec = self.config.operation_options.parameter("set_sync_output_source", "source_channel")
        if spec is not None:
            for option in spec.options:
                tokens = option.constraints.get("response_tokens", [])
                if any(response == str(token).upper() for token in tokens):
                    return int(option.value)
        raise InstrumentCommunicationError(
            instrument=self.config.model,
            command="sync source readback",
            message=f"Unexpected sync-source response: {response!r}",
        )

    @validate_call
    def select_arbitrary_waveform(self, channel: int | str, arb_name: str) -> None:
        """Select which stored arbitrary waveform a channel replays."""
        ch = self._validate_channel(channel)
        if not arb_name:
            raise InstrumentParameterError(
                parameter="arb_name", message="Arbitrary waveform name cannot be empty."
            )
        if '"' in arb_name or "'" in arb_name:
            raise InstrumentParameterError(
                parameter="arb_name",
                value=arb_name,
                message="Arbitrary waveform name cannot contain quotes.",
            )
        quoted_arb_name = f'"{arb_name}"'
        self._send_command(
            self._scpi_engine.build(
                "select_arbitrary_waveform", channel=ch, arb_name=quoted_arb_name
            )[0]
        )
        self._logger.debug(f"Channel {ch}: Active arbitrary waveform selection set to '{arb_name}'")

    @validate_call
    def get_selected_arbitrary_waveform_name(self, channel: int | str) -> str:
        """Read back the name of the arbitrary waveform a channel is replaying."""
        ch = self._validate_channel(channel)
        cmd = self._scpi_engine.build("get_selected_arbitrary_waveform_name", channel=ch)[0]
        response = (self._query(cmd)).strip()
        if response.startswith('"') and response.endswith('"'):
            response = response[1:-1]
        self._logger.debug(f"Channel {ch}: Currently selected arbitrary waveform is '{response}'")
        return response

    @validate_call
    def set_arbitrary_waveform_sample_rate(
        self, channel: int | str, sample_rate: float | str
    ) -> None:
        """Set the arbitrary waveform playback rate, in samples per second."""
        ch = self._validate_channel(channel)
        cmd_val = self._format_value_min_max_def(sample_rate)
        if isinstance(sample_rate, int | float):
            if (
                hasattr(self.config, "waveforms")
                and hasattr(self.config.waveforms, "arbitrary")
                and self.config.waveforms.arbitrary is not None
                and hasattr(self.config.waveforms.arbitrary, "sampling_rate")
                and self.config.waveforms.arbitrary.sampling_rate is not None
            ):
                self.config.waveforms.arbitrary.sampling_rate.assert_in_range(
                    float(sample_rate), name="Arbitrary sample rate"
                )
        self._send_command(
            self._scpi_engine.build(
                "set_arbitrary_waveform_sample_rate", channel=ch, sample_rate=cmd_val
            )[0]
        )
        self._logger.debug(
            f"Channel {ch}: Arbitrary waveform sample rate set to {sample_rate} Sa/s (using SCPI value: {cmd_val})"
        )

    @validate_call
    def get_arbitrary_waveform_sample_rate(
        self, channel: int | str, query_type: str | None = None
    ) -> float:
        """Read back the arbitrary waveform playback rate, in samples per second."""
        ch = self._validate_channel(channel)
        cmd, type_str = self._profile_limit_query(
            "get_arbitrary_waveform_sample_rate", ch, query_type
        )
        response = (self._query(cmd)).strip()
        try:
            sr = float(response)
        except ValueError as e:
            raise InstrumentCommunicationError(
                instrument=self.config.model,
                command=cmd,
                message=f"Failed to parse sample rate float from response: '{response}'",
            ) from e
        self._logger.debug(f"Channel {ch}: Arbitrary waveform sample rate{type_str} is {sr} Sa/s")
        return sr

    @validate_call
    def get_arbitrary_waveform_points(self, channel: int | str) -> int:
        """Read back how many points the selected arbitrary waveform contains."""
        ch = self._validate_channel(channel)
        try:
            response = (
                self._query(self._scpi_engine.build("get_arbitrary_waveform_points", channel=ch)[0])
            ).strip()
            points = int(response)
            self._logger.debug(
                f"Channel {ch}: Currently selected arbitrary waveform has {points} points"
            )
            return points
        except ValueError as e:
            raise InstrumentCommunicationError(
                instrument=self.config.model,
                command=self._scpi_engine.build("get_arbitrary_waveform_points", channel=ch)[0],
                message=f"Failed to parse integer points from response: '{response}'",
            ) from e
        except InstrumentCommunicationError as e:
            code, msg = self.get_error()
            if code != 0:
                self._logger.warning(
                    f"Query for arbitrary waveform points failed. Inst Err {code}: {msg}. Returning 0."
                )
                return 0
            else:
                raise e

    def download_arbitrary_waveform_data(
        self,
        channel: int | str,
        arb_name: str,
        data_points: list[int] | list[float] | np.ndarray,
        data_type: str = "DAC",
        use_binary: bool = True,
        is_dual_channel_data: bool = False,
        dual_data_format: str | None = None,
    ) -> None:
        """Upload arbitrary waveform samples to the instrument.


        Args:
            channel: Channel the waveform is stored against.
            arb_name: Name to store the waveform under.
            data_points: Sample values to send.

        The transfer format is chosen automatically; use the CSV or binary
        variants to force one.
        """
        if use_binary:
            self.download_arbitrary_waveform_data_binary(
                channel,
                arb_name,
                data_points,
                data_type,
                is_dual_channel_data=is_dual_channel_data,
                dual_data_format=dual_data_format,
            )
        else:
            self.download_arbitrary_waveform_data_csv(channel, arb_name, data_points, data_type)

    def download_arbitrary_waveform_data_csv(
        self,
        channel: int | str,
        arb_name: str,
        data_points: list[int] | list[float] | np.ndarray,
        data_type: str = "DAC",
    ) -> None:
        """Upload arbitrary waveform samples as comma-separated ASCII values.


        Slower than the binary transfer but easier to inspect on the wire.
        """
        ch = self._validate_channel(channel)
        if not re.match(r"^[a-zA-Z0-9_]{1,12}$", arb_name):
            raise InstrumentParameterError(
                parameter="arb_name",
                value=arb_name,
                message="Arbitrary waveform name is invalid.",
            )
        data_type_upper = data_type.upper().strip()
        data_type_options = self._scpi_engine.list_options(
            "download_arbitrary_waveform_data_csv", "data_type"
        )
        data_type_lookup = {
            str(key).upper(): str(choice.get("value", key)).upper()
            for choice in data_type_options
            for key in (
                choice.get("value"),
                choice.get("token"),
                choice.get("label"),
                *(choice.get("aliases", []) or []),
            )
            if key is not None
        }
        try:
            data_type_semantic = data_type_lookup[data_type_upper]
        except KeyError as e:
            raise InstrumentParameterError(
                parameter="data_type",
                value=data_type,
                valid_range=sorted(data_type_lookup),
                message="Invalid data_type declared by the profile.",
            ) from e
        np_data = np.asarray(data_points)
        if np_data.ndim != 1 or np_data.size == 0:
            raise InstrumentParameterError(
                parameter="data_points", message="data_points must be a non-empty 1D sequence."
            )
        max_len = getattr(
            getattr(getattr(self.config, "waveforms", None), "arbitrary", None), "max_length", None
        )
        if isinstance(max_len, int | float) and np_data.size > max_len:
            self._logger.warning(
                f"Number of data points ({np_data.size}) exceeds configured max_length ({max_len})."
            )
        formatted_data: str
        if data_type_semantic == "DAC":
            if not np.issubdtype(np_data.dtype, np.integer):
                self._logger.warning("DAC data not integer, converting to int16.")
                try:
                    np_data = np_data.astype(np.int16)
                except ValueError as e:
                    raise InstrumentParameterError(
                        parameter="data_points",
                        message="Cannot convert DAC data to int16.",
                    ) from e
            dac_min, dac_max = (-32768, 32767)
            if np.any(np_data < dac_min) or np.any(np_data > dac_max):
                raise InstrumentParameterError(
                    parameter="data_points",
                    message=f"DAC data out of range [{dac_min}, {dac_max}].",
                )
            formatted_data = ",".join(map(str, np_data))
        else:  # NORM
            if not np.issubdtype(np_data.dtype, np.floating):
                self._logger.warning("Normalized data not float, converting to float32.")
                try:
                    np_data = np_data.astype(np.float32)
                except ValueError as e:
                    raise InstrumentParameterError(
                        parameter="data_points",
                        message="Cannot convert Normalized data to floats.",
                    ) from e
            norm_min, norm_max = -1.0, 1.0
            tolerance = 1e-9
            if np.any(np_data < norm_min - tolerance) or np.any(np_data > norm_max + tolerance):
                raise InstrumentParameterError(
                    parameter="data_points",
                    message=f"Normalized data out of range [{norm_min}, {norm_max}].",
                )
            np_data = np.clip(np_data, norm_min, norm_max)
            formatted_data = ",".join(map(lambda x: f"{x:.8G}", np_data))
        cmd = self._scpi_engine.build(
            "download_arbitrary_waveform_data_csv",
            channel=ch,
            data_type=data_type_semantic,
            arb_name=arb_name,
            formatted_data=formatted_data,
        )[0]
        max_cmd_len = getattr(self.config, "max_scpi_command_length", 10000)
        if len(cmd) > max_cmd_len:
            self._logger.warning(
                f"SCPI command length ({len(cmd)}) large. Consider binary transfer."
            )
        try:
            self._send_command(cmd)
            self._logger.debug(
                f"Channel {ch}: Downloaded arb '{arb_name}' via CSV ({np_data.size} points, type: {data_type_upper})"
            )
        except InstrumentCommunicationError as e:
            self._logger.error(f"Error during CSV arb download for '{arb_name}'.")
            code, msg = self.get_error()
            if code == -113:
                raise InstrumentCommunicationError(
                    instrument=self.config.model,
                    command=cmd,
                    message=f"SCPI Syntax Error (-113) for '{arb_name}'.",
                ) from e
            elif code == 786:
                raise InstrumentCommunicationError(
                    instrument=self.config.model,
                    command=cmd,
                    message=f"Arb Name Conflict (786) for '{arb_name}'.",
                ) from e
            elif code == 781:
                raise InstrumentCommunicationError(
                    instrument=self.config.model,
                    command=cmd,
                    message=f"Out of Memory (781) for '{arb_name}'.",
                ) from e
            elif code == -102:
                raise InstrumentCommunicationError(
                    instrument=self.config.model,
                    command=cmd,
                    message=f"SCPI Syntax Error (-102) for '{arb_name}'.",
                ) from e
            elif code != 0:
                raise InstrumentCommunicationError(
                    instrument=self.config.model,
                    command=cmd,
                    message=f"Arb download for '{arb_name}' failed. Inst Err {code}: {msg}",
                ) from e
            else:
                raise e

    def download_arbitrary_waveform_data_binary(
        self,
        channel: int | str,
        arb_name: str,
        data_points: list[int] | list[float] | np.ndarray,
        data_type: str = "DAC",
        is_dual_channel_data: bool = False,
        dual_data_format: str | None = None,
    ) -> None:
        """Upload arbitrary waveform samples as an IEEE definite-length binary block.


        Faster than the CSV transfer for long waveforms.
        """
        ch = self._validate_channel(channel)
        if not re.match(r"^[a-zA-Z0-9_]{1,12}$", arb_name):
            raise InstrumentParameterError(
                parameter="arb_name",
                value=arb_name,
                message="Arbitrary waveform name is invalid.",
            )
        data_type_result = self._resolve_operation_parameter(
            "download_arbitrary_waveform_data_binary", "data_type", data_type
        )
        dual_result = self._resolve_operation_parameter(
            "download_arbitrary_waveform_data_binary",
            "is_dual_channel_data",
            is_dual_channel_data,
        )
        data_type_semantic = str(data_type_result.value)
        np_data = np.asarray(data_points)
        if np_data.ndim != 1 or np_data.size == 0:
            raise InstrumentParameterError(
                parameter="data_points", message="data_points must be a non-empty 1D sequence."
            )
        num_points_total = np_data.size
        num_points_per_channel = num_points_total
        arb_cmd_node = str(dual_result.transport_value)
        if bool(dual_result.value):
            if self.channel_count < 2:
                raise InstrumentConfigurationError(
                    self.config.model,
                    "Dual channel download requires 2-channel instrument.",
                )
            arb_cmd_node = "ARBitrary2"
            if num_points_total % 2 != 0:
                raise InstrumentParameterError(
                    parameter="data_points",
                    message="Total data_points must be even for dual channel.",
                )
            num_points_per_channel = num_points_total // 2
            if dual_data_format:
                format_result = self._resolve_operation_parameter(
                    "download_arbitrary_waveform_data_binary",
                    "dual_data_format",
                    dual_data_format,
                )
                operation = self.config.operation_options.operation(
                    "download_arbitrary_waveform_data_binary"
                )
                format_alias = operation.transport["dual_format"] if operation else None
                if format_alias is None:
                    raise InstrumentConfigurationError(
                        self.config.model, "Profile does not declare dual-data formatting."
                    )
                for command in self._scpi_engine.build(
                    format_alias,
                    channel=ch,
                    node=arb_cmd_node,
                    format=format_result.transport_value,
                ):
                    self._send_command(command)
                self._logger.debug(
                    f"Channel {ch}: Dual arb data format set to {format_result.value}"
                )
        binary_data: bytes
        scpi_suffix: str
        transfer_type_log_msg: str = "Binary Block"
        if data_type_semantic == "dac":
            scpi_suffix = str(data_type_result.transport_value)
            if not np.issubdtype(np_data.dtype, np.integer):
                self._logger.warning("Warning: DAC data not integer, converting to int16.")
                try:
                    np_data = np_data.astype(np.int16)
                except ValueError as e:
                    raise InstrumentParameterError(
                        parameter="data_points",
                        message="Cannot convert DAC data to int16.",
                    ) from e
            dac_min, dac_max = (-32768, 32767)
            if np.any(np_data < dac_min) or np.any(np_data > dac_max):
                raise InstrumentParameterError(
                    parameter="data_points",
                    message=f"DAC data out of range [{dac_min}, {dac_max}].",
                )
            binary_data = np_data.astype("<h").tobytes()
        else:
            scpi_suffix = str(data_type_result.transport_value)
            if not np.issubdtype(np_data.dtype, np.floating):
                self._logger.warning("Warning: Normalized data not float, converting to float32.")
                try:
                    np_data = np_data.astype(np.float32)
                except ValueError as e:
                    raise InstrumentParameterError(
                        parameter="data_points",
                        message="Cannot convert Normalized data to float32.",
                    ) from e
            norm_min, norm_max = -1.0, 1.0
            tolerance = 1e-6
            if np.any(np_data < norm_min - tolerance) or np.any(np_data > norm_max + tolerance):
                raise InstrumentParameterError(
                    parameter="data_points",
                    message=f"Normalized data out of range [{norm_min}, {norm_max}].",
                )
            np_data = np.clip(np_data, norm_min, norm_max)
            binary_data = np_data.astype("<f").tobytes()
        operation = self.config.operation_options.operation(
            "download_arbitrary_waveform_data_binary"
        )
        prefix_alias = operation.transport["prefix"] if operation else None
        if prefix_alias is None:
            raise InstrumentConfigurationError(
                self.config.model, "Profile does not declare binary waveform framing."
            )
        cmd_prefix = self._scpi_engine.build(
            prefix_alias,
            channel=ch,
            node=arb_cmd_node,
            suffix=scpi_suffix,
            arb_name=arb_name,
        )[0]
        try:
            self._write_binary(cmd_prefix, binary_data)
            transfer_type_log_msg = "IEEE 488.2 Binary Block via _write_binary"
            self._logger.debug(
                f"Channel {ch}: Downloaded arb '{arb_name}' via {transfer_type_log_msg} ({num_points_per_channel} pts/ch, {len(binary_data)} bytes, type: {data_type_semantic})"
            )
        except InstrumentCommunicationError as e:
            self._logger.error(
                f"Error during {transfer_type_log_msg} arb download for '{arb_name}'."
            )
            code, msg = self.get_error()
            if code == 786:
                raise InstrumentCommunicationError(
                    instrument=self.config.model,
                    command=cmd_prefix,
                    message=f"Arb Name Conflict (786) for '{arb_name}'.",
                ) from e
            elif code == 781:
                raise InstrumentCommunicationError(
                    instrument=self.config.model,
                    command=cmd_prefix,
                    message=f"Out of Memory (781) for '{arb_name}'.",
                ) from e
            elif code == -113:
                raise InstrumentCommunicationError(
                    instrument=self.config.model,
                    command=cmd_prefix,
                    message=f"SCPI Syntax Error (-113) for '{arb_name}'.",
                ) from e
            elif code != 0:
                raise InstrumentCommunicationError(
                    instrument=self.config.model,
                    command=cmd_prefix,
                    message=f"Arb download for '{arb_name}' failed. Inst Err {code}: {msg}",
                ) from e
            else:
                raise e
        except Exception as e:
            self._logger.error(f"Unexpected error during binary arb download for '{arb_name}': {e}")
            raise InstrumentCommunicationError(
                instrument=self.config.model,
                command=cmd_prefix,
                message=f"Unexpected failure downloading arb '{arb_name}'",
            ) from e

    @validate_call
    def clear_volatile_arbitrary_waveforms(self, channel: int | str) -> None:
        """Delete all arbitrary waveforms held in the channel's volatile memory."""
        ch = self._validate_channel(channel)
        self._send_command(
            self._scpi_engine.build("clear_volatile_arbitrary_waveforms", channel=ch)[0]
        )
        self._logger.debug(f"Channel {ch}: Cleared volatile arbitrary waveform memory.")

    @validate_call
    def get_free_volatile_arbitrary_memory(self, channel: int | str) -> int:
        """Read back how many arbitrary waveform points still fit in volatile memory."""
        ch = self._validate_channel(channel)
        cmd = self._scpi_engine.build("get_free_volatile_arbitrary_memory", channel=ch)[0]
        response = (self._query(cmd)).strip()
        try:
            free_points = int(response)
        except ValueError as e:
            raise InstrumentCommunicationError(
                instrument=self.config.model,
                command=cmd,
                message=f"Unexpected non-integer response: {response}",
            ) from e
        self._logger.debug(f"Channel {ch}: Free volatile arbitrary memory: {free_points} points")
        return free_points

    @validate_call
    def get_pulse_duty_cycle(self, channel: int | str) -> float:
        """Read back the pulse duty cycle of a channel, as a percentage."""
        ch = self._validate_channel(channel)
        response = (
            self._query(self._scpi_engine.build("get_pulse_duty_cycle", channel=ch)[0])
        ).strip()
        return float(response)

    @validate_call
    def get_pulse_period(self, channel: int | str) -> float:
        """Read back the pulse period of a channel, in seconds."""
        ch = self._validate_channel(channel)
        response = (self._query(self._scpi_engine.build("get_pulse_period", channel=ch)[0])).strip()
        return float(response)

    @validate_call
    def get_pulse_width(self, channel: int | str) -> float:
        """Read back the pulse width of a channel, in seconds."""
        ch = self._validate_channel(channel)
        response = (self._query(self._scpi_engine.build("get_pulse_width", channel=ch)[0])).strip()
        return float(response)

    @validate_call
    def get_pulse_transition_leading(self, channel: int | str) -> float:
        """Read back the pulse leading-edge transition time, in seconds."""
        ch = self._validate_channel(channel)
        response = (
            self._query(self._scpi_engine.build("get_pulse_transition_leading", channel=ch)[0])
        ).strip()
        return float(response)

    @validate_call
    def get_pulse_transition_trailing(self, channel: int | str) -> float:
        """Read back the pulse trailing-edge transition time, in seconds."""
        ch = self._validate_channel(channel)
        response = (
            self._query(self._scpi_engine.build("get_pulse_transition_trailing", channel=ch)[0])
        ).strip()
        return float(response)

    @validate_call
    def get_pulse_transition_both(self, channel: int | str) -> float:
        """Read back the pulse edge transition time applied to both edges, in seconds."""
        warnings.warn(
            "Querying PULS:TRAN:BOTH; specific query may not exist or might return leading edge time.",
            UserWarning,
            stacklevel=2,
        )
        return self.get_pulse_transition_leading(channel)

    @validate_call
    def get_pulse_hold_mode(self, channel: int | str) -> str:
        """Read back whether pulse width or duty cycle is held constant when frequency changes."""
        ch = self._validate_channel(channel)
        response = (
            (self._query(self._scpi_engine.build("get_pulse_hold_mode", channel=ch)[0]))
            .strip()
            .upper()
        )
        return response

    @validate_call
    def get_square_duty_cycle(self, channel: int | str) -> float:
        """Read back the square wave duty cycle of a channel, as a percentage."""
        ch = self._validate_channel(channel)
        response = (
            self._query(self._scpi_engine.build("get_square_duty_cycle", channel=ch)[0])
        ).strip()
        return float(response)

    @validate_call
    def get_square_period(self, channel: int | str) -> float:
        """Read back the square wave period of a channel, in seconds."""
        ch = self._validate_channel(channel)
        response = (
            self._query(self._scpi_engine.build("get_square_period", channel=ch)[0])
        ).strip()
        return float(response)

    @validate_call
    def get_ramp_symmetry(self, channel: int | str) -> float:
        """Read back the ramp symmetry of a channel, as a percentage."""
        ch = self._validate_channel(channel)
        response = (
            self._query(self._scpi_engine.build("get_ramp_symmetry", channel=ch)[0])
        ).strip()
        return float(response)

    @validate_call
    def set_angle_unit(self, unit: str) -> None:
        """Set the unit phase is programmed in: degrees, radians or seconds."""
        self._send_resolved_operation("set_angle_unit", {"unit": unit})
        self._logger.debug(f"Global angle unit set to {unit}")

    @validate_call
    def get_angle_unit(self) -> str:
        """Read back the unit phase is currently programmed in."""
        response = self._query(self._scpi_engine.build("get_angle_unit")[0]).strip()
        spec = self.config.operation_options.parameter("set_angle_unit", "unit")
        if spec is not None:
            for option in spec.options:
                token = getattr(option.transport, "value", None)
                accepted = {str(token).casefold(), *(alias.casefold() for alias in option.aliases)}
                if response.casefold() in accepted:
                    return str(option.value)
        raise InstrumentCommunicationError(
            instrument=self.config.model,
            command="unit readback",
            message=f"Unexpected response: {response!r}",
        )

    @validate_call
    def apply_waveform_settings(
        self,
        channel: int | str,
        function_type: str,
        frequency: float | str = "default",
        amplitude: float | str = "default",
        offset: float | str = "default",
    ) -> None:
        """Configure shape, frequency, amplitude and offset of a channel in one call.


        Equivalent to the instrument's APPLy command; faster than setting each
        parameter separately.
        """
        ch = self._validate_channel(channel)
        # The profile owns both the accepted semantic values and the private
        # spelling used by the instrument's APPLy command.  Enum inputs remain
        # a compatibility adapter, while ordinary callers use profile values
        # such as ``"sine"``.
        function_value = str(getattr(function_type, "name", function_type)).lower()
        semantic_function = str(
            self._resolve_operation_parameter(
                "apply_waveform_settings", "function_type", function_value
            ).value
        )
        resolved = self._resolve_operation_arguments(
            "apply_waveform_settings",
            {
                "channel": ch,
                "function_type": function_value,
                "frequency": frequency,
                "amplitude": amplitude,
                "offset": offset,
            },
        )
        joint_offset = self._validate_compound_settings(
            ch,
            "apply_waveform_settings",
            semantic_function,
            {"frequency": frequency, "amplitude": amplitude, "offset": offset},
        )
        parameters = resolved.get("apply_waveform_settings", {})
        if joint_offset is not None:
            parameters["offset"] = joint_offset
        commands = self._scpi_engine.build(
            "apply_waveform_settings",
            channel=parameters.get("channel", ch),
            function=semantic_function,
            frequency=parameters.get("frequency", frequency),
            amplitude=parameters.get("amplitude", amplitude),
            offset=parameters.get("offset", offset),
        )
        for command in commands:
            self._send_command(command)
        self._logger.debug(
            f"Channel {ch}: Applied {semantic_function} with params: Freq/SR={frequency}, Ampl={amplitude}, Offs={offset}"
        )

    @validate_call
    def get_channel_configuration_summary(self, channel: int | str) -> str:
        """Return the instrument's own one-line summary of a channel's configuration."""
        ch = self._validate_channel(channel)
        response = (
            self._query(self._scpi_engine.build("get_channel_configuration_summary", channel=ch)[0])
        ).strip()
        self._logger.debug(f"Channel {ch}: Configuration summary returned: {response}")
        if response.startswith('"') and response.endswith('"') and response.count('"') == 2:
            return response[1:-1]
        return response

    @validate_call
    def get_complete_config(self, channel: int | str) -> WaveformConfigResult:
        """Read back every configurable setting of a channel as a structured result."""
        ch_num = self._validate_channel(channel)
        self._logger.debug(f"Getting complete configuration snapshot for channel {ch_num}...")
        func_scpi_str = self.get_function(ch_num)
        freq = self.get_frequency(ch_num)
        ampl = self.get_amplitude(ch_num)
        offs = self.get_offset(ch_num)
        output_state_bool = self.get_output_state(ch_num)
        load_impedance_val = self.get_output_load_impedance(ch_num)
        load_impedance_str: str | float
        if load_impedance_val == "infinity":
            load_impedance_str = "infinity"
        else:
            load_impedance_str = float(load_impedance_val)
        voltage_unit_enum = self.get_voltage_unit(ch_num)
        voltage_unit_str = voltage_unit_enum
        phase: float | None = None
        if func_scpi_str not in {"dc", "noise"}:
            try:
                phase = self.get_phase(ch_num)
            except InstrumentCommunicationError as e:
                self._log(
                    f"Note: Phase query failed for CH{ch_num} (function: {func_scpi_str}): {e}",
                    level="info",
                )
        symmetry: float | None = None
        duty_cycle: float | None = None
        try:
            if func_scpi_str == "ramp":
                symmetry = self.get_ramp_symmetry(ch_num)
            elif func_scpi_str == "square":
                duty_cycle = self.get_square_duty_cycle(ch_num)
            elif func_scpi_str == "pulse":
                duty_cycle = self.get_pulse_duty_cycle(ch_num)
        except InstrumentCommunicationError as e:
            self._log(
                f"Note: Query failed for function-specific parameter for CH{ch_num} func {func_scpi_str}: {e}",
                level="info",
            )
        return WaveformConfigResult(
            channel=ch_num,
            function=func_scpi_str,
            frequency=freq,
            amplitude=ampl,
            offset=offs,
            phase=phase,
            symmetry=symmetry,
            duty_cycle=duty_cycle,
            output_state=output_state_bool,
            load_impedance=load_impedance_str,
            voltage_unit=voltage_unit_str,
        )

    def enable_modulation(self, channel: int | str, mod_type: str, state: bool) -> None:
        """Turn a modulation mode (AM, FM, PM, FSK or PWM) on or off for a channel."""
        ch = self._validate_channel(channel)
        self._send_resolved_operation(
            "enable_modulation", {"channel": ch, "mod_type": mod_type, "state": state}
        )

    def set_am_depth(self, channel: int | str, depth_percent: float | str) -> None:
        """Set the amplitude modulation depth of a channel, as a percentage."""
        ch = self._validate_channel(channel)
        cmd_val = self._format_value_min_max_def(depth_percent)
        if isinstance(depth_percent, int | float) and not (0 <= float(depth_percent) <= 120):
            self._log(
                f"Warning: AM depth {depth_percent}% is outside typical 0-120 range.",
                level="warning",
            )
        self._send_command(self._scpi_engine.build("set_am_depth", channel=ch, depth=cmd_val)[0])
        self._logger.debug(f"Channel {ch}: AM depth set to {depth_percent}%")

    def set_am_source(self, channel: int | str, source: str) -> None:
        """Choose the amplitude modulation source: internal or external."""
        ch = self._validate_channel(channel)
        resolved = self._resolve_operation_arguments(
            "set_am_source", {"channel": ch, "source": source}
        ).get("set_am_source", {})
        cmd_src = resolved.get("source", source)
        semantic_source = str(getattr(source, "name", source)).casefold()
        if semantic_source in {f"channel_{ch}", f"ch{ch}"}:
            raise InstrumentParameterError(
                parameter="source",
                value=source,
                message=f"Channel {ch} cannot be its own AM source.",
            )
        if semantic_source in {"channel_2", "ch2"} and self.channel_count < 2:
            raise InstrumentParameterError(
                parameter="source",
                value=source,
                message="CH2 source invalid for 1-channel instrument.",
            )
        self._send_command(self._scpi_engine.build("set_am_source", channel=ch, source=cmd_src)[0])
        self._logger.debug(f"Channel {ch}: AM source set to {cmd_src}")

    def set_fm_deviation(self, channel: int | str, deviation_hz: float | str) -> None:
        """Set the frequency modulation peak deviation of a channel, in Hz."""
        ch = self._validate_channel(channel)
        cmd_val = self._format_value_min_max_def(deviation_hz)
        self._send_command(
            self._scpi_engine.build("set_fm_deviation", channel=ch, deviation=cmd_val)[0]
        )
        self._logger.debug(f"Channel {ch}: FM deviation set to {deviation_hz} Hz")

    def enable_sweep(self, channel: int | str, state: bool) -> None:
        """Turn frequency sweeping on or off for a channel."""
        ch = self._validate_channel(channel)
        self._send_resolved_operation("enable_sweep", {"channel": ch, "state": state})

    def set_sweep_time(self, channel: int | str, sweep_time_sec: float | str) -> None:
        """Set how long one frequency sweep takes, in seconds."""
        ch = self._validate_channel(channel)
        cmd_val = self._format_value_min_max_def(sweep_time_sec)
        self._send_command(self._scpi_engine.build("set_sweep_time", channel=ch, time=cmd_val)[0])
        self._logger.debug(f"Channel {ch}: Sweep time set to {sweep_time_sec} s")

    def set_sweep_start_frequency(self, channel: int | str, freq_hz: float | str) -> None:
        """Set the frequency a sweep starts from, in Hz."""
        ch = self._validate_channel(channel)
        cmd_val = self._format_value_min_max_def(freq_hz)
        self._send_command(
            self._scpi_engine.build("set_sweep_start_frequency", channel=ch, frequency=cmd_val)[0]
        )
        self._logger.debug(f"Channel {ch}: Sweep start frequency set to {freq_hz} Hz")

    def set_sweep_stop_frequency(self, channel: int | str, freq_hz: float | str) -> None:
        """Set the frequency a sweep ends at, in Hz."""
        ch = self._validate_channel(channel)
        cmd_val = self._format_value_min_max_def(freq_hz)
        self._send_command(
            self._scpi_engine.build("set_sweep_stop_frequency", channel=ch, frequency=cmd_val)[0]
        )
        self._logger.debug(f"Channel {ch}: Sweep stop frequency set to {freq_hz} Hz")

    def set_sweep_spacing(self, channel: int | str, spacing: str) -> None:
        """Set whether a sweep steps linearly or logarithmically."""
        ch = self._validate_channel(channel)
        self._send_resolved_operation("set_sweep_spacing", {"channel": ch, "spacing": spacing})
        self._logger.debug(f"Channel {ch}: Sweep spacing set to {spacing}")

    def enable_burst(self, channel: int | str, state: bool) -> None:
        """Turn burst mode on or off for a channel.


        In burst mode the channel emits a fixed number of cycles per trigger
        instead of running continuously.
        """
        ch = self._validate_channel(channel)
        self._send_resolved_operation("enable_burst", {"channel": ch, "state": state})

    def set_burst_mode(self, channel: int | str, mode: str) -> None:
        """Set the burst mode to triggered or gated."""
        ch = self._validate_channel(channel)
        self._send_resolved_operation("set_burst_mode", {"channel": ch, "mode": mode})
        self._logger.debug(f"Channel {ch}: Burst mode set to {mode}")

    def set_burst_cycles(self, channel: int | str, n_cycles: int | str) -> None:
        """Set how many cycles each burst emits."""
        ch = self._validate_channel(channel)
        cmd_val: str
        log_val: int | str = n_cycles
        if isinstance(n_cycles, str):
            nc_upper = n_cycles.upper().strip()
            special = self._profile_special_value(nc_upper)
            if special is not None:
                cmd_val = special
            else:
                raise InstrumentParameterError(
                    parameter="n_cycles",
                    value=n_cycles,
                    message="Invalid string for burst cycles.",
                )
        elif isinstance(n_cycles, int):
            if n_cycles < 1:
                raise InstrumentParameterError(
                    parameter="n_cycles",
                    value=n_cycles,
                    message="Burst cycle count must be positive.",
                )
            cmd_val = str(n_cycles)
        else:
            raise InstrumentParameterError(
                parameter="n_cycles",
                value=n_cycles,
                message=f"Invalid type '{type(n_cycles)}' for burst cycles.",
            )
        self._send_command(
            self._scpi_engine.build("set_burst_cycles", channel=ch, cycles=cmd_val)[0]
        )
        self._logger.debug(f"Channel {ch}: Burst cycles set to {log_val}")

    def set_burst_period(self, channel: int | str, period_sec: float | str) -> None:
        """Set the interval between internally triggered bursts, in seconds."""
        ch = self._validate_channel(channel)
        cmd_val = self._format_value_min_max_def(period_sec)
        self._send_command(
            self._scpi_engine.build("set_burst_period", channel=ch, period=cmd_val)[0]
        )
        self._logger.debug(f"Channel {ch}: Internal burst period set to {period_sec} s")

    def set_trigger_source(self, channel: int | str, source: str) -> None:
        """Choose what triggers a burst or sweep: immediate, external, bus or timer."""
        ch = self._validate_channel(channel)
        self._send_resolved_operation("set_trigger_source", {"channel": ch, "source": source})
        self._logger.debug(f"Channel {ch}: Trigger source set to {source}")

    def set_trigger_slope(self, channel: int | str, slope: str) -> None:
        """Set which external trigger edge starts a burst or sweep."""
        ch = self._validate_channel(channel)
        self._send_resolved_operation("set_trigger_slope", {"channel": ch, "slope": slope})
        self._logger.debug(f"Channel {ch}: Trigger slope set to {slope}")

    def trigger_now(self, channel: int | str | None = None) -> None:
        """Send an immediate software trigger to start a burst or sweep."""
        if channel is not None:
            ch = self._validate_channel(channel)
            self._send_command(self._scpi_engine.build("trigger_now", channel=ch)[0])
            self._logger.debug(f"Sent immediate channel-specific trigger for channel {ch}")
        else:
            self._send_command(self._scpi_engine.build("trigger_now_global")[0])
            self._logger.debug("Sent general bus trigger command *TRG")

    def list_directory(self, path: str = "") -> FileSystemInfo:
        """List files and folders in the instrument's internal storage."""
        path_scpi = f' "{path}"' if path else ""
        cmd = self._scpi_engine.build("list_directory", path=path_scpi)[0]
        response = (self._query(cmd)).strip()
        try:
            parts = response.split(",", 2)
            if len(parts) < 2:
                raise InstrumentCommunicationError(
                    instrument=self.config.model,
                    command=cmd,
                    message=f"Unexpected response format for directory listing: {response}",
                )
            bytes_used = int(parts[0])
            bytes_free = int(parts[1])
            info = FileSystemInfo(bytes_used=bytes_used, bytes_free=bytes_free)
            if len(parts) > 2 and parts[2]:
                file_pattern = r'"([^"]+),([^"]*),(\d+)"'
                listings = re.findall(file_pattern, parts[2])
                for name, ftype, size_str in listings:
                    file_type = ftype if ftype else "FILE"
                    try:
                        size = int(size_str)
                    except ValueError:
                        self._log(
                            f"Warning: Could not parse size '{size_str}' for file '{name}'.",
                            level="warning",
                        )
                        continue
                    info.files.append({"name": name, "type": file_type.upper(), "size": size})
            self._logger.debug(
                f"Directory listing for '{path or 'current dir'}': Used={info.bytes_used}, Free={info.bytes_free}, Items={len(info.files)}"
            )
            return info
        except (ValueError, IndexError) as e:
            raise InstrumentCommunicationError(
                instrument=self.config.model,
                command=cmd,
                message=f"Failed to parse directory listing response: '{response}'. Error: {e}",
            ) from e

    def delete_file_or_folder(self, path: str) -> None:
        """Delete a file or folder from the instrument's internal storage."""
        if not path:
            raise InstrumentParameterError(
                parameter="path", message="Path cannot be empty for deletion."
            )
        path_scpi = f'"{path}"'
        cmd = self._scpi_engine.build("delete_file_or_folder", path=path_scpi)[0]
        try:
            self._send_command(cmd)
            self._logger.debug(f"Attempted to delete file/folder: '{path}'")
        except InstrumentCommunicationError as e:
            code, msg = self.get_error()
            if code != 0:
                if "Directory not empty" in msg or "folder" in msg.lower():
                    raise InstrumentCommunicationError(
                        instrument=self.config.model,
                        command=cmd,
                        message=f"Failed to delete '{path}'. Non-empty folder? Inst Err {code}: {msg}",
                    ) from e
                else:
                    raise InstrumentCommunicationError(
                        instrument=self.config.model,
                        command=cmd,
                        message=f"Failed to delete '{path}'. Inst Err {code}: {msg}",
                    ) from e
            else:
                raise e

    @validate_call
    def channel(self, ch_num: int | str) -> WGChannelFacade:
        """
        Returns a facade for interacting with a specific channel.

        Args:
            ch_num (Union[int,str]): The channel number (1-based) or string identifier (e.g. "CH1").

        Returns:
            WGChannelFacade: A facade object for the specified channel.

        Raises:
            InstrumentParameterError: If channel number is invalid.
        """
        validated_ch_num = self._validate_channel(ch_num)  # _validate_channel returns int
        return WGChannelFacade(self, validated_ch_num)
