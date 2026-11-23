"""Profile-driven generic motion backend.

This module closes the gap between the instrument side of PyTestLab - where
"100% of the instrument-specific SCPI lives in the YAML profile" via
:class:`pytestlab.instruments.scpi_engine.SCPIEngine` - and the motion side,
where :class:`pytestlab.motion.MotionDevice` previously only offered either a
per-device Python typed backend or invented JSON wire commands.

:class:`ProfileMotionBackend` is a typed motion backend whose wire protocol,
capabilities, response parsing, and success convention live in ``motion:``.
Shared framing and timing requirements live in ``transport:``.
:class:`ProfileMotionDevice` is the matching generic device class; register it
for a device type (e.g. ``motion_stage``) and any compliant profile becomes a
working motion device with no per-device Python.

Profile schema::

    transport:
      min_command_interval_s: 0.1
    motion:
      axes:
        - {name: x, units: mm, minimum: -100.0, maximum: 100.0}
        - {name: y, units: mm, minimum: -100.0, maximum: 100.0}
      frames: [machine]                      # optional, default [machine]
      supports: [set_home, move_home, move_absolute, ...]  # optional subset gate
      relative_from_position: [x, y]         # read and write in the same frame
      wire_scale: 1000.0                     # interface units -> wire units
      success_prefix: "0"                    # optional response convention
      commands:                              # motion writes
        set_home:      {template: "ORIGIN STORE"}
        move_home:     {template: "ORIGIN MOVE"}
        move_absolute: {template: "34 {x} {y} H"}
      queries:                               # motion reads
        position:
          template: "31"
          response: {type: axis_tuple, skip: 1, axes: [x, y, z], scale: 0.001}
        status:
          template: "31"
          response: {type: status_field, index: 0, ok_value: "0"}
      operations:                            # device-specific extra writes
        set_chuck_vacuum:
          template: "05 {state}"
          parameters: {...}                  # SCPIEngine parameter schema
        move_to_contact: {template: "37"}

``set_home`` defines the controller home; ``move_home`` moves to it.
``home`` is reserved for a profile-declared homing/reference operation.

Move operations receive the motion layer's ``position``/``offset`` axis
mapping; the backend validates the axes against the declared axes, scales
values by ``wire_scale`` (interface -> wire units), and formats them into the
template. To support checked relative moves, a profile may declare
``relative_from_position``: the complete set of axes its absolute command
writes. The position query and absolute command must share units and a
coordinate reference. The backend snapshots position, adds the requested
offsets, checks the absolute target, and sends that target. It does not send a
native relative command after the read. A bounded profile without this
contract cannot use a native relative command.
Query responses are parsed by generic response types:

- ``axis_tuple``: whitespace-separated tokens; ``skip`` leading tokens, map
  the next ``len(axes)`` tokens to ``axes`` names, multiply by ``scale``.
- ``status_field``: token at ``index`` compared to ``ok_value``; yields a
  motion-status mapping (``settled``/``fault``).
- ``scalar``: single numeric token scaled by ``scale``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from .devices.base import _BackendFactory
from .errors import InstrumentConfigurationError
from .instruments.scpi_engine import SCPIEngine
from .motion import DEFAULT_MOTION_OPERATIONS
from .motion import MotionCapabilities
from .motion import MotionDevice
from .motion import MotionFaultError
from .profile_transport import ProfileResponseError
from .profile_transport import ProfileTransport

_PROFILE_MOTION_OPERATIONS = DEFAULT_MOTION_OPERATIONS | {
    "set_home",
    "move_home",
    # Native prober primitives. These are motion capabilities, not opaque
    # profile operations, so generic devices can expose them consistently.
    "contact",
    "move_to_align",
    "separate",
    "align",
    "move_to_load",
    "set_vacuum",
    "configure_chuck",
}


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number")
    return number


def _has_axis_bounds(capabilities: MotionCapabilities) -> bool:
    return any(axis.minimum is not None or axis.maximum is not None for axis in capabilities.axes)


def _relative_axes(spec: Mapping[str, Any]) -> tuple[str, ...]:
    axes = spec.get("relative_from_position")
    if axes is None:
        return ()
    if (
        not isinstance(axes, (list, tuple))
        or not axes
        or any(not isinstance(axis, str) or not axis for axis in axes)
        or len(set(axes)) != len(axes)
    ):
        raise ValueError("relative_from_position must list distinct absolute command axes")
    return tuple(axes)


def _profile_supports(spec: Mapping[str, Any]) -> frozenset[str]:
    commands = spec.get("commands") or {}
    queries = spec.get("queries") or {}
    implemented = (set(commands) | set(queries)) & _PROFILE_MOTION_OPERATIONS
    if "status" in queries:
        implemented.add("wait")
    if _relative_axes(spec):
        if "move_absolute" not in commands or "position" not in queries:
            raise ValueError(
                "relative_from_position requires a position query and absolute command"
            )
        if "move_absolute" in (spec.get("operations") or {}):
            raise ValueError("relative_from_position cannot use a shadowed absolute command")
        implemented.add("move_relative")
    declared = spec.get("supports", implemented)
    if isinstance(declared, str):
        raise ValueError("motion supports must be a list of capability names")
    supports = frozenset(declared)
    missing = supports - implemented
    if missing:
        raise ValueError(f"motion capabilities have no profile implementation: {sorted(missing)}")
    return supports


def _profile_capabilities(spec: Mapping[str, Any], supports: frozenset[str]) -> MotionCapabilities:
    declaration = {**spec, "supports": supports}
    if "units" not in declaration:
        axis_units = {
            axis.get("units", "mm") for axis in spec.get("axes", ()) if isinstance(axis, Mapping)
        }
        if len(axis_units) == 1:
            declaration["units"] = tuple(axis_units)
        elif len(axis_units) > 1:
            raise ValueError("mixed axis units require an explicit motion units declaration")
    capabilities = MotionCapabilities.from_mapping(declaration)
    relative_axes = _relative_axes(spec)
    if "move_relative" in supports:
        if relative_axes:
            if not {"position", "move_absolute"} <= supports:
                raise ValueError(
                    "relative_from_position requires enabled position and move_absolute"
                )
            if set(relative_axes) - set(capabilities.axis_map):
                raise ValueError("relative_from_position contains undeclared axes")
        elif _has_axis_bounds(capabilities):
            declaration["supports"] = supports - {"move_relative"}
            return MotionCapabilities.from_mapping(declaration)
    return capabilities


class ProfileMotionBackend:
    """Typed motion backend built entirely from a profile ``motion:`` section."""

    def __init__(self, io: Any, spec: Mapping[str, Any]) -> None:
        if not isinstance(spec, Mapping):
            raise InstrumentConfigurationError(
                "motion", "profile 'motion' section must be a mapping"
            )
        self._spec = dict(spec)
        self._io = io
        self._transport = ProfileTransport(io, spec)
        self._exchange_lock = self._transport.lock
        self.query_delay_s = self._transport.query_delay_s
        self._wire_scale = _number(spec.get("wire_scale", 1.0), "wire_scale")
        if self._wire_scale <= 0:
            raise ValueError("wire_scale must be positive")

        def entries(section: str) -> dict[str, Any]:
            return {
                name: {"template": value} if isinstance(value, str) else dict(value)
                for name, value in (spec.get(section, {}) or {}).items()
            }

        commands = entries("commands")
        self._commands = commands
        operations = entries("operations")
        self._queries = entries("queries")
        self._engine = SCPIEngine(
            {"commands": {**commands, **operations}, "queries": self._queries}
        )
        self._operations = frozenset(operations)
        self._operation_specs = operations
        self._supports = _profile_supports(spec)

    # .............. DeviceIO forwarding .............. #

    def connect(self) -> None:
        self._transport.connect()

    def disconnect(self) -> None:
        self._io.disconnect()

    def close(self) -> None:
        self._io.close()

    @property
    def is_simulated(self) -> bool:
        return getattr(self._io, "is_simulated", False) is True

    def supports_native_status_byte(self) -> bool:
        return self._transport.supports_native_status_byte()

    def read_status_byte(self) -> int:
        """Forward native bus status independently of motion query templates."""
        return self._transport.read_status_byte()

    def set_timeout(self, timeout_ms: int) -> None:
        self._io.set_timeout(timeout_ms)

    def get_timeout(self) -> int:
        return self._io.get_timeout()

    def write(self, cmd: str) -> None:
        self._io.write(cmd)

    def query(self, cmd: str, delay: float | None = None) -> str:
        return self._io.query(cmd, delay=delay)

    def query_raw(self, cmd: str, delay: float | None = None) -> bytes:
        return self._io.query_raw(cmd, delay=delay)

    # .............. wire exchange .............. #

    def _exchange(self, command: str, *, expect_response: bool = False) -> str:
        try:
            return self._transport.exchange(command, expect_response=expect_response)
        except ProfileResponseError as error:
            raise MotionFaultError(f"motion_error_response: {error}") from error

    # .............. typed motion hooks .............. #

    def get_motion_capabilities(self) -> MotionCapabilities:
        return _profile_capabilities(self._spec, self._supports)

    def _validate_coordinates(self, fields: Mapping[str, Any]) -> None:
        capabilities = self.get_motion_capabilities()
        units = fields.get("units")
        if units is not None and units not in capabilities.units:
            raise ValueError(f"unsupported motion units: {units}")
        frame = fields.get("frame")
        if frame is not None and frame not in capabilities.frame_map:
            raise ValueError(f"unsupported motion frame: {frame}")
        group = fields.get("axis_group")
        if group is not None:
            declared = {item.name: item for item in capabilities.axis_groups}
            name = group.get("name") if isinstance(group, Mapping) else group
            if name not in declared:
                raise ValueError(f"unsupported motion axis group: {name}")
            requested_axes = set(fields.get("position", fields.get("offset", {})))
            if requested_axes - set(declared[name].axes):
                raise ValueError(f"requested axes are outside motion axis group: {name}")
            if isinstance(group, Mapping) and tuple(group.get("axes", ())) != declared[name].axes:
                raise ValueError(f"motion axis group disagrees with profile: {name}")

    def _expects_response(self, spec: Mapping[str, Any]) -> bool:
        return self._transport.expects_response(spec)

    def _move_parameters(
        self, operation: str, mapping: Any, fields: Mapping[str, Any]
    ) -> dict[str, Any]:
        if not isinstance(mapping, Mapping) or not mapping:
            raise ValueError(f"{operation} requires a non-empty axis mapping")
        limits = self.get_motion_capabilities().axis_map
        unknown = set(mapping) - set(limits)
        if unknown:
            raise ValueError(f"undeclared motion axes: {sorted(unknown)}")
        params = {
            key: value
            for key, value in fields.items()
            if key not in {"position", "offset"} and key not in limits
        }
        for axis, value in mapping.items():
            number = _number(value, axis)
            axis_spec = limits[axis]
            if operation == "move_absolute":
                if axis_spec.minimum is not None and number < axis_spec.minimum:
                    raise ValueError(f"{axis}={number} below axis minimum {axis_spec.minimum}")
                if axis_spec.maximum is not None and number > axis_spec.maximum:
                    raise ValueError(f"{axis}={number} above axis maximum {axis_spec.maximum}")
            params[axis] = _number(number * self._wire_scale, axis)
        return params

    def _relative_command(
        self, *, operation_id: str, fields: Mapping[str, Any], axes: tuple[str, ...]
    ) -> dict[str, Any]:
        offset = fields.get("offset")
        if not isinstance(offset, Mapping) or not offset:
            raise ValueError("move_relative requires a non-empty axis mapping")
        unknown = set(offset) - set(axes)
        if unknown:
            raise ValueError(f"unsupported relative motion axes: {sorted(unknown)}")
        deltas = {axis: _number(value, axis) for axis, value in offset.items()}
        if fields.get("axis_group") is not None:
            self._validate_coordinates(
                {"axis_group": fields["axis_group"], "position": dict.fromkeys(axes)}
            )
        query_fields = {key: fields[key] for key in ("frame", "units") if key in fields}
        with self._exchange_lock:
            try:
                current = self.motion_query("position", **query_fields)
                if not isinstance(current, Mapping):
                    raise ValueError("expected an axis mapping")
                start = {axis: _number(current[axis], axis) for axis in axes}
            except (KeyError, TypeError, ValueError, OverflowError) as error:
                raise MotionFaultError(f"relative motion position unavailable: {error}") from error
            target = {axis: start[axis] + deltas.get(axis, 0.0) for axis in axes}
            params = self._move_parameters("move_absolute", target, fields)
            receipt = self._dispatch_motion("move_absolute", operation_id, params)
        return {**receipt, "target": target}

    def motion_command(self, operation: str, *, operation_id: str, **fields: Any) -> dict[str, Any]:
        capabilities = self.get_motion_capabilities()
        if operation not in capabilities.supports:
            if operation == "move_relative" and _has_axis_bounds(capabilities):
                raise NotImplementedError(
                    "relative motion with axis bounds requires relative_from_position"
                )
            raise NotImplementedError(f"profile motion command not declared: {operation}")
        self._validate_coordinates(fields)
        if operation == "move_relative" and (axes := _relative_axes(self._spec)):
            return self._relative_command(operation_id=operation_id, fields=fields, axes=axes)
        if operation not in self._commands:
            raise NotImplementedError(f"profile motion command not declared: {operation}")
        command_spec = self._commands[operation]
        mapping = fields.get("offset" if operation == "move_relative" else "position")
        if operation in {"home", "set_home", "move_home"}:
            selected = fields.get("axes")
            axes = set(self.get_motion_capabilities().axis_map)
            if selected is not None and set(selected) != axes:
                raise NotImplementedError(
                    f"profile {operation} command only supports all declared axes"
                )
            params: dict[str, Any] = dict(fields)
        elif operation in {"move_absolute", "move_relative"}:
            params = self._move_parameters(operation, mapping, fields)
        else:
            params = dict(fields)
            if (
                operation == "stop"
                and fields.get("mode") != "controlled"
                and "{mode}" not in command_spec["template"]
            ):
                raise NotImplementedError("profile stop command does not declare this stop mode")
        return self._dispatch_motion(operation, operation_id, params)

    def _dispatch_motion(
        self, operation: str, operation_id: str, params: Mapping[str, Any]
    ) -> dict[str, Any]:
        command_spec = self._commands[operation]
        commands = self._engine.build(operation, **params)
        with self._exchange_lock:
            for command in commands:
                self._exchange(command, expect_response=self._expects_response(command_spec))
        # A transport acknowledgement is not proof of physical completion.
        return {"state": command_spec.get("result_state", "running"), "operation_id": operation_id}

    def motion_query(self, name: str, **kwargs: Any) -> Any:
        if name not in self._queries:
            raise NotImplementedError(f"profile motion query not declared: {name}")
        self._validate_coordinates(kwargs)
        query_spec = self._queries[name]
        commands = self._engine.build(name, **kwargs)
        if len(commands) != 1:
            raise ValueError("motion query must declare exactly one wire transaction")
        command = commands[0]
        raw = self._exchange(command, expect_response=True)
        return self._parse_response(query_spec.get("response", {}), raw)

    # .............. device-specific operations .............. #

    def has_operation(self, name: str) -> bool:
        return name in self._operations

    def has_query(self, name: str) -> bool:
        # Profile capability introspection is deliberately side-effect free.
        return name in self._queries

    def query_response_spec(self, name: str) -> Mapping[str, Any] | None:
        # Return response metadata for explicit-readback capability gating.
        if name not in self._queries:
            return None
        response = self._queries[name].get("response", {})
        return response if isinstance(response, Mapping) else None

    def operation(self, name: str, **params: Any) -> None:
        if name == "move_relative" and _has_axis_bounds(self.get_motion_capabilities()):
            raise NotImplementedError(
                "relative motion is not supported on a profile with axis bounds"
            )
        if name not in self._operations:
            raise NotImplementedError(f"profile operation not declared: {name}")
        commands = self._engine.build(name, **params)
        with self._exchange_lock:
            for command in commands:
                self._exchange(
                    command, expect_response=self._expects_response(self._operation_specs[name])
                )

    # .............. response parsing .............. #

    def _parse_response(self, spec: Mapping[str, Any], raw: str) -> Any:
        kind = str(spec.get("type", "scalar"))
        delimiter = spec.get("delimiter")
        tokens = raw.split(delimiter) if delimiter is not None else raw.split()
        if kind == "axis_tuple":
            skip = int(spec.get("skip", 0))
            axes = [str(axis) for axis in spec.get("axes", [])]
            scale = _number(spec.get("scale", 1.0), "scale")
            selected = tokens[skip : skip + len(axes)]
            if len(selected) != len(axes):
                raise MotionFaultError(f"motion_position_unparseable: {raw!r}")
            return {
                axis: _number(float(token), axis) * scale
                for axis, token in zip(axes, selected, strict=True)
            }
        if kind == "status_field":
            index = int(spec.get("index", 0))
            ok_value = str(spec.get("ok_value", "0"))
            if len(tokens) <= index:
                raise MotionFaultError(f"motion_status_unparseable: {raw!r}")
            ok = tokens[index] == ok_value
            settled = ok and spec.get("settled_on_success", True)
            value_map = spec.get("value_map", spec.get("map"))
            if isinstance(value_map, Mapping):
                mapped = value_map.get(tokens[index])
                if mapped is None and tokens[index] not in value_map:
                    raise MotionFaultError(f"motion_status_unparseable: {raw!r}")
                return mapped
            return {
                "state": "settled" if settled else "unknown" if ok else "faulted",
                "settled": settled,
                "fault": not ok,
                "details": {"raw": raw},
            }
        if kind == "state_map":
            index = int(spec.get("index", 0))
            if len(tokens) <= index:
                raise MotionFaultError(f"motion_state_unparseable: {raw!r}")
            value_map = spec.get("values", spec.get("map"))
            if not isinstance(value_map, Mapping):
                raise InstrumentConfigurationError(
                    "motion", "state_map responses require a values/map mapping"
                )
            token = tokens[index]
            if token not in value_map:
                raise MotionFaultError(f"motion_state_unparseable: {raw!r}")
            return value_map[token]
        if kind == "scalar":
            scale = _number(spec.get("scale", 1.0), "scale")
            if not tokens:
                raise MotionFaultError(f"motion_scalar_unparseable: {raw!r}")
            return _number(float(tokens[0]), "response") * scale
        raise InstrumentConfigurationError("motion", f"unknown motion response type: {kind}")


class ProfileMotionDevice(MotionDevice):
    """Generic motion device whose wire protocol lives in the profile.

    Register this class for a device type (e.g. ``motion_stage``); any
    profile with a ``motion:`` section then becomes a working motion device
    with no per-device Python. Profile-declared ``operations`` are reachable
    through :meth:`operation`.
    """

    capability_name = "motion"

    def __init__(self, config: Any, backend: Any, **kwargs: Any) -> None:
        motion_spec = getattr(config, "motion", None)
        if motion_spec is None:
            raise InstrumentConfigurationError(
                config, "profile motion device requires a 'motion' section"
            )
        spec = dict(motion_spec)
        transport = getattr(config, "transport", None)
        if isinstance(transport, Mapping):
            if "min_command_interval_s" in transport:
                spec["min_command_interval_s"] = transport["min_command_interval_s"]
            if "query_delay_s" in transport:
                spec["query_delay_s"] = transport["query_delay_s"]
            message_io = dict(spec.get("message_io", {}) or {})
            message_io.update(transport.get("message_io", {}))
            for key in ("read_termination", "write_termination"):
                if key in transport:
                    message_io[key] = transport[key]
            if message_io:
                spec["message_io"] = message_io
        self._motion_spec = spec
        super().__init__(
            config,
            (
                _BackendFactory(lambda: ProfileMotionBackend(backend.build(), spec))
                if isinstance(backend, _BackendFactory)
                else ProfileMotionBackend(backend, spec)
            ),
            **kwargs,
        )

    def get_motion_capabilities(self) -> MotionCapabilities:
        """Inspect declared capabilities without allocating an instrument transport."""
        spec = self._motion_spec
        return _profile_capabilities(spec, _profile_supports(spec))

    def operation(self, name: str, **params: Any) -> None:
        """Execute a profile-declared device-specific operation."""

        if name == "move_relative" and _has_axis_bounds(self.get_motion_capabilities()):
            raise NotImplementedError(
                "relative motion is not supported on a profile with axis bounds"
            )

        backend = self._backend
        if not isinstance(backend, ProfileMotionBackend) or not backend.has_operation(name):
            raise NotImplementedError(f"operation not declared in profile: {name}")
        self._ensure_backend_connected()
        backend.operation(name, **params)


__all__ = ["ProfileMotionBackend", "ProfileMotionDevice"]
