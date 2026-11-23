from __future__ import annotations

import math
import numbers
from collections.abc import Iterable
from dataclasses import dataclass
from threading import RLock
from types import MappingProxyType
from typing import Any
from typing import cast

from ..config.source_measure_config import SourceMeasureConfig
from ..errors import InstrumentConfigurationError
from ..errors import InstrumentDataError
from ..errors import InstrumentParameterError
from ..experiments import MeasurementResult
from ..uncertainty import Quantity
from ..uncertainty import resolve_traceability_ref
from ..uncertainty.specs import UncertaintyContext
from .instrument import Instrument
from .operation_contract import OperationDescriptor
from .scpi_engine import SCPIEngine
from .uncertainty_adapters import nominal_measurement_quantity
from .uncertainty_adapters import nonzero_uncertainty_quantity


class TypedMeasurementResult(MeasurementResult):
    """A source-measure reading with the instrument's measurement header."""

    def __init__(
        self,
        value: Quantity,
        header: str,
        channel: int,
        status: str,
        measurement_type: str,
        compliance: bool | None,
        status_text: str | None = None,
        status_metadata: dict[str, Any] | None = None,
        *,
        instrument: str = "",
    ) -> None:
        envelope = {
            "header": header,
            "physical_channel": channel,
            "status": status,
            "status_text": status_text,
            "compliance": compliance,
            "status_metadata": status_metadata or {},
        }
        super().__init__(
            values=value,
            instrument=instrument,
            units=value.unit,
            measurement_type=measurement_type,
            envelope=envelope,
        )
        self.header = header
        self.channel = channel
        self.physical_channel = channel
        self.status = status
        self.measurement_type = measurement_type
        self.compliance = compliance
        self.status_text = status_text
        self.status_metadata = dict(status_metadata or {})
        self.validity = self.status_metadata.get("validity")

    @property
    def value(self) -> Quantity:
        return cast(Quantity, self.values)

    @property
    def quantity(self) -> Quantity:
        """Alias for callers that name the measured quantity explicitly."""
        return self.value

    @property
    def unit(self) -> str:
        """Singular-unit alias matching the underlying :class:`Quantity`."""
        return self.units


@dataclass
class _ChannelState:
    mode: str | None = None
    voltage: float | None = None
    current_limit: float | None = None
    current: float | None = None
    voltage_compliance: float | None = None
    output: bool | None = None


class SourceMeasureChannelFacade:
    """Chainable facade for one configured source-measure channel."""

    def __init__(self, source_measure: SourceMeasure, channel_num: int) -> None:
        self._source_measure = source_measure
        self._channel = channel_num

    def set(
        self, voltage: float | None = None, current_limit: float | None = None
    ) -> SourceMeasureChannelFacade:
        self._source_measure._set_voltage_settings(self._channel, voltage, current_limit)
        return self

    def force_current(
        self, current: float, voltage_compliance: float
    ) -> SourceMeasureChannelFacade:
        self._source_measure.force_current(self._channel, current, voltage_compliance)
        return self

    def on(self) -> SourceMeasureChannelFacade:
        self._source_measure.output(self._channel, True)
        return self

    def off(self) -> SourceMeasureChannelFacade:
        self._source_measure.output(self._channel, False)
        return self

    def get_voltage(self) -> TypedMeasurementResult:
        return self._source_measure.read_voltage(self._channel)

    def get_current(self) -> TypedMeasurementResult:
        return self._source_measure.read_current(self._channel)

    def get_output_state(self) -> bool:
        return self._source_measure.get_output_state(self._channel)


class SourceMeasure(Instrument[SourceMeasureConfig]):
    """Generic declarative source-measure driver.

    The driver contains no vendor command or status tables. Wire commands and
    measurement header interpretation are supplied by the profile's SCPI data.
    """

    config: SourceMeasureConfig
    OPERATION_CONTRACT: tuple[OperationDescriptor, ...] = (
        OperationDescriptor("id", safety_class="read"),
        OperationDescriptor("set_voltage"),
        OperationDescriptor("set_current"),
        OperationDescriptor("force_current"),
        OperationDescriptor("output"),
        OperationDescriptor("read_voltage", safety_class="read"),
        OperationDescriptor("read_current", safety_class="read"),
        OperationDescriptor("get_output_state", safety_class="read", required=False),
    )

    def __init__(self, config: SourceMeasureConfig, backend: Any, **kwargs: Any) -> None:
        super().__init__(config=config, backend=backend, **kwargs)
        scpi_data = config.scpi.model_dump(exclude_none=True) if config.scpi else {}
        self.scpi_engine = SCPIEngine(scpi_data, variant=config.scpi_variant)
        self._states = {spec.channel_id: _ChannelState() for spec in config.channels}
        self._requested_audit: dict[int, dict[str, Any]] = {
            spec.channel_id: {} for spec in config.channels
        }
        self._io_lock = RLock()

    def _spec(self, channel: int):
        if isinstance(channel, bool) or not isinstance(channel, numbers.Integral):
            raise InstrumentParameterError(
                parameter="channel", value=channel, message="must be an integer"
            )
        try:
            return next(spec for spec in self.config.channels if spec.channel_id == channel)
        except StopIteration as exc:
            valid = [spec.channel_id for spec in self.config.channels]
            raise InstrumentParameterError(
                parameter="channel",
                value=channel,
                valid_range=tuple(valid),
                message=f"configured channels are {valid}",
            ) from exc

    def _state(self, channel: int) -> _ChannelState:
        self._spec(channel)
        return self._states[channel]

    def _remember_requested(self, channel: int, **values: Any) -> None:
        self._requested_audit[channel].update(values)

    def _invalidate_channel(self, channel: int) -> None:
        """Discard active proof after an uncertain write; retain audit inputs."""
        state = self._state(channel)
        for name in (
            "mode",
            "voltage",
            "current_limit",
            "current",
            "voltage_compliance",
        ):
            value = getattr(state, name)
            if value is not None:
                self._requested_audit[channel].setdefault(name, value)
            setattr(state, name, None)
        state.output = None

    @staticmethod
    def _finite(value: float, name: str) -> None:
        if (
            isinstance(value, bool)
            or not isinstance(value, numbers.Real)
            or not math.isfinite(float(value))
        ):
            raise InstrumentParameterError(parameter=name, value=value, message="must be finite")

    @staticmethod
    def _check_range(value: float, range_spec: Any, name: str) -> None:
        SourceMeasure._finite(value, name)
        if not range_spec.min <= value <= range_spec.max:
            raise InstrumentParameterError(
                parameter=name,
                value=value,
                valid_range=(range_spec.min, range_spec.max),
                message=f"{name} must be within the configured static rating",
            )

    def validate_channel_settings(
        self,
        channel: int,
        *,
        voltage: float | None = None,
        current_limit: float | None = None,
        current: float | None = None,
        voltage_compliance: float | None = None,
    ) -> None:
        """Validate a complete requested setting without performing I/O."""
        spec = self._spec(channel)
        if voltage is not None:
            self._check_range(voltage, spec.voltage_range, "voltage")
        if current_limit is not None:
            self._check_range(current_limit, spec.current_limit_range, "current_limit")
        if current is not None:
            self._check_range(current, spec.current_range, "current")
        if voltage_compliance is not None:
            self._check_range(
                voltage_compliance, spec.voltage_compliance_range, "voltage_compliance"
            )

    def _build(self, alias: str, **params: Any) -> list[str]:
        try:
            return self.scpi_engine.build(alias, **params)
        except KeyError as exc:
            raise InstrumentConfigurationError(
                self.config.model, f"profile lacks SCPI alias {alias!r}"
            ) from exc

    def _send_profile_commands(self, commands: list[str]) -> None:
        capabilities = self.config.capabilities or {}
        for command in commands:
            self._send_command(command, skip_check=capabilities.get("error_queue") is False)

    def _query_profile(self, alias: str, **params: Any) -> str:
        commands = self._build(alias, **params)
        capabilities = self.config.capabilities or {}
        for command in commands[:-1]:
            self._send_profile_commands([command])
        return self._query(commands[-1], skip_check=capabilities.get("error_queue") is False)

    def _set_voltage_settings(
        self, channel: int, voltage: float | None, current_limit: float | None
    ) -> None:
        with self._io_lock:
            self.validate_channel_settings(channel, voltage=voltage, current_limit=current_limit)
            state = self._state(channel)
            if voltage is None and current_limit is None:
                return
            requested_voltage = state.voltage if voltage is None else float(voltage)
            requested_limit = state.current_limit if current_limit is None else float(current_limit)
            self._remember_requested(
                channel,
                **({"voltage": float(voltage)} if voltage is not None else {}),
                **({"current_limit": float(current_limit)} if current_limit is not None else {}),
            )
            if requested_voltage is not None and requested_limit is not None:
                commands = self._build(
                    "force_voltage",
                    channel=channel,
                    voltage=requested_voltage,
                    current_limit=requested_limit,
                )
                try:
                    self._send_profile_commands(commands)
                except Exception:
                    self._invalidate_channel(channel)
                    raise
                state.mode = "voltage"
            if voltage is not None:
                state.voltage = float(voltage)
            if current_limit is not None:
                state.current_limit = float(current_limit)

    def set_voltage(self, channel: int, voltage: float) -> None:
        self._set_voltage_settings(channel, voltage, None)

    def set_current(self, channel: int, current_limit: float) -> None:
        self._set_voltage_settings(channel, None, current_limit)

    def force_current(self, channel: int, current: float, voltage_compliance: float) -> None:
        with self._io_lock:
            self.validate_channel_settings(
                channel, current=current, voltage_compliance=voltage_compliance
            )
            commands = self._build(
                "force_current",
                channel=channel,
                current=float(current),
                voltage_compliance=float(voltage_compliance),
            )
            self._remember_requested(
                channel,
                current=float(current),
                voltage_compliance=float(voltage_compliance),
            )
            try:
                self._send_profile_commands(commands)
            except Exception:
                self._invalidate_channel(channel)
                raise
            state = self._state(channel)
            state.mode = "current"
            state.current = float(current)
            state.voltage_compliance = float(voltage_compliance)

    def output(self, channel: int | list[int], state: bool = True) -> None:
        with self._io_lock:
            if not isinstance(state, bool):
                raise InstrumentParameterError(
                    parameter="state", value=state, message="must be bool"
                )
            channels = [channel] if isinstance(channel, int) else list(channel)
            states = [(ch, self._state(ch)) for ch in channels]
            if state:
                for ch, channel_state in states:
                    if channel_state.mode == "voltage" and (
                        channel_state.voltage is None or channel_state.current_limit is None
                    ):
                        raise InstrumentParameterError(
                            parameter="output",
                            value=True,
                            message=f"channel {ch} lacks voltage/compliance pairing",
                        )
                    if channel_state.mode == "current" and (
                        channel_state.current is None or channel_state.voltage_compliance is None
                    ):
                        raise InstrumentParameterError(
                            parameter="output",
                            value=True,
                            message=f"channel {ch} lacks current/compliance pairing",
                        )
                    if channel_state.mode is None:
                        raise InstrumentParameterError(
                            parameter="output",
                            value=True,
                            message=f"channel {ch} has no configured source state",
                        )
            alias = "output_on" if state else "output_off"
            command_groups = [self._build(alias, channel=ch) for ch, _ in states]
            for ch, _ in states:
                self._remember_requested(ch, output=state)
            try:
                for commands, (_, channel_state) in zip(command_groups, states, strict=True):
                    self._send_profile_commands(commands)
                    channel_state.output = state
            except Exception:
                for ch, _ in states:
                    self._invalidate_channel(ch)
                raise

    def preflight_channel(
        self,
        channel: int,
        required: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        """Validate a channel and required profile packets without I/O.

        The default set is suitable for workflows that need both actuation and
        verified readback. Missing aliases or response metadata fail before any
        command can be sent.
        """
        with self._io_lock:
            self._spec(channel)
            required_aliases = tuple(
                required
                or (
                    "output_on",
                    "output_off",
                    "measure_voltage",
                    "measure_current",
                    "get_output_state",
                )
            )
            packets: dict[str, list[str]] = {}
            for alias in required_aliases:
                if not self.scpi_engine.validate_presence([alias])[alias]:
                    raise InstrumentConfigurationError(
                        self.config.model, f"preflight requires missing SCPI alias {alias!r}"
                    )
                if alias in {"measure_voltage", "measure_current"}:
                    profile = self._response_profile(alias)
                    if not profile.get("header_fields") or not profile.get("status_map"):
                        raise InstrumentConfigurationError(
                            self.config.model,
                            f"preflight requires response metadata for {alias!r}",
                        )
                if alias == "get_output_state":
                    self._state_map(alias)
                packets[alias] = self._build(alias, channel=channel)
            return {"channel": channel, "required": required_aliases, "packets": packets}

    def get_output_state(self, channel: int) -> bool:
        with self._io_lock:
            self._spec(channel)
            if not self.scpi_engine.validate_presence(["get_output_state"])["get_output_state"]:
                raise NotImplementedError("profile does not provide a verified output-state query")
            raw = self._query_profile("get_output_state", channel=channel)
        token = str(raw).strip().upper()
        states = self._state_map("get_output_state")
        try:
            return states[token]
        except KeyError as exc:
            raise InstrumentDataError(self.config.model, f"unknown output state {raw!r}") from exc

    def channel(self, channel: int) -> SourceMeasureChannelFacade:
        self._spec(channel)
        return SourceMeasureChannelFacade(self, channel)

    def id(self) -> str:
        with self._io_lock:
            return str(self._query_profile("identify")).strip()

    def _response_profile(self, alias: str) -> dict[str, Any]:
        data = self.config.scpi.model_dump(exclude_none=True) if self.config.scpi else {}
        for section in ("queries", "commands"):
            item = (data.get(section) or {}).get(alias)
            if isinstance(item, dict):
                return dict(item.get("response") or item)
        raise InstrumentConfigurationError(
            self.config.model, f"profile lacks response metadata for {alias!r}"
        )

    def _state_map(self, alias: str) -> dict[str, bool]:
        """Return a profile state map whose values are strictly booleans."""
        states = self._response_profile(alias).get("state_map")
        if (
            not isinstance(states, dict)
            or not states
            or any(type(value) is not bool for value in states.values())
        ):
            raise InstrumentConfigurationError(
                self.config.model,
                f"profile state_map for {alias!r} must map tokens to booleans",
            )
        return states

    def _measurement_quantity(
        self, reading: float, channel: int, unit: str, function: str
    ) -> Quantity:
        reason = f"{self.config.model} {function} channel {channel}: no measurement accuracy metadata; nominal-only."
        quantity = nominal_measurement_quantity(
            reading, unit, function=function, output_name=f"{function}_ch{channel}", reason=reason
        )
        spec = (self.config.measurement_accuracy or {}).get(f"{function}_ch{channel}")
        if spec is None:
            return quantity
        channel_spec = self._spec(channel)
        range_spec = channel_spec.voltage_range if unit == "V" else channel_spec.current_range
        context = UncertaintyContext(
            reading=reading,
            unit=unit,
            function=function,
            range_value=range_spec.max,
            range_unit=unit,
            resolution=range_spec.resolution,
            channel=channel,
            source_key=f"{self._uncertainty_source_key()}:ch{channel}:{function}:{range_spec.max}",
            traceability=resolve_traceability_ref(
                self.config.calibration_certificates,
                function=function,
                channel=channel,
                range_value=range_spec.max,
                unit=unit,
            ),
        )
        evaluated = nonzero_uncertainty_quantity(
            spec,
            context,
            logger=self._logger,
            label=f"accuracy spec {function}_ch{channel}",
            strict=self.config.uncertainty_strict,
        )
        return evaluated or quantity

    def _read_measurement(
        self, channel: int, alias: str, unit: str, function: str
    ) -> TypedMeasurementResult:
        self._spec(channel)
        with self._io_lock:
            raw = str(self._query_profile(alias, channel=channel)).strip()
        profile = self._response_profile(alias)
        width = int(profile.get("header_width", len(profile.get("header_fields", []))))
        start = int(profile.get("value_start", width))
        if len(raw) <= start:
            raise InstrumentDataError(
                self.config.model, f"measurement response is too short: {raw!r}"
            )
        header = raw[:width]
        fields = list(profile.get("header_fields", []))
        values = dict(zip(fields, header, strict=False))
        try:
            result_channel = int(values["channel"]) if "channel" in values else channel
            reading = float(raw[start:])
        except ValueError as exc:
            raise InstrumentDataError(
                self.config.model, f"invalid measurement response {raw!r}"
            ) from exc
        if result_channel != channel:
            raise InstrumentDataError(
                self.config.model,
                f"measurement header channel {result_channel} != requested {channel}",
            )
        status = str(values.get("status", ""))
        status_map = profile.get("status_map", {}) or {}
        if status not in status_map:
            raise InstrumentDataError(
                self.config.model, f"unknown measurement status {status!r} in {raw!r}"
            )
        expected_type = profile.get("expected_measurement_type")
        measurement_type = str(values.get("measurement_type", ""))
        if expected_type is not None and measurement_type != str(expected_type):
            raise InstrumentDataError(
                self.config.model,
                f"measurement type {measurement_type!r} != expected {expected_type!r}",
            )
        compliance_statuses = {str(item) for item in profile.get("compliance_statuses", [])}
        status_metadata = dict((profile.get("status_metadata") or {}).get(status) or {})
        return TypedMeasurementResult(
            value=self._measurement_quantity(reading, channel, unit, function),
            header=header,
            channel=result_channel,
            status=status,
            measurement_type=measurement_type,
            compliance=(status in compliance_statuses) if compliance_statuses else None,
            status_text=status_map.get(status),
            status_metadata=status_metadata,
            instrument=self.config.model,
        )

    def read_voltage(self, channel: int) -> TypedMeasurementResult:
        return self._read_measurement(channel, "measure_voltage", "V", "read_voltage")

    def read_current(self, channel: int) -> TypedMeasurementResult:
        return self._read_measurement(channel, "measure_current", "A", "read_current")

    def get_channel_configuration(self, channel: int) -> MappingProxyType:
        with self._io_lock:
            state = self._state(channel)
            return MappingProxyType(
                {
                    "mode": state.mode,
                    "voltage": state.voltage,
                    "current_limit": state.current_limit,
                    "current": state.current,
                    "voltage_compliance": state.voltage_compliance,
                    "output": state.output,
                    "requested": MappingProxyType(dict(self._requested_audit[channel])),
                }
            )

    def get_configuration(self) -> MappingProxyType:
        with self._io_lock:
            return MappingProxyType(
                {channel: self.get_channel_configuration(channel) for channel in self._states}
            )
