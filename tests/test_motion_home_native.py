from __future__ import annotations

import pytest

from pytestlab import AutoDevice
from pytestlab.config.device_config import DeviceConfig
from pytestlab.motion import MotionDevice
from pytestlab.motion_profile import ProfileMotionDevice


class FakeIO:
    def __init__(self):
        self.calls = []

    def connect(self):
        self.calls.append(("connect",))

    def disconnect(self):
        pass

    def close(self):
        pass

    def set_read_termination(self, value):
        pass

    def set_write_termination(self, value):
        self.write_termination = value

    def write(self, command):
        self.calls.append(("write", command))

    def query(self, command, delay=None):
        self.calls.append(("query", command, delay))
        return "0 accepted"


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    monkeypatch.setattr("pytestlab.profile_transport.time.sleep", lambda _: None)


def prober():
    io = FakeIO()
    return AutoDevice.from_preset("suss/PA200", backend_override=io), io


def commands(io):
    return [call[1] for call in io.calls if call[0] in {"write", "query"}]


def test_set_home_is_a_native_capability_with_profile_only_wire_command():
    device, io = prober()
    result = device.set_home()
    assert result.operation == "set_home"
    assert commands(io) == ["40"]
    assert {"set_home", "move_home"} <= device.get_capabilities().supports
    assert not device._backend.has_operation("set_chuck_home")


def test_move_home_and_reference_cycle_are_distinct():
    device, io = prober()
    result = device.move_home()
    assert result.operation == "move_home"
    assert commands(io) == ["34 0 0 H"]
    io.calls.clear()
    with pytest.raises(NotImplementedError, match="home"):
        device.home()
    assert io.calls == []


def test_keyword_coordinates_and_existing_mapping_have_identical_wire_results():
    device, io = prober()
    device.move_absolute(x=1.0, y=-0.5)
    device.move_absolute({"x": 1.0, "y": -0.5})
    assert commands(io) == ["34 1000.0 -500.0 H", "34 1000.0 -500.0 H"]


def test_packaged_pa200_relative_wait_is_unavailable_before_transport():
    device, io = prober()
    assert "move_relative" in device.get_capabilities().supports
    assert io.calls == []
    with pytest.raises(NotImplementedError, match="wait"):
        device.move_relative(x=0.01, wait=True)
    assert io.calls == []


@pytest.mark.parametrize(
    "method,mapping", [("move_absolute", {"x": 1}), ("move_relative", {"x": 1})]
)
def test_mixed_coordinate_forms_are_rejected_before_connection(method, mapping):
    device, io = prober()
    with pytest.raises(TypeError, match="mapping.*keyword|keyword.*mapping"):
        getattr(device, method)(mapping, y=2)
    assert io.calls == []


@pytest.mark.parametrize("kwargs", [{}, {"x": True}, {"x": float("nan")}, {"x": float("inf")}])
def test_invalid_keyword_coordinates_do_not_connect(kwargs):
    device, io = prober()
    with pytest.raises((TypeError, ValueError)):
        device.move_relative(**kwargs)
    assert io.calls == []


@pytest.mark.parametrize("method", ["set_home", "move_home"])
def test_subset_home_request_cannot_silently_affect_all_axes(method):
    device, io = prober()
    with pytest.raises(NotImplementedError):
        getattr(device, method)("x")
    assert commands(io) == []


def test_new_home_capabilities_are_not_assumed_on_legacy_backends():
    io = FakeIO()
    device = MotionDevice(
        DeviceConfig(
            manufacturer="Example",
            model="legacy",
            device_type="motion",
            role="fixture",
        ),
        io,
    )
    for method in (device.set_home, device.move_home):
        with pytest.raises(NotImplementedError):
            method()
    assert io.calls == []


def test_unrelated_protocol_uses_the_identical_native_home_api():
    io = FakeIO()
    device = ProfileMotionDevice(
        DeviceConfig(
            manufacturer="Example",
            model="different-protocol",
            device_type="motion_stage",
            role="fixture",
            motion={
                "axes": [{"name": "u"}],
                "commands": {
                    "set_home": {"template": "ORIGIN SAVE"},
                    "move_home": {"template": "GO ZERO"},
                },
            },
        ),
        io,
    )
    device.set_home()
    device.move_home()
    assert commands(io) == ["ORIGIN SAVE", "GO ZERO"]


def test_unsupported_wait_is_rejected_before_return_home_actuation():
    device, io = prober()
    with pytest.raises(NotImplementedError, match="wait"):
        device.move_home(wait=True)
    assert io.calls == []
