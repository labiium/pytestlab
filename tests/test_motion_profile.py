"""Profile-driven generic motion device tests (no per-device Python).

Two different wire protocols are declared purely in profiles to prove the
machinery is generic: the deployed SUSS PA200 hex protocol and an invented
ASCII protocol. No PA200-specific code exists anywhere in pytestlab.
"""

from __future__ import annotations

import pytest

from pytestlab.config.device_config import DeviceConfig
from pytestlab.config.device_config import DeviceRole
from pytestlab.errors import InstrumentConfigurationError
from pytestlab.motion import MotionFaultError
from pytestlab.motion_profile import ProfileMotionDevice


class FakeIO:
    """Minimal DeviceIO fake recording writes and scripted responses."""

    def __init__(self, responses: dict[str, str] | None = None) -> None:
        self.writes: list[str] = []
        self.queries: list[str] = []
        self.responses = responses or {}

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

    def query(self, cmd: str, delay: float | None = None) -> str:
        self.queries.append(cmd)
        for pattern, response in self.responses.items():
            if cmd.startswith(pattern):
                return response
        return "0"


PA200_MOTION = {
    "axes": [
        {"name": "x", "units": "mm", "minimum": -100.0, "maximum": 100.0},
        {"name": "y", "units": "mm", "minimum": -100.0, "maximum": 100.0},
    ],
    "frames": ["machine"],
    "supports": [
        "set_home",
        "move_home",
        "move_absolute",
        "move_relative",
        "position",
        "status",
        "wait",
    ],
    "wire_scale": 1000.0,
    "success_prefix": "0",
    "commands": {
        "move_home": {"template": "34 0 0 H"},
        "set_home": {"template": "40"},
        "move_absolute": {"template": "34 {x} {y} H"},
        "move_relative": {"template": "34 {x} {y} R"},
    },
    "queries": {
        "position": {
            "template": "31",
            "response": {"type": "axis_tuple", "skip": 1, "axes": ["x", "y", "z"], "scale": 0.001},
        },
        "status": {
            "template": "31",
            "response": {"type": "status_field", "index": 0, "ok_value": "0"},
        },
    },
    "operations": {
        "set_chuck_vacuum": {
            "template": "05 {state}",
            "parameters": {
                "state": {
                    "kind": "enum",
                    "strict": True,
                    "choices": [
                        {"token": "1", "label": "on", "aliases": ["on", "true", "1"]},
                        {"token": "0", "label": "off", "aliases": ["off", "false", "0"]},
                    ],
                }
            },
        },
        "move_to_contact": {"template": "37"},
        "set_chuck_mode": {
            "template": "03 {overtravel} {auto_z} {interlock} {edge_sensor} 2",
            "parameters": {
                name: {
                    "kind": "enum",
                    "strict": True,
                    "choices": [
                        {"token": "1", "label": "engaged", "aliases": ["true", "on", "1"]},
                        {"token": "0", "label": "bypassed", "aliases": ["false", "off", "0"]},
                    ],
                }
                for name in ("overtravel", "auto_z", "interlock", "edge_sensor")
            },
        },
    },
}

GENERIC_ASCII_MOTION = {
    "axes": [{"name": "x", "units": "mm"}],
    "wire_scale": 1.0,
    "commands": {
        "home": {"template": "M:HOME"},
        "move_absolute": {"template": "M:ABS {x}"},
        "move_relative": {"template": "M:REL {x}"},
    },
    "queries": {
        "position": {
            "template": "M:POS?",
            "response": {"type": "axis_tuple", "skip": 0, "axes": ["x"], "scale": 1.0},
        }
    },
}


def device(
    motion: dict, responses: dict[str, str] | None = None
) -> tuple[ProfileMotionDevice, FakeIO]:
    config = DeviceConfig(
        manufacturer="test",
        model="profile-motion",
        device_type="motion_stage",
        role=DeviceRole.DUT_CONTROL,
        motion=motion,
    )
    io = FakeIO(responses)
    return ProfileMotionDevice(config, io), io


def test_pa200_hex_protocol_is_fully_profile_driven() -> None:
    prober, io = device(PA200_MOTION)
    with pytest.raises(NotImplementedError, match="move_relative"):
        prober.move_relative({"x": 0.01, "y": -0.005})
    assert io.queries == [] and io.writes == []
    prober.move_absolute({"x": 1.0, "y": 2.0})
    prober.move_home()
    # Response-checked exchanges go through DeviceIO.query() (write+read at
    # the transport level); with success_prefix declared, moves are checked.
    assert io.queries == ["34 1000.0 2000.0 H", "34 0 0 H"]
    assert io.writes == []


def test_position_response_spec_parses_and_scales() -> None:
    prober, _ = device(PA200_MOTION, responses={"31": "0 1000.0 -500.0 6600.0 0 31"})
    position = prober.get_position()
    assert position == pytest.approx({"x": 1.0, "y": -0.5, "z": 6.6})
    status = prober.get_status()
    assert status.settled and not status.fault


def test_success_prefix_convention_raises_fault() -> None:
    prober, _ = device(PA200_MOTION, responses={"05": "4 vacuum failed"})
    with pytest.raises(MotionFaultError, match="motion_error_response"):
        prober.operation("set_chuck_vacuum", state="on")


def test_operations_are_profile_declared() -> None:
    prober, io = device(PA200_MOTION)
    prober.operation("set_chuck_vacuum", state="on")
    prober.operation("move_to_contact")
    prober.set_home()
    assert io.queries == ["05 1", "37", "40"]
    with pytest.raises(NotImplementedError):
        prober.operation("does_not_exist")


def test_axis_limits_and_declarations_are_enforced() -> None:
    prober, _ = device(PA200_MOTION)
    with pytest.raises(ValueError, match="undeclared motion axes"):
        prober.move_absolute({"x": 1.0, "theta": 2.0})
    with pytest.raises(ValueError, match="above axis maximum"):
        prober.move_absolute({"x": 500.0, "y": 0.0})


def test_capabilities_come_from_the_profile() -> None:
    prober, _ = device(PA200_MOTION)
    capabilities = prober.get_capabilities()
    assert [axis.name for axis in capabilities.axes] == ["x", "y"]
    assert capabilities.axes[0].maximum == 100.0
    assert "jog" not in capabilities.supports
    with pytest.raises(NotImplementedError):
        prober.jog("x", 2.0)
    with pytest.raises(NotImplementedError):
        prober.stop()


def test_a_second_protocol_needs_no_python() -> None:
    stage, io = device(GENERIC_ASCII_MOTION, responses={"M:POS?": "2.5"})
    stage.move_absolute({"x": 2.5})
    stage.move_relative({"x": -0.5})
    stage.home()
    assert io.writes == ["M:ABS 2.5", "M:REL -0.5", "M:HOME"]
    assert stage.get_position() == {"x": 2.5}


def test_response_checked_exchange_transmits_exactly_once() -> None:
    prober, io = device(PA200_MOTION)
    prober.move_absolute({"x": 0.01, "y": -0.005})
    # DeviceIO.query() is write+read at the transport level: a
    # response-checked exchange must not ALSO call write().
    assert io.writes == []
    assert io.queries == ["34 10.0 -5.0 H"]


def test_moves_are_response_checked_when_prefix_declared() -> None:
    prober, _ = device(PA200_MOTION, responses={"34": "5 limit fault"})
    with pytest.raises(MotionFaultError, match="motion_error_response"):
        prober.move_absolute({"x": 0.01, "y": -0.005})


def test_chuck_mode_booleans_map_to_wire_bits() -> None:
    prober, io = device(PA200_MOTION)
    prober.operation(
        "set_chuck_mode", overtravel=True, auto_z=True, interlock=True, edge_sensor=False
    )
    assert io.queries == ["03 1 1 1 0 2"]


def test_missing_motion_section_is_a_configuration_error() -> None:
    config = DeviceConfig(
        manufacturer="test",
        model="no-motion",
        device_type="motion_stage",
        role=DeviceRole.DUT_CONTROL,
    )
    with pytest.raises(InstrumentConfigurationError, match="motion"):
        ProfileMotionDevice(config, FakeIO())


def test_profile_motion_preserves_lazy_backend_allocation():
    from pytestlab.devices.base import _BackendFactory

    config = DeviceConfig(
        manufacturer="test",
        model="lazy-motion",
        device_type="motion_stage",
        role=DeviceRole.DUT_CONTROL,
        motion=GENERIC_ASCII_MOTION,
    )
    allocations = []
    io = FakeIO()

    def build():
        allocations.append(True)
        return io

    motion = ProfileMotionDevice(config, _BackendFactory(build))
    assert allocations == []
    motion.close()
    assert allocations == []
    assert motion.get_motion_capabilities().axes
    assert allocations == []
    motion.connect_backend()
    assert allocations == [True]
    motion.close()
