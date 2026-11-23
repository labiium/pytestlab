"""Profile-defined switching wire protocols."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field
from re import Pattern
from threading import RLock
from typing import Any

from .devices.base import _BackendFactory
from .errors import InstrumentConfigurationError
from .profile_transport import ProfileTransport


@dataclass(frozen=True, slots=True)
class ObservedRouteVerification:
    """Typed proof derived from a profile-declared connection readback."""

    route_name: str
    expected_connected: bool
    connected: bool
    qualified: bool
    settled: bool
    actor: str = "physical_resource"
    frame: str = "electrical"
    details: Mapping[str, Any] = field(default_factory=dict)


class ProfileSwitchBackend:
    """Transport-neutral switch protocol loaded from a ``switch`` profile."""

    def __init__(self, io: Any, spec: Mapping[str, Any]) -> None:
        if not isinstance(spec, Mapping):
            raise InstrumentConfigurationError(
                "switch", "profile 'switch' section must be a mapping"
            )
        self._io_source = io
        self._spec = dict(spec)
        self._allocation_lock = RLock()
        self._transport_instance: ProfileTransport | None = None
        crosspoint = spec.get("crosspoint", {})
        if not isinstance(crosspoint, Mapping):
            raise InstrumentConfigurationError("switch", "crosspoint must be a mapping")
        pattern = crosspoint.get("pattern")
        if not isinstance(pattern, str) or not pattern:
            raise InstrumentConfigurationError("switch", "crosspoint.pattern is required")
        self._pattern: Pattern[str] = re.compile(pattern)
        self._fields = tuple(str(item) for item in crosspoint.get("fields", ()))
        self._constraints = dict(crosspoint.get("constraints", {}) or {})
        self._commands = dict(spec.get("commands", {}) or {})
        self._queries = dict(spec.get("queries", {}) or {})
        self._requires_context = tuple(str(item) for item in spec.get("requires_context", ()))

    @property
    def _io(self) -> Any:
        with self._allocation_lock:
            if isinstance(self._io_source, _BackendFactory):
                self._io_source = self._io_source.build()
            return self._io_source

    @property
    def _transport(self) -> ProfileTransport:
        with self._allocation_lock:
            if self._transport_instance is None:
                self._transport_instance = ProfileTransport(self._io, self._spec)
            return self._transport_instance

    def connect(self) -> None:
        self._transport.connect()

    def disconnect(self) -> None:
        if not isinstance(self._io_source, _BackendFactory):
            self._io_source.disconnect()

    def close(self) -> None:
        if not isinstance(self._io_source, _BackendFactory):
            self._io_source.close()

    def set_timeout(self, timeout_ms: int) -> None:
        self._io.set_timeout(timeout_ms)

    def get_timeout(self) -> int:
        return self._io.get_timeout()

    def write(self, command: str) -> None:
        self._transport.write(command)

    def query(self, command: str, delay: float | None = None) -> str:
        return self._transport.query(command, delay=delay)

    def query_raw(self, command: str, delay: float | None = None) -> bytes:
        return self._transport.query_raw(command, delay=delay)

    def read_status_byte(self) -> int:
        return self._transport.read_status_byte()

    @property
    def is_simulated(self) -> bool:
        return getattr(self._io, "is_simulated", False) is True

    def supports_native_status_byte(self) -> bool:
        return self._transport.supports_native_status_byte()

    @property
    def lock(self) -> RLock:
        return self._transport.lock

    @property
    def requires_context(self) -> tuple[str, ...]:
        return self._requires_context

    def _fields_for(self, channel: str) -> dict[str, Any]:
        match = self._pattern.fullmatch(channel)
        if match is None:
            raise ValueError(f"switch channel does not match profile grammar: {channel!r}")
        values: dict[str, Any] = {key: value for key, value in match.groupdict().items()}
        values["channel"] = channel
        for name in self._fields:
            if name not in values:
                raise ValueError(f"profile crosspoint field {name!r} was not captured")
        for name, constraint in self._constraints.items():
            value = values.get(name)
            if value is None:
                continue
            try:
                numeric = int(value)
            except (TypeError, ValueError):
                numeric = value
            if isinstance(constraint, Mapping):
                if (
                    constraint.get("min") is not None or constraint.get("max") is not None
                ) and not isinstance(numeric, int):
                    raise ValueError(f"switch field {name} must be numeric")
                if constraint.get("min") is not None and numeric < constraint["min"]:
                    raise ValueError(f"switch field {name} is below profile minimum")
                if constraint.get("max") is not None and numeric > constraint["max"]:
                    raise ValueError(f"switch field {name} is above profile maximum")
                choices = constraint.get("choices")
                if choices is not None and numeric not in choices and value not in choices:
                    raise ValueError(f"switch field {name} is not an allowed profile value")
            elif (
                isinstance(constraint, (list, tuple, set))
                and numeric not in constraint
                and value not in constraint
            ):
                raise ValueError(f"switch field {name} is not an allowed profile value")
            values[name] = numeric
        return values

    def command_for(self, action: str, channel: str | None = None) -> str:
        template = self._commands.get(action)
        if not isinstance(template, str):
            raise NotImplementedError(f"switch action is not declared by profile: {action}")
        values = self._fields_for(channel) if channel is not None else {"channel": ""}
        try:
            return template.format(**values)
        except (KeyError, ValueError) as exc:
            raise ValueError(f"profile switch command {action!r} cannot format channel") from exc

    def has_query(self, name: str) -> bool:
        return name in self._queries

    def query_response_spec(self, name: str) -> Mapping[str, Any]:
        spec = self._queries.get(name)
        if not isinstance(spec, Mapping):
            return {}
        response = spec.get("response", {})
        return response if isinstance(response, Mapping) else {}

    @staticmethod
    def _validate_query_fields(spec: Mapping[str, Any], fields: Mapping[str, Any]) -> None:
        parameters = spec.get("parameters", {})
        if not isinstance(parameters, Mapping):
            return
        for name, rule in parameters.items():
            if name not in fields or not isinstance(rule, Mapping):
                continue
            value = fields[name]
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"switch query field {name} must be an integer")
            if rule.get("min") is not None and value < rule["min"]:
                raise ValueError(f"switch query field {name} is below profile minimum")
            if rule.get("max") is not None and value > rule["max"]:
                raise ValueError(f"switch query field {name} is above profile maximum")
            choices = rule.get("choices")
            if choices is not None:
                normalized = {
                    choice.get("token") if isinstance(choice, Mapping) else choice
                    for choice in choices
                }
                if value not in normalized:
                    raise ValueError(f"switch query field {name} is not an allowed profile value")

    def query_for(self, name: str, **fields: Any) -> str:
        spec = self._queries.get(name)
        if isinstance(spec, str):
            template = spec
            query_spec: Mapping[str, Any] = {}
        elif isinstance(spec, Mapping):
            template = spec.get("template")
            query_spec = spec
        else:
            raise NotImplementedError(f"switch query is not declared by profile: {name}")
        if not isinstance(template, str) or not template:
            raise ValueError(f"profile switch query {name!r} has no template")
        self._validate_query_fields(query_spec, fields)
        try:
            return template.format(**fields)
        except (KeyError, ValueError) as exc:
            raise ValueError(f"profile switch query {name!r} cannot format fields") from exc

    def command_for_fields(self, action: str, **fields: Any) -> str:
        template = self._commands.get(action)
        if not isinstance(template, str) or not template:
            raise NotImplementedError(f"switch action is not declared by profile: {action}")
        try:
            return template.format(**fields)
        except (KeyError, ValueError) as exc:
            raise ValueError(f"profile switch action {action!r} cannot format fields") from exc

    def send_command(self, command: str) -> None:
        self._send_action(command)

    def query_action(self, name: str, **fields: Any) -> str:
        command = self.query_for(name, **fields)
        return self._transport.exchange(command, expect_response=True, validate_success=False)

    def query_mapped_bool(self, name: str, **fields: Any) -> bool:
        response = self.query_response_spec(name)
        if response.get("type") != "state_map":
            raise NotImplementedError(
                f"switch query {name!r} requires an explicit boolean state map"
            )
        values = response.get("values", response.get("map"))
        if (
            not isinstance(values, Mapping)
            or not values
            or not all(type(value) is bool for value in values.values())
        ):
            raise NotImplementedError(
                f"switch query {name!r} requires an explicit boolean state map"
            )
        raw = self.query_action(name, **fields).strip()
        if raw in values:
            return values[raw]
        normalized = raw.upper()
        for key, value in values.items():
            if str(key).upper() == normalized:
                return value
        raise ValueError(f"profile query {name!r} returned unmapped state {raw!r}")

    def verify_route(
        self, name: str, *, expected_connected: bool = True
    ) -> ObservedRouteVerification:
        connected = self.query_mapped_bool("connection_state")
        return ObservedRouteVerification(
            route_name=name,
            expected_connected=expected_connected,
            connected=connected,
            qualified=connected is expected_connected,
            settled=True,
            details={"query": "connection_state"},
        )

    def preflight(self, action: str, channels: list[str]) -> list[str]:
        commands = [self.command_for(action, channel) for channel in channels]
        if not commands:
            raise ValueError("switch operation requires at least one channel")
        return commands

    def apply_route(self, channels: list[str]) -> list[str]:
        commands = self.preflight("connect", channels)
        for command in commands:
            self._send_action(command)
        return commands

    def open_route(self, channels: list[str]) -> list[str]:
        commands = self.preflight("open", channels)
        for command in commands:
            self._send_action(command)
        return commands

    def clear(self) -> str:
        command = self.command_for("clear")
        self._send_action(command)
        return command

    def _send_action(self, command: str) -> None:
        expect_response = self._transport.expects_response()
        self._transport.exchange(command, expect_response=expect_response)

    def identity(self) -> str:
        return self._transport.exchange(
            self.command_for("identity"), expect_response=True, validate_success=False
        )


__all__ = ["ObservedRouteVerification", "ProfileSwitchBackend"]
