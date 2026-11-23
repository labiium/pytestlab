from __future__ import annotations

import json

import pytest

from pytestlab.config.device_config import DeviceConfig
from pytestlab.config.device_config import DeviceRole
from pytestlab.motion import AxisGroup
from pytestlab.motion import AxisSpec
from pytestlab.motion import CoordinateFrame
from pytestlab.motion import MotionCapabilities
from pytestlab.motion import MotionDevice
from pytestlab.motion import OperationState
from pytestlab.robot import RobotDevice


class Backend:
    def __init__(self) -> None:
        self.writes: list[str] = []
        self.statuses = iter([json.dumps({"state": "moving", "settled": False}), "settled"])

    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        pass

    def close(self) -> None:
        pass

    def set_timeout(self, timeout_ms: int) -> None:
        pass

    def get_timeout(self) -> int:
        return 1000

    def write(self, cmd: str) -> None:
        self.writes.append(cmd)

    def query_raw(self, cmd: str, delay: float | None = None) -> bytes:
        return b""

    def query(self, cmd: str, delay: float | None = None) -> str:
        if cmd == "STATUS?":
            return next(self.statuses)
        if cmd.startswith("POSITION?"):
            return '{"x": 1.5, "y": 2}'
        return ""


def device(cls=MotionDevice):
    backend = Backend()
    config = DeviceConfig(
        manufacturer="test", model="motion", device_type="motion", role=DeviceRole.FIXTURE
    )
    return cls(config, backend), backend


def payload(command: str) -> dict:
    return json.loads(command[command.index("{") :])


def test_motion_commands_cover_home_absolute_relative_jog_stop_abort_and_state():
    motion, backend = device()
    group = AxisGroup("xy", ("x", "y"))
    motion.home(["x", "y"])
    motion.move_absolute({"x": 1}, axis_group=group, wait=True)
    motion.move_relative({"x": -0.5})
    motion.jog("x", 2.0)
    motion.stop()
    motion.abort()

    assert backend.writes[0] == 'HOME {"axes":["x","y"]}'
    assert payload(backend.writes[1]) == {
        "axis_group": {"axes": ["x", "y"], "name": "xy"},
        "frame": "machine",
        "position": {"x": 1},
        "units": "mm",
    }
    assert motion.position == {"x": 1.5, "y": 2.0}
    assert backend.writes[-2:] == ["STOP", "ABORT"]


def test_motion_commands_cover_absolute_rotation():
    motion, backend = device()

    result = motion.rotate_absolute(7.0)

    assert result.operation == "rotate_absolute"
    assert result.requested == {"theta_deg": 7.0}
    assert backend.writes[0].startswith("ROTATE ABS ")
    assert payload(backend.writes[0]) == {"theta_deg": 7.0}


def test_robot_supports_joint_pose_and_trajectory_spaces():
    robot, backend = device(RobotDevice)
    robot.move_joints({"j1": 10, "j2": -2})
    robot.move_pose({"x": 1, "y": 2, "orientation": [0, 0, 0, 1]})
    robot.execute_trajectory([{"j1": 0}, {"j1": 10}], space="joint")
    assert backend.writes[0].startswith("JOINT MOVE ")
    assert backend.writes[1].startswith("POSE MOVE ")
    assert json.loads(backend.writes[2][backend.writes[2].index("{") :])["space"] == "joint"


def test_motion_validates_targets_and_waits_until_settled():
    motion, _ = device()
    assert motion.wait_settled(timeout=1).settled
    with pytest.raises(ValueError):
        motion.move_absolute({})
    with pytest.raises(ValueError):
        motion.jog("x", 0)
    with pytest.raises(ValueError):
        motion.wait_settled(timeout=-1)


def test_typed_motion_backend_avoids_invented_wire_commands():
    class TypedBackend(Backend):
        def __init__(self):
            super().__init__()
            self.connected = False

        def connect(self):
            self.connected = True

        capabilities = MotionCapabilities(
            axes=(AxisSpec("x", minimum=-1, maximum=1),),
            frames=(CoordinateFrame("machine"),),
        )

        def motion_command(self, operation, *, operation_id, **fields):
            assert self.connected
            self.typed_command = (operation, operation_id, fields)
            return {"operation_id": "controller-op-7", "state": "queued"}

        def motion_query(self, query, **fields):
            assert self.connected
            if query == "position":
                return {"x": 0.5}
            return {"state": "settled", "settled": True}

    backend = TypedBackend()
    config = DeviceConfig(
        manufacturer="test", model="typed-motion", device_type="motion", role=DeviceRole.FIXTURE
    )
    motion = MotionDevice(config, backend)

    result = motion.move_absolute({"x": 0.5}, wait=True)

    assert result.operation_id == "controller-op-7"
    assert result.state is OperationState.SUCCEEDED
    assert result.actual == {"x": 0.5}
    assert backend.writes == []
    assert backend.typed_command[0] == "move_absolute"


def test_plain_fault_status_is_normalized_as_fault():
    motion, backend = device()
    backend.statuses = iter(["FAULT"])

    status = motion.get_status()

    assert status.fault is True
    assert status.settled is False
