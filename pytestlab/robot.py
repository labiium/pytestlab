"""Generic robot APIs layered on :mod:`pytestlab.motion`."""

from __future__ import annotations

from collections.abc import Iterable
from collections.abc import Mapping
from typing import Any
from typing import cast

from .motion import CoordinateFrame
from .motion import MotionDevice
from .motion import MotionResult


class RobotDevice(MotionDevice):
    """Robot controller supporting arbitrary joint counts and pose schemas."""

    capability_name = "robot"

    def move_joints(
        self,
        joints: Mapping[str, float] | Iterable[float],
        *,
        units: str = "deg",
        wait: bool = False,
    ) -> MotionResult:
        values: Mapping[str, float] | list[float]
        if isinstance(joints, Mapping):
            named_joints = cast(Mapping[str, float], joints)
            self._validate_position(named_joints)
            values = dict(named_joints)
        else:
            try:
                values = [float(value) for value in joints]
            except (TypeError, ValueError) as exc:
                raise TypeError("joint targets must be finite numbers") from exc
            if not values:
                raise ValueError("joint target cannot be empty")
            self._validate_vector(values, label="joint targets")
        return self._issue(
            "move_joints",
            fields={"joints": values, "units": units},
            requested=values,
            units=units,
            wait=wait,
            wire_operation="JOINT MOVE",
        )

    def move_pose(
        self,
        pose: Mapping[str, Any],
        *,
        frame: str | CoordinateFrame = "base",
        units: str = "mm",
        wait: bool = False,
    ) -> MotionResult:
        if not pose:
            raise ValueError("pose cannot be empty")
        frame_name = self._frame_name(frame)
        return self._issue(
            "move_pose",
            fields={"pose": dict(pose), "frame": frame_name, "units": units},
            requested=dict(pose),
            frame=frame_name,
            units=units,
            wait=wait,
            wire_operation="POSE MOVE",
        )

    def execute_trajectory(
        self,
        points: Iterable[Mapping[str, Any]],
        *,
        space: str = "joint",
        frame: str | CoordinateFrame = "base",
        units: str | None = None,
        wait: bool = False,
    ) -> MotionResult:
        trajectory = [dict(point) for point in points]
        if not trajectory:
            raise ValueError("trajectory must contain at least one point")
        if space not in {"joint", "pose"}:
            raise ValueError("trajectory space must be 'joint' or 'pose'")
        frame_name = self._frame_name(frame)
        resolved_units = units or ("deg" if space == "joint" else "mm")
        return self._issue(
            "execute_trajectory",
            fields={
                "points": trajectory,
                "space": space,
                "frame": frame_name,
                "units": resolved_units,
            },
            requested=trajectory,
            frame=frame_name,
            units=resolved_units,
            wait=wait,
            wire_operation="TRAJECTORY EXECUTE",
        )

    def get_joint_position(self, *, units: str = "deg") -> dict[str, float]:
        """Read the current named joint state when the controller exposes it."""

        typed_query = getattr(self._backend, "motion_query", None)
        if callable(typed_query):
            self._ensure_backend_connected()
            return self._decode_mapping_value(typed_query("joint_position", units=units))
        return self._decode_mapping(self.query(self._command("JOINT POSITION?", units=units)))

    def get_pose(
        self,
        *,
        frame: str | CoordinateFrame = "base",
        units: str = "mm",
    ) -> dict[str, float]:
        """Read the controller's current Cartesian/tool pose when available."""

        frame_name = self._frame_name(frame)
        typed_query = getattr(self._backend, "motion_query", None)
        if callable(typed_query):
            self._ensure_backend_connected()
            return self._decode_mapping_value(typed_query("pose", frame=frame_name, units=units))
        return self._decode_mapping(
            self.query(self._command("POSE?", frame=frame_name, units=units))
        )
