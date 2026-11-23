"""Generic, transport-neutral motion-controller APIs.

The controller command vocabulary is deliberately small and textual.  A
backend only needs to implement :class:`~pytestlab.devices.DeviceIO`; a
vendor driver can translate these commands without changing user code.
"""

from __future__ import annotations

import json
import math
import time
from collections.abc import Iterable
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from typing import Protocol

from .config.device_config import DeviceConfig
from .devices.base import Device
from .devices.base import DeviceBackend

DEFAULT_MOTION_OPERATIONS = frozenset(
    {
        "home",
        "rotate_absolute",
        "move_absolute",
        "move_relative",
        "move_velocity",
        "jog",
        "move_joints",
        "move_pose",
        "execute_trajectory",
        "position",
        "status",
        "wait",
        "stop",
        "abort",
    }
)


class MotionBackend(DeviceBackend, Protocol):
    """Lifecycle-only motion backend marker.

    Drivers may implement either typed hook independently.  The generic
    device also retains a JSON command fallback for simple text transports
    and test doubles; that fallback is not presented as a vendor protocol.
    """


class MotionCommandBackend(MotionBackend, Protocol):
    """Backend that accepts typed motion commands."""

    def motion_command(self, operation: str, *, operation_id: str, **fields: Any) -> Any: ...


class MotionQueryBackend(MotionBackend, Protocol):
    """Backend that returns typed position/status values."""

    def motion_query(self, query: str, **fields: Any) -> Any: ...


class MotionWaitBackend(MotionBackend, Protocol):
    """Backend with native operation-correlated waiting."""

    def wait_operation(self, operation_id: str, **kwargs: Any) -> Any: ...


@dataclass(frozen=True)
class AxisGroup:
    """A named, ordered collection of controller axes."""

    name: str
    axes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.name or not self.axes or any(not axis for axis in self.axes):
            raise ValueError("axis groups require a name and at least one non-empty axis")


@dataclass(frozen=True)
class CoordinateFrame:
    """A named coordinate frame, optionally attached to a parent frame."""

    name: str
    parent: str | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("coordinate frame name cannot be empty")


@dataclass(frozen=True)
class AxisSpec:
    """Capabilities and limits for one named motion axis."""

    name: str
    units: str = "mm"
    minimum: float | None = None
    maximum: float | None = None

    def __post_init__(self) -> None:
        if not self.name or not self.units:
            raise ValueError("axis name and units cannot be empty")
        if self.minimum is not None and not math.isfinite(self.minimum):
            raise ValueError("axis minimum must be finite")
        if self.maximum is not None and not math.isfinite(self.maximum):
            raise ValueError("axis maximum must be finite")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("axis minimum cannot exceed maximum")


@dataclass(frozen=True)
class MotionCapabilities:
    """Declared features used to validate generic motion operations."""

    axes: tuple[AxisSpec, ...] = ()
    axis_groups: tuple[AxisGroup, ...] = ()
    frames: tuple[CoordinateFrame, ...] = (CoordinateFrame("machine"),)
    units: tuple[str, ...] = ("mm",)
    supports: frozenset[str] = DEFAULT_MOTION_OPERATIONS

    def __post_init__(self) -> None:
        axis_names = [axis.name for axis in self.axes]
        if len(axis_names) != len(set(axis_names)):
            raise ValueError("motion axis names must be unique")
        frame_names = [frame.name for frame in self.frames]
        if len(frame_names) != len(set(frame_names)):
            raise ValueError("motion frame names must be unique")
        group_names = [group.name for group in self.axis_groups]
        if len(group_names) != len(set(group_names)):
            raise ValueError("motion axis-group names must be unique")
        declared_axes = set(axis_names)
        if declared_axes and any(
            axis not in declared_axes for group in self.axis_groups for axis in group.axes
        ):
            raise ValueError("axis groups may only contain declared axes")

    @property
    def axis_map(self) -> dict[str, AxisSpec]:
        """Return axis specifications keyed by their stable controller name."""

        return {axis.name: axis for axis in self.axes}

    @property
    def frame_map(self) -> dict[str, CoordinateFrame]:
        """Return declared coordinate frames keyed by name."""

        return {frame.name: frame for frame in self.frames}

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> MotionCapabilities:
        """Build a declaration from YAML/JSON-friendly values."""

        def axis_from_value(axis: Any) -> AxisSpec:
            if isinstance(axis, AxisSpec):
                return axis
            if isinstance(axis, str):
                return AxisSpec(name=axis)
            if not isinstance(axis, Mapping):
                raise TypeError("motion axes must be names or mappings")
            name = axis.get("name", axis.get("axis"))
            if not isinstance(name, str) or not name:
                raise ValueError("motion axis declarations require a name")
            return AxisSpec(
                name=name,
                units=str(axis.get("units", "mm")),
                minimum=axis.get("minimum", axis.get("min")),
                maximum=axis.get("maximum", axis.get("max")),
            )

        def frame_from_value(frame: Any) -> CoordinateFrame:
            if isinstance(frame, CoordinateFrame):
                return frame
            if isinstance(frame, str):
                return CoordinateFrame(frame)
            if not isinstance(frame, Mapping):
                raise TypeError("motion frames must be names or mappings")
            name = frame.get("name")
            if not isinstance(name, str) or not name:
                raise ValueError("motion frame declarations require a name")
            parent = frame.get("parent")
            return CoordinateFrame(name, None if parent is None else str(parent))

        def group_from_value(group: Any) -> AxisGroup:
            if isinstance(group, AxisGroup):
                return group
            if not isinstance(group, Mapping):
                raise TypeError("motion axis groups must be mappings")
            name = group.get("name")
            axes = group.get("axes", ())
            if not isinstance(name, str) or not isinstance(axes, (list, tuple)):
                raise TypeError("motion axis groups require a name and axes")
            return AxisGroup(name, tuple(str(axis) for axis in axes))

        supports_value = value.get("supports", DEFAULT_MOTION_OPERATIONS)
        if isinstance(supports_value, str):
            supports = frozenset({supports_value})
        else:
            supports = frozenset(str(item) for item in supports_value)
        units_value = value.get("units", ("mm",))
        if isinstance(units_value, str):
            units = (units_value,)
        else:
            units = tuple(str(unit) for unit in units_value)
        frames_value = value.get("frames", (CoordinateFrame("machine"),))
        return cls(
            axes=tuple(axis_from_value(axis) for axis in value.get("axes", ())),
            axis_groups=tuple(group_from_value(group) for group in value.get("axis_groups", ())),
            frames=tuple(frame_from_value(frame) for frame in frames_value),
            units=units,
            supports=supports,
        )


class OperationState(StrEnum):
    """Normalized lifecycle state for a motion command."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    CANCELLED = "cancelled"
    FAILED = "failed"
    FAULTED = "faulted"
    UNKNOWN = "unknown"


class StopMode(StrEnum):
    """Controller stop semantics; emergency circuits remain external safety."""

    CONTROLLED = "controlled"
    QUICK = "quick"
    ABORT = "abort"


class MotionFaultError(RuntimeError):
    """The controller reported a motion fault while an operation was active."""


@dataclass(frozen=True)
class MotionStatus:
    """Controller state returned by :meth:`MotionDevice.get_status`."""

    state: str
    settled: bool
    raw: str = ""
    details: Mapping[str, Any] | None = None
    homed: bool | None = None
    enabled: bool | None = None
    fault: bool = False
    target_reached: bool | None = None
    operation_id: str | None = None


@dataclass(frozen=True)
class MotionResult:
    """Receipt for one accepted, completed, or rejected motion operation."""

    operation_id: str
    operation: str
    state: OperationState
    requested: Any = None
    actual: Mapping[str, float] | None = None
    frame: str = "machine"
    units: str = "mm"
    error: str | None = None
    details: Mapping[str, Any] | None = None


class MotionDevice(Device[DeviceConfig]):
    """Generic multi-axis motion device using real-controller semantics."""

    capability_name = "motion"

    def __init__(self, config: DeviceConfig, backend: Any, **kwargs: Any) -> None:
        super().__init__(config, backend, **kwargs)
        self._operation_counter = 0

    def get_motion_capabilities(self) -> MotionCapabilities:
        """Return declared backend capabilities without starting motion."""

        getter = getattr(self._backend, "get_motion_capabilities", None)
        value = (
            getter() if callable(getter) else getattr(self._backend, "motion_capabilities", None)
        )
        if value is None:
            getter = getattr(self._backend, "get_capabilities", None)
            value = getter() if callable(getter) else getattr(self._backend, "capabilities", None)
        if value is None:
            value = getattr(self._backend, "capabilities", None)
        if isinstance(value, MotionCapabilities):
            return value
        if isinstance(value, Mapping):
            try:
                return MotionCapabilities.from_mapping(value)
            except (AttributeError, TypeError, ValueError) as exc:
                raise TypeError("invalid motion capability declaration") from exc
        return MotionCapabilities()

    def get_capabilities(self) -> MotionCapabilities:
        """Return the motion capability declaration for this device."""

        return self.get_motion_capabilities()

    describe_capabilities = get_capabilities

    def _require_supported(self, operation: str) -> None:
        supports = self.get_motion_capabilities().supports
        if operation not in supports:
            raise NotImplementedError(f"motion operation is not supported: {operation}")

    def _next_operation(self, operation: str) -> str:
        self._operation_counter += 1
        model = getattr(self.config, "model", "motion")
        return f"{model}-{operation}-{self._operation_counter:06d}"

    def _issue(
        self,
        operation: str,
        *,
        fields: Mapping[str, Any] | None = None,
        requested: Any = None,
        frame: str = "machine",
        units: str = "mm",
        wait: bool = False,
        wire_operation: str | None = None,
    ) -> MotionResult:
        self._require_supported(operation)
        if wait:
            self._require_supported("wait")
        operation_id = self._next_operation(operation)
        payload = dict(fields or {})
        typed_command = getattr(self._backend, "motion_command", None)
        details: Mapping[str, Any] | None = None
        backend_actual: Mapping[str, float] | None = None
        backend_error: str | None = None
        if callable(typed_command):
            self._ensure_backend_connected()
            value = typed_command(operation, operation_id=operation_id, **payload)
            if isinstance(value, Mapping):
                details = dict(value)
                returned_id = value.get("operation_id")
                if returned_id is not None:
                    operation_id = str(returned_id)
                state = self._operation_state(value.get("state"), OperationState.RUNNING)
                actual_value = value.get("actual")
                if isinstance(actual_value, Mapping):
                    backend_actual = self._decode_mapping_value(actual_value)
                if value.get("error") is not None:
                    backend_error = str(value["error"])
            elif isinstance(value, MotionResult):
                operation_id = value.operation_id or operation_id
                state = value.state
                details = value.details
                backend_actual = value.actual
                backend_error = value.error
            else:
                state = OperationState.RUNNING
        else:
            command = self._command(
                wire_operation or operation.upper().replace("_", " "), **payload
            )
            self.write(command)
            state = OperationState.RUNNING
        result = MotionResult(
            operation_id=operation_id,
            operation=operation,
            state=state,
            requested=requested,
            frame=frame,
            units=units,
            details=details,
        )
        if not wait:
            return result
        if state in {
            OperationState.SUCCEEDED,
            OperationState.CANCELLED,
            OperationState.FAILED,
            OperationState.FAULTED,
        }:
            return MotionResult(
                operation_id=operation_id,
                operation=operation,
                state=state,
                requested=requested,
                actual=backend_actual,
                frame=frame,
                units=units,
                error=backend_error,
                details=details,
            )
        try:
            status = self.wait_operation(operation_id)
        except MotionFaultError as exc:
            return MotionResult(
                operation_id=operation_id,
                operation=operation,
                state=OperationState.FAULTED,
                requested=requested,
                frame=frame,
                units=units,
                error=str(exc),
                details=details,
            )
        actual: Mapping[str, float] | None
        try:
            actual = self.get_position(frame=frame, units=units)
        except NotImplementedError:
            actual = None
        return MotionResult(
            operation_id=operation_id,
            operation=operation,
            state=(OperationState.FAULTED if status.fault else OperationState.SUCCEEDED),
            requested=requested,
            actual=actual,
            frame=frame,
            units=units,
            error="motion_fault" if status.fault else None,
            details=status.details,
        )

    def home(self, axes: str | Iterable[str] | None = None, *, wait: bool = False) -> MotionResult:
        """Run the declared homing/reference operation for all or selected axes."""
        selected = self._axes(axes)
        return self._issue(
            "home", fields={"axes": selected}, requested={"axes": selected}, wait=wait
        )

    def set_home(self, axes: str | Iterable[str] | None = None) -> MotionResult:
        """Define the controller's saved home at the current position."""
        selected = self._axes(axes)
        return self._issue("set_home", fields={"axes": selected}, requested={"axes": selected})

    def move_home(
        self, axes: str | Iterable[str] | None = None, *, wait: bool = False
    ) -> MotionResult:
        """Move to the saved controller home without redefining it."""
        selected = self._axes(axes)
        return self._issue(
            "move_home", fields={"axes": selected}, requested={"axes": selected}, wait=wait
        )

    def rotate_absolute(self, theta_deg: float, *, wait: bool = False) -> MotionResult:
        """Move a rotary chuck axis to an absolute angle in degrees."""

        if (
            isinstance(theta_deg, bool)
            or not isinstance(theta_deg, (int, float))
            or not math.isfinite(float(theta_deg))
        ):
            raise ValueError("theta_deg must be a finite number")
        value = float(theta_deg)
        return self._issue(
            "rotate_absolute",
            fields={"theta_deg": value},
            requested={"theta_deg": value},
            frame="machine",
            units="deg",
            wait=wait,
            wire_operation="ROTATE ABS",
        )

    def move_absolute(
        self,
        position: Mapping[str, float] | None = None,
        *,
        frame: str | CoordinateFrame = "machine",
        units: str = "mm",
        axis_group: str | AxisGroup | None = None,
        wait: bool = False,
        **coordinates: float,
    ) -> MotionResult:
        position = self._coordinate_arguments(position, coordinates)
        self._validate_position(position)
        frame_name = self._frame_name(frame)
        return self._issue(
            "move_absolute",
            fields={
                "position": dict(position),
                "frame": frame_name,
                "units": units,
                "axis_group": self._group_fields(axis_group),
            },
            requested=dict(position),
            frame=frame_name,
            units=units,
            wait=wait,
            wire_operation="MOVE ABS",
        )

    def move_relative(
        self,
        offset: Mapping[str, float] | None = None,
        *,
        frame: str | CoordinateFrame = "machine",
        units: str = "mm",
        axis_group: str | AxisGroup | None = None,
        wait: bool = False,
        **coordinates: float,
    ) -> MotionResult:
        offset = self._coordinate_arguments(offset, coordinates)
        self._validate_position(offset)
        frame_name = self._frame_name(frame)
        return self._issue(
            "move_relative",
            fields={
                "offset": dict(offset),
                "frame": frame_name,
                "units": units,
                "axis_group": self._group_fields(axis_group),
            },
            requested=dict(offset),
            frame=frame_name,
            units=units,
            wait=wait,
            wire_operation="MOVE REL",
        )

    def jog(
        self,
        axis: str,
        velocity: float,
        *,
        units: str = "mm/s",
        axis_group: str | AxisGroup | None = None,
        frame: str | CoordinateFrame = "machine",
    ) -> MotionResult:
        if not axis or velocity == 0 or not math.isfinite(velocity):
            raise ValueError("jog requires a non-empty axis and non-zero velocity")
        frame_name = self._frame_name(frame)
        return self._issue(
            "jog",
            fields={
                "axis": axis,
                "velocity": velocity,
                "units": units,
                "frame": frame_name,
                "axis_group": self._group_fields(axis_group),
            },
            requested={"axis": axis, "velocity": velocity},
            frame=frame_name,
            units=units,
        )

    def move_velocity(
        self,
        velocity: Mapping[str, float],
        *,
        frame: str | CoordinateFrame = "machine",
        units: str = "mm/s",
        axis_group: str | AxisGroup | None = None,
    ) -> MotionResult:
        self._validate_position(velocity)
        frame_name = self._frame_name(frame)
        return self._issue(
            "move_velocity",
            fields={
                "velocity": dict(velocity),
                "frame": frame_name,
                "units": units,
                "axis_group": self._group_fields(axis_group),
            },
            requested=dict(velocity),
            frame=frame_name,
            units=units,
        )

    def get_position(
        self, *, frame: str | CoordinateFrame = "machine", units: str = "mm"
    ) -> dict[str, float]:
        """Read and decode the current position from the controller."""
        self._require_supported("position")
        frame_name = self._frame_name(frame)
        typed_query = getattr(self._backend, "motion_query", None)
        if callable(typed_query):
            self._ensure_backend_connected()
            return self._decode_mapping_value(
                typed_query("position", frame=frame_name, units=units)
            )
        return self._decode_mapping(
            self.query(self._command("POSITION?", frame=frame_name, units=units))
        )

    def get_status(self) -> MotionStatus:
        self._require_supported("status")
        typed_query = getattr(self._backend, "motion_query", None)
        if callable(typed_query):
            self._ensure_backend_connected()
            return self._coerce_status(typed_query("status"))
        else:
            raw_value = None
        raw = (
            json.dumps(raw_value, sort_keys=True, separators=(",", ":"))
            if isinstance(raw_value, Mapping)
            else str(raw_value)
            if raw_value is not None
            else self.query("STATUS?")
        )
        return self._coerce_status(raw)

    @property
    def position(self) -> dict[str, float]:
        return self.get_position()

    @property
    def status(self) -> MotionStatus:
        return self.get_status()

    def wait_settled(
        self,
        *,
        timeout: float = 30.0,
        poll_interval: float = 0.05,
        expected_operation_id: str | None = None,
    ) -> MotionStatus:
        self._require_supported("wait")
        if timeout < 0 or poll_interval < 0:
            raise ValueError("timeout and poll_interval must be non-negative")
        deadline = time.monotonic() + timeout
        while True:
            status = self.get_status()
            if status.fault:
                raise MotionFaultError("motion_controller_fault")
            if status.operation_id is not None and status.operation_id != expected_operation_id:
                if expected_operation_id is not None:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(
                            f"motion operation {expected_operation_id} did not settle within {timeout:g} seconds"
                        )
                    time.sleep(min(poll_interval, max(0.0, deadline - time.monotonic())))
                    continue
            if status.settled:
                return status
            if time.monotonic() >= deadline:
                raise TimeoutError(f"motion did not settle within {timeout:g} seconds")
            time.sleep(min(poll_interval, max(0.0, deadline - time.monotonic())))

    def wait_operation(
        self,
        operation_id: str,
        *,
        timeout: float = 30.0,
        poll_interval: float = 0.05,
    ) -> MotionStatus:
        """Wait for one operation, using a typed backend hook when available."""

        if not operation_id:
            raise ValueError("operation_id cannot be empty")
        typed_wait = getattr(self._backend, "wait_operation", None)
        if callable(typed_wait):
            self._ensure_backend_connected()
            value = typed_wait(
                operation_id,
                timeout=timeout,
                poll_interval=poll_interval,
            )
            return self._coerce_status(value)
        return self.wait_settled(
            timeout=timeout,
            poll_interval=poll_interval,
            expected_operation_id=operation_id,
        )

    def stop(self, mode: StopMode | str = StopMode.CONTROLLED) -> MotionResult:
        """Stop motion; emergency circuits are not represented by this method."""

        selected = StopMode(mode)
        if selected is StopMode.ABORT:
            return self.abort()
        self._require_supported("stop")
        command = "QUICKSTOP" if selected is StopMode.QUICK else "STOP"
        typed_command = getattr(self._backend, "motion_command", None)
        operation_id = self._next_operation(selected.value)
        if callable(typed_command):
            self._ensure_backend_connected()
            value = typed_command(
                "stop",
                operation_id=operation_id,
                mode=selected.value,
            )
            if isinstance(value, Mapping):
                returned_id = value.get("operation_id")
                if returned_id is not None:
                    operation_id = str(returned_id)
                state = self._operation_state(value.get("state"), OperationState.RUNNING)
                details: Mapping[str, Any] | None = dict(value)
            else:
                state = OperationState.RUNNING
                details = None
        else:
            self.write(command)
            state = OperationState.RUNNING
            details = None
        return MotionResult(operation_id, selected.value, state, details=details)

    def abort(self) -> MotionResult:
        """Abort the controller operation; this is not a safety-rated E-stop."""

        self._require_supported("abort")
        operation_id = self._next_operation("abort")
        typed_command = getattr(self._backend, "motion_command", None)
        if callable(typed_command):
            self._ensure_backend_connected()
            value = typed_command("abort", operation_id=operation_id)
            if isinstance(value, Mapping):
                returned_id = value.get("operation_id")
                if returned_id is not None:
                    operation_id = str(returned_id)
                state = self._operation_state(value.get("state"), OperationState.CANCELLED)
                details: Mapping[str, Any] | None = dict(value)
            else:
                state = OperationState.CANCELLED
                details = None
        else:
            self.write("ABORT")
            state = OperationState.CANCELLED
            details = None
        return MotionResult(operation_id, "abort", state, details=details)

    @staticmethod
    def _axes(axes: str | Iterable[str] | None) -> list[str] | None:
        if axes is None:
            return None
        values = [axes] if isinstance(axes, str) else list(axes)
        if not values or any(not axis for axis in values):
            raise ValueError("axes must contain at least one non-empty axis")
        return values

    @staticmethod
    def _coordinate_arguments(
        values: Mapping[str, float] | None, coordinates: Mapping[str, float]
    ) -> dict[str, float]:
        if values is not None and coordinates:
            raise TypeError("Use either a coordinate mapping or keyword axes, not both.")
        selected = coordinates if values is None else values
        if not isinstance(selected, Mapping):
            raise TypeError("Coordinates must be a mapping or keyword axes.")
        return dict(selected)

    @staticmethod
    def _validate_position(position: Mapping[str, float]) -> None:
        if not position or any(not axis for axis in position):
            raise ValueError("position must contain at least one named axis")
        if any(
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(float(value))
            for value in position.values()
        ):
            raise TypeError("position values must be finite numbers")

    @staticmethod
    def _validate_vector(values: Iterable[float], *, label: str) -> None:
        if any(not math.isfinite(float(value)) for value in values):
            raise TypeError(f"{label} must be finite numbers")

    @staticmethod
    def _group_fields(group: str | AxisGroup | None) -> Any:
        if isinstance(group, AxisGroup):
            return {"name": group.name, "axes": list(group.axes)}
        return group

    @staticmethod
    def _frame_name(frame: str | CoordinateFrame) -> str:
        return frame.name if isinstance(frame, CoordinateFrame) else frame

    @staticmethod
    def _decode_mapping_value(value: Any) -> dict[str, float]:
        if isinstance(value, Mapping):
            try:
                return {str(axis): float(number) for axis, number in value.items()}
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "controller position response contains non-numeric values"
                ) from exc
        return MotionDevice._decode_mapping(str(value))

    @staticmethod
    def _optional_bool(value: Any) -> bool | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on", "ready", "idle", "settled"}:
                return True
            if normalized in {"0", "false", "no", "off", "moving", "busy"}:
                return False
            return None
        return bool(value)

    @staticmethod
    def _operation_state(value: Any, default: OperationState) -> OperationState:
        if value is None:
            return default
        try:
            return OperationState(str(value).lower())
        except ValueError:
            return OperationState.UNKNOWN

    @classmethod
    def _coerce_status(cls, value: Any) -> MotionStatus:
        if isinstance(value, MotionStatus):
            return value
        raw = (
            json.dumps(value, sort_keys=True, separators=(",", ":"))
            if isinstance(value, Mapping)
            else str(value)
        )
        payload = value if isinstance(value, Mapping) else cls._decode_payload(raw)
        if not isinstance(payload, Mapping):
            state = raw.strip()
            state_lower = state.lower()
            settled = state_lower in {"settled", "idle", "ready", "done", "complete"}
            fault = state_lower in {"fault", "faulted", "error", "alarm"} or "fault" in state_lower
            return MotionStatus(state, settled, raw, fault=fault, target_reached=settled)
        state = str(payload.get("state", payload.get("status", "unknown")))
        state_lower = state.lower()
        settled = cls._as_bool(
            payload.get("settled"),
            state_lower in {"settled", "idle", "ready", "done", "complete"},
        )
        fault = cls._as_bool(
            payload.get("fault"),
            state_lower in {"fault", "faulted", "error", "alarm"} or "fault" in state_lower,
        )
        nested_details = payload.get("details", {})
        if not isinstance(nested_details, Mapping):
            raise ValueError("controller status details must be an object")
        status_fields = {
            "state",
            "status",
            "settled",
            "fault",
            "homed",
            "enabled",
            "target_reached",
            "operation_id",
            "details",
        }
        details = {key: item for key, item in payload.items() if key not in status_fields}
        details.update(nested_details)
        return MotionStatus(
            state,
            settled,
            raw,
            details,
            homed=cls._optional_bool(payload.get("homed")),
            enabled=cls._optional_bool(payload.get("enabled")),
            fault=fault,
            target_reached=cls._optional_bool(payload.get("target_reached")),
            operation_id=(
                str(payload["operation_id"]) if payload.get("operation_id") is not None else None
            ),
        )

    @staticmethod
    def _as_bool(value: Any, default: bool) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on", "ready", "idle", "settled"}:
                return True
            if normalized in {"0", "false", "no", "off", "moving", "busy"}:
                return False
            return default
        return bool(value)

    @staticmethod
    def _command(operation: str, **fields: Any) -> str:
        payload = json.dumps(fields, sort_keys=True, separators=(",", ":"))
        return f"{operation} {payload}".rstrip()

    @staticmethod
    def _decode_payload(raw: str) -> Any:
        try:
            return json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return raw

    @classmethod
    def _decode_mapping(cls, raw: str) -> dict[str, float]:
        payload = cls._decode_payload(raw)
        if not isinstance(payload, dict):
            raise ValueError("controller position response must be a JSON object")
        try:
            return {str(axis): float(value) for axis, value in payload.items()}
        except (TypeError, ValueError) as exc:
            raise ValueError("controller position response contains non-numeric values") from exc


__all__ = [
    "AxisGroup",
    "AxisSpec",
    "CoordinateFrame",
    "DEFAULT_MOTION_OPERATIONS",
    "MotionBackend",
    "MotionCommandBackend",
    "MotionCapabilities",
    "MotionDevice",
    "MotionFaultError",
    "MotionQueryBackend",
    "MotionResult",
    "MotionStatus",
    "MotionWaitBackend",
    "OperationState",
    "StopMode",
]
