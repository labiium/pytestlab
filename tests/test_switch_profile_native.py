from __future__ import annotations

from pytestlab.config.bench_config import BenchConfigExtended
from pytestlab.config.device_config import DeviceRole
from pytestlab.devices import AutoDevice
from pytestlab.devices import SwitchMatrixDevice


class FakeIO:
    def __init__(self, status: int = 0x43):
        self.writes: list[str] = []
        self.queries: list[str] = []
        self.status = status
        self.connects = 0
        self.terminations: list[str | None] = []

    def connect(self):
        self.connects += 1

    def disconnect(self):
        pass

    def close(self):
        pass

    def set_timeout(self, value):
        pass

    def get_timeout(self):
        return 1000

    def write(self, command):
        self.writes.append(command)

    def query(self, command, delay=None):
        self.queries.append(command)
        return "HP 4084B REV. 3.0"

    def query_raw(self, command, delay=None):
        return b""

    def read_status_byte(self):
        return self.status

    def set_read_termination(self, value):
        self.terminations.append(value)


class AckIO(FakeIO):
    def query(self, command, delay=None):
        self.queries.append(command)
        return "0 OK"


class ScriptedAckIO(FakeIO):
    def __init__(self, response: str):
        super().__init__()
        self.response = response

    def query(self, command, delay=None):
        self.queries.append(command)
        return self.response


class FailingIO(FakeIO):
    def __init__(self):
        super().__init__()
        self._writes = 0

    def write(self, command):
        self._writes += 1
        if self._writes == 2:
            raise RuntimeError("simulated relay write failure")
        super().write(command)


def config() -> dict:
    return {
        "device_type": "switch_matrix",
        "role": DeviceRole.SWITCHING,
        "manufacturer": "Example",
        "model": "DeclarativeMatrix",
        "terminals": ["source", "dut"],
        "channels": ["P1:12", "P2:12"],
        "switch": {
            "requires_context": ["source_outputs_zero", "matrix_closed"],
            "crosspoint": {
                "pattern": r"P(?P<port>[0-9]+):(?P<pin>[0-9]+)",
                "fields": ["port", "pin"],
                "constraints": {
                    "port": {"min": 1, "max": 10},
                    "pin": {"min": 1, "max": 48},
                },
            },
            "commands": {
                "connect": "PC{port}ON{pin:02d}",
                "open": "PC0ON{pin:02d}",
                "clear": "CL",
                "identity": "ID",
            },
        },
    }


def route(path: list[str], settling_time_s: float | None = None):
    return BenchConfigExtended.model_validate(
        {
            "bench_name": "native_switch",
            "devices": {"matrix": {"profile": "unused"}},
            "routes": {
                "r": {
                    "device": "matrix",
                    "settling_time_s": settling_time_s,
                    "connects": [{"from": "source", "to": "dut", "path": path}],
                }
            },
        }
    ).routes["r"]


def test_profile_translates_generic_route_without_scpi():
    io = FakeIO()
    matrix = AutoDevice.from_dict(config(), backend_override=io)
    assert isinstance(matrix, SwitchMatrixDevice)
    matrix.apply_route(
        "r",
        route(["P1:12", "P2:12"]),
        safety_context={"source_outputs_zero": True, "matrix_closed": True},
    )
    assert io.writes == ["PC1ON12", "PC2ON12"]
    assert matrix.identity() == "HP 4084B REV. 3.0"
    assert matrix.read_status_byte() == 0x43


def test_profile_guard_and_preflight_happen_before_io():
    io = FakeIO()
    matrix = AutoDevice.from_dict(config(), backend_override=io)
    try:
        matrix.apply_route("r", route(["P1:12"]), safety_context={})
    except ValueError as exc:
        assert "source_outputs_zero" in str(exc)
    else:
        raise AssertionError("missing safety context accepted")
    assert io.writes == []

    try:
        matrix.apply_route(
            "r",
            route(["P1:12", "P99:12"]),
            safety_context={"source_outputs_zero": True, "matrix_closed": True},
        )
    except ValueError as exc:
        assert "above profile maximum" in str(exc)
    else:
        raise AssertionError("invalid crosspoint accepted")
    assert io.writes == []


def test_second_profile_protocol_uses_same_high_level_api():
    data = config()
    data["switch"] = {
        "crosspoint": {"pattern": r"X(?P<slot>[0-9]+)", "fields": ["slot"]},
        "commands": {
            "connect": "CLOSE X{slot}",
            "open": "OPEN X{slot}",
            "clear": "OPEN ALL",
            "identity": "WHO?",
        },
    }
    data["channels"] = ["X1"]
    io = FakeIO()
    matrix = AutoDevice.from_dict(data, backend_override=io)
    matrix.apply_route("r", route(["X1"]))
    assert io.writes == ["CLOSE X1"]


def test_packaged_hp_profile_uses_generic_route_api_without_context():
    import pytest

    io = FakeIO()
    matrix = AutoDevice.from_preset("hp/HP4084B", backend_override=io)
    path = route(["P1:12"])
    matrix.apply_route("r", path)
    assert matrix.route_state()["active_route"] == "r"
    with pytest.raises(NotImplementedError, match="connection_state"):
        matrix.preflight_recipe(path, name="r")
    matrix.guard_pin(12)
    matrix.open_route(path)
    matrix.open_all()
    assert io.writes == ["PC1ON12", "PC1GD12", "PC0ON12", "CL"]
    assert io.queries == []
    assert io.terminations == ["\n"]


def test_profile_preflights_open_clear_identity_before_connect_and_invalidates_state():
    data = config()
    data["switch"]["success_token"] = "0"
    io = AckIO()
    matrix = AutoDevice.from_dict(data, backend_override=io)
    matrix.validate_route(route(["P1:12"]))
    assert io.connects == 0
    matrix.open_route(
        route(["P1:12"]),
        safety_context={"source_outputs_zero": True, "matrix_closed": True},
    )
    assert matrix.route_state()["active_route"] is None
    matrix.open_all(safety_context={"source_outputs_zero": True, "matrix_closed": True})
    assert matrix.route_state()["active_route"] is None


def test_profile_acknowledgement_rejects_empty_and_token_lookalikes():
    for response in ("", "00 OK", "0bad"):
        data = config()
        data["switch"]["success_token"] = "0"
        matrix = AutoDevice.from_dict(data, backend_override=ScriptedAckIO(response))
        try:
            matrix.open_route(
                route(["P1:12"]),
                safety_context={"source_outputs_zero": True, "matrix_closed": True},
            )
        except RuntimeError as exc:
            assert "profile_error_response" in str(exc)
        else:
            raise AssertionError(f"invalid response accepted: {response!r}")


def test_empty_channels_are_allowed_only_with_profile_grammar():
    data = config()
    data["channels"] = []
    AutoDevice.from_dict(data, backend_override=FakeIO())
    legacy = dict(data)
    legacy.pop("switch")
    try:
        AutoDevice.from_dict(legacy, backend_override=FakeIO())
    except ValueError as exc:
        assert "channels" in str(exc)
    else:
        raise AssertionError("legacy profile without channels accepted")


def test_native_status_support_is_forwarded_without_connecting():
    class NoStatus(FakeIO):
        def read_status_byte(self):
            raise AssertionError("status read should not be attempted")

        def supports_native_status_byte(self):
            return False

    matrix = AutoDevice.from_dict(config(), backend_override=NoStatus())
    assert matrix.supports_native_status_byte() is False


def test_failed_state_change_invalidates_previous_route_claim():
    io = FailingIO()
    matrix = AutoDevice.from_dict(config(), backend_override=io)
    matrix.apply_route(
        "first",
        route(["P1:12"]),
        safety_context={"source_outputs_zero": True, "matrix_closed": True},
    )
    assert matrix.route_state()["active_route"] == "first"
    try:
        matrix.apply_route(
            "second",
            route(["P1:12", "P2:12"]),
            safety_context={"source_outputs_zero": True, "matrix_closed": True},
        )
    except RuntimeError as exc:
        assert "relay write failure" in str(exc)
    else:
        raise AssertionError("simulated relay failure did not propagate")
    assert matrix.route_state()["active_route"] is None


def test_profile_route_settling_is_local_and_does_not_emit_scpi(monkeypatch):
    io = FakeIO()
    matrix = AutoDevice.from_dict(config(), backend_override=io)
    delays: list[float] = []
    monkeypatch.setattr("pytestlab.devices.switch_matrix.time.sleep", delays.append)
    route_with_settle = route(["P1:12"], settling_time_s=0.25)
    matrix.apply_route(
        "r",
        route_with_settle,
        safety_context={"source_outputs_zero": True, "matrix_closed": True},
    )
    assert delays == [0.25]
    assert all(not command.startswith("ROUTE:") for command in io.writes)


def test_failed_open_or_clear_invalidates_previous_active_route():
    import pytest

    for action in ("open", "clear"):
        io = FakeIO()
        matrix = AutoDevice.from_dict(config(), backend_override=io)
        context = {"source_outputs_zero": True, "matrix_closed": True}
        matrix.apply_route("first", route(["P1:12"]), safety_context=context)

        def fail(command):
            raise RuntimeError("partial switching failure")

        io.write = fail
        with pytest.raises(RuntimeError, match="partial switching failure"):
            if action == "open":
                matrix.open_route(route(["P1:12"]), safety_context=context)
            else:
                matrix.open_all(safety_context=context)
        assert matrix.route_state()["active_route"] is None


def test_exclusive_clear_and_route_are_one_serialized_transaction():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from unittest.mock import patch

    io = FakeIO()
    matrix = AutoDevice.from_dict(config(), backend_override=io)
    context = {"source_outputs_zero": True, "matrix_closed": True}
    first_route = route(["P1:12"])
    first_route.exclusive_group = "measurement"
    clear_finished, resume_route, other_done = Event(), Event(), Event()
    original_clear = matrix._profile_backend.clear

    def pause_after_clear():
        result = original_clear()
        clear_finished.set()
        assert resume_route.wait(2)
        return result

    def open_other_route():
        try:
            matrix.open_route(route(["P1:12"]), safety_context=context)
        finally:
            other_done.set()

    with patch.object(matrix._profile_backend, "clear", pause_after_clear):
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(
                matrix.apply_route, "first", first_route, safety_context=context
            )
            assert clear_finished.wait(2)
            second = executor.submit(open_other_route)
            try:
                assert not other_done.wait(0.05)
                assert io.writes == ["CL"]
            finally:
                resume_route.set()
            first.result(timeout=2)
            second.result(timeout=2)
    assert io.writes == ["CL", "PC1ON12", "PC0ON12"]


def test_legacy_failed_open_or_clear_also_invalidates_route_state():
    import pytest

    for action in ("open", "clear"):
        io = FakeIO()
        data = config()
        data.pop("switch")
        matrix = AutoDevice.from_dict(data, backend_override=io)
        matrix.apply_route("first", route(["P1:12"]))

        def fail(command):
            raise RuntimeError("legacy switching failure")

        io.write = fail
        with pytest.raises(RuntimeError, match="legacy switching failure"):
            if action == "open":
                matrix.open_route(route(["P1:12"]))
            else:
                matrix.open_all()
        assert matrix.route_state()["active_route"] is None


def test_profile_default_settling_time_is_used_without_a_route_override(monkeypatch):
    data = config()
    data["settling_time_s"] = 0.125
    matrix = AutoDevice.from_dict(data, backend_override=FakeIO())
    delays = []
    monkeypatch.setattr("pytestlab.devices.switch_matrix.time.sleep", delays.append)
    matrix.apply_route(
        "r",
        route(["P1:12"]),
        safety_context={
            "source_outputs_zero": True,
            "matrix_closed": True,
        },
    )
    assert delays == [0.125]


def test_profile_switch_preserves_lazy_backend_allocation():
    from pytestlab.devices.base import _BackendFactory
    from pytestlab.switch_profile import ProfileSwitchBackend

    allocations = []
    io = FakeIO()

    def build():
        allocations.append(True)
        return io

    switch = ProfileSwitchBackend(
        _BackendFactory(build),
        {"crosspoint": {"pattern": r"(?P<channel>.+)"}, "commands": {"clear": "CLEAR"}},
    )
    assert switch.command_for("clear") == "CLEAR"
    switch.close()
    switch.disconnect()
    assert allocations == []
    switch.connect()
    assert allocations == [True]
    assert io.connects == 1
    switch.close()
