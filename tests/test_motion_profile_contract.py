from __future__ import annotations

from copy import deepcopy
from unittest.mock import patch

import pytest

from pytestlab import AutoDevice
from pytestlab.config.device_config import DeviceConfig
from pytestlab.errors import InstrumentConfigurationError
from pytestlab.motion import MotionFaultError
from pytestlab.motion import OperationState
from pytestlab.motion_profile import ProfileMotionDevice


class Wire:
    def __init__(self, response="0 1000 -500 6600 0 31"):
        self.response = response
        self.calls = []

    def connect(self):
        self.calls.append(("connect",))

    def disconnect(self):
        self.calls.append(("disconnect",))

    def close(self):
        self.calls.append(("close",))

    def write(self, command):
        self.calls.append(("write", command))

    def query(self, command, delay=None):
        self.calls.append(("query", command, delay))
        return self.response

    def set_read_termination(self, value):
        self.calls.append(("termination", value))

    def set_write_termination(self, value):
        self.write_termination = value


def make(spec, wire=None):
    wire = Wire() if wire is None else wire
    config = DeviceConfig(
        manufacturer="Example",
        model="stage",
        device_type="motion_stage",
        role="fixture",
        motion=spec,
    )
    return ProfileMotionDevice(config, wire), wire


def spec():
    return {
        "axes": [{"name": "x", "units": "mm"}, {"name": "y", "units": "mm"}],
        "wire_scale": 1000,
        "success_token": "0",
        "commands": {"move_relative": {"template": "34 {x} {y} R"}},
        "queries": {
            "position": {
                "template": "31",
                "response": {
                    "type": "axis_tuple",
                    "skip": 1,
                    "axes": ["x", "y", "z"],
                    "scale": 0.001,
                },
            },
        },
    }


def test_infer_only_implemented_operations_and_explicit_empty_means_none():
    stage, wire = make(spec())
    assert stage.get_capabilities().supports == {"move_relative", "position"}
    with pytest.raises(NotImplementedError):
        stage.home()
    assert wire.calls == []
    empty = spec()
    empty["supports"] = []
    stage, wire = make(empty)
    assert stage.get_capabilities().supports == frozenset()
    with pytest.raises(NotImplementedError):
        stage.get_position()
    assert wire.calls == []


@pytest.mark.parametrize(
    "bound", [{"minimum": -100}, {"maximum": 100}, {"max": 100}, {"min": -100}]
)
@pytest.mark.parametrize("explicit", [False, True])
def test_bounded_relative_motion_fails_closed_at_both_layers(bound, explicit):
    settings = spec()
    settings["axes"][0].update(bound)
    settings["operations"] = {"move_relative": {"template": "34 {x} {y} R"}}
    if explicit:
        settings["supports"] = ["move_relative", "position"]
    stage, wire = make(settings)
    assert "move_relative" not in stage.get_capabilities().supports
    assert "move_relative" not in stage._backend.get_motion_capabilities().supports
    with pytest.raises(NotImplementedError, match="move_relative"):
        stage.move_relative({"x": 2.0})
    with pytest.raises(NotImplementedError, match="axis bounds"):
        stage._backend.motion_command("move_relative", operation_id="fixture", offset={"x": 2.0})
    with pytest.raises(NotImplementedError, match="axis bounds"):
        stage.operation("move_relative", x=2.0, y=0.0)
    assert wire.calls == []


def commands(wire):
    return [call[1] for call in wire.calls if call[0] in {"query", "write"}]


def bounded_relative_spec():
    settings = spec()
    settings["axes"][0].update(minimum=-100, maximum=100)
    settings["axes"][1].update(minimum=-100, maximum=100)
    settings["commands"]["move_absolute"] = {"template": "34 {x} {y} H"}
    del settings["commands"]["move_relative"]
    settings["relative_from_position"] = ["x", "y"]
    return settings


def test_opt_in_infers_relative_capability_without_native_relative_command():
    stage, wire = make(bounded_relative_spec())
    assert stage.get_capabilities().supports == {"move_relative", "move_absolute", "position"}
    assert stage._backend.get_motion_capabilities().supports == stage.get_capabilities().supports
    assert wire.calls == []
    result = stage.move_relative(x=0.25)
    assert commands(wire) == ["31", "34 1250.0 -500.0 H"]
    assert result.details["target"] == {"x": 1.25, "y": -0.5}


def test_opt_in_never_allows_opaque_native_relative_move_to_bypass_position_check():
    settings = bounded_relative_spec()
    settings["operations"] = {"move_relative": {"template": "34 {x} {y} R"}}
    stage, wire = make(settings)
    with pytest.raises(NotImplementedError):
        stage.operation("move_relative", x=2.0, y=0.0)
    with pytest.raises(NotImplementedError):
        stage._backend.operation("move_relative", x=2.0, y=0.0)
    assert wire.calls == []


@pytest.mark.parametrize("kwargs", [{"units": "um"}, {"frame": "other"}, {"z": 1.0}])
def test_opt_in_rejects_invalid_coordinates_before_position_query(kwargs):
    stage, wire = make(bounded_relative_spec())
    with pytest.raises((ValueError, NotImplementedError)):
        stage.move_relative(x=0.1, **kwargs)
    assert commands(wire) == []


def test_opt_in_rejects_group_that_omits_an_axis_written_by_absolute_move():
    settings = bounded_relative_spec()
    settings["axis_groups"] = [{"name": "x-only", "axes": ["x"]}]
    stage, wire = make(settings)
    with pytest.raises(ValueError, match="axis group"):
        stage.move_relative(x=0.1, axis_group="x-only")
    assert commands(wire) == []


@pytest.mark.parametrize(
    "relative_settings",
    [
        {"relative_from_position": ["x", "unknown"]},
        {"supports": ["move_relative", "position"]},
        {"supports": ["move_relative", "move_absolute"]},
        {"commands": {}},
        {"queries": {}},
    ],
)
def test_invalid_relative_opt_in_does_not_advertise_capability(relative_settings):
    settings = bounded_relative_spec()
    settings.update(relative_settings)
    wire = Wire()
    with pytest.raises(ValueError, match="relative_from_position"):
        stage, _ = make(settings, wire)
        stage.get_capabilities()
    assert wire.calls == []


@pytest.mark.parametrize(
    "response,delta",
    [("0 99000 -500 0", 2.0), ("0 -99000 -500 0", -2.0), ("0 1000 101000 0", 0.25)],
)
def test_packaged_pa200_rejects_outside_endpoint_even_on_omitted_axis(response, delta):
    wire = Wire(response)
    pa = AutoDevice.from_preset("suss/PA200", backend_override=wire)
    with pytest.raises(ValueError, match="(above|below) axis"):
        pa.move_relative(x=delta)
    assert commands(wire) == ["31"]


@pytest.mark.parametrize(
    "response", ["", "1 fault", "0 99000", "0 bad -500 0", "0 nan -500 0", "0 99000 inf 0"]
)
def test_packaged_pa200_bad_fresh_position_never_moves(response):
    wire = Wire(response)
    pa = AutoDevice.from_preset("suss/PA200", backend_override=wire)
    with pytest.raises(MotionFaultError):
        pa.move_relative(x=0.25)
    assert commands(wire) == ["31"]


def test_packaged_pa200_relative_inclusive_limit_does_not_claim_measured_completion():
    wire = Wire("0 99000 -500 0")
    pa = AutoDevice.from_preset("suss/PA200", backend_override=wire)
    assert "move_relative" in pa.get_capabilities().supports
    assert wire.calls == []
    result = pa.move_relative(x=1.0)
    assert commands(wire) == ["31", "34 100000.0 -500.0 H"]
    assert result.operation == "move_relative"
    assert result.requested == {"x": 1.0}
    assert result.details["target"] == {"x": 100.0, "y": -0.5}
    assert result.state == OperationState.RUNNING
    assert result.actual is None


def test_packaged_pa200_outside_absolute_rejected_and_ack_never_means_settled():
    wire = Wire("0 99000 0 0")
    pa = AutoDevice.from_preset("suss/PA200", backend_override=wire)
    with pytest.raises(ValueError, match="above axis maximum"):
        pa.move_absolute(x=101.0, y=0.0)
    assert commands(wire) == []
    receipt = pa.move_absolute(x=100.0, y=0.0)
    assert receipt.state == OperationState.RUNNING
    assert receipt.actual is None
    assert not pa.get_status().settled


@pytest.mark.parametrize("response", ["", "01 not-success", "1 fault", "0bad malformed"])
def test_exact_success_token_rejects_empty_and_prefix_lookalikes(response):
    stage, _ = make(spec(), Wire(response))
    with pytest.raises(MotionFaultError, match="motion_error_response"):
        stage.get_position()


def test_termination_and_query_delay_are_profile_owned_without_initial_wait():
    settings = spec()
    settings.update(
        message_io={"read_termination": "\r\n"},
        min_command_interval_s=0.1,
        query_delay_s=0.1,
    )
    stage, wire = make(settings)
    assert wire.calls == []
    with patch("pytestlab.profile_transport.time.sleep") as sleep:
        assert stage.get_position() == pytest.approx({"x": 1, "y": -0.5, "z": 6.6})
    assert wire.calls == [("termination", "\r\n"), ("connect",), ("query", "31", 0.1)]
    sleep.assert_not_called()


def test_acknowledgement_does_not_implicitly_complete_motion():
    stage, wire = make(spec(), Wire("0 accepted"))
    receipt = stage.move_relative({"x": 0.01, "y": -0.005})
    assert receipt.state == OperationState.RUNNING
    assert wire.calls[-1] == ("query", "34 10.0 -5.0 R", None)


def test_profile_can_explicitly_declare_synchronous_completion():
    settings = spec()
    settings["commands"]["move_relative"]["result_state"] = "succeeded"
    stage, _ = make(settings, Wire("0 complete"))
    assert stage.move_relative({"x": 0, "y": 0}).state == OperationState.SUCCEEDED


@pytest.mark.parametrize(
    "kwargs", [{"units": "um"}, {"frame": "unmapped"}, {"axis_group": "missing"}]
)
def test_coordinate_metadata_is_not_silently_ignored(kwargs):
    stage, wire = make(spec())
    with pytest.raises((ValueError, NotImplementedError)):
        stage.move_relative({"x": 0, "y": 0}, **kwargs)
    assert not any(call[0] in {"query", "write"} for call in wire.calls)


def test_declared_stop_and_rotation_use_the_same_generic_command_path():
    settings = spec()
    settings["commands"].update(
        {
            "stop": {"template": "HALT {mode}"},
            "rotate_absolute": {"template": "ANGLE {theta_deg}"},
        }
    )
    stage, wire = make(settings, Wire("0 accepted"))
    stage.stop()
    stage.rotate_absolute(1.5)
    assert ("query", "HALT controlled", None) in wire.calls
    assert ("query", "ANGLE 1.5", None) in wire.calls


@pytest.mark.parametrize(
    "field,value",
    [
        ("min_command_interval_s", float("nan")),
        ("query_delay_s", -0.1),
        ("query_delay_s", float("inf")),
        ("wire_scale", 0),
    ],
)
def test_invalid_transport_metadata_fails_offline(field, value):
    settings = spec()
    settings[field] = value
    wire = Wire()
    with pytest.raises(ValueError):
        make(settings, wire)
    assert wire.calls == []


def test_profile_response_parsing_supports_delimiters_without_device_code():
    settings = spec()
    settings["queries"]["position"]["response"]["delimiter"] = ":"
    settings["success_pattern"] = r"^0:.*"
    settings.pop("success_token")
    stage, _ = make(settings, Wire("0:1000:-500:6600"))
    assert stage.get_position() == pytest.approx({"x": 1, "y": -0.5, "z": 6.6})


def test_named_axis_home_cannot_silently_home_every_axis():
    settings = spec()
    settings["commands"]["home"] = {"template": "HOME-ALL"}
    stage, wire = make(settings, Wire("0 accepted"))
    with pytest.raises(NotImplementedError):
        stage.home("x")
    assert not any(call[0] in {"query", "write"} for call in wire.calls)


def test_packaged_prober_uses_generic_factory_and_capability_cli(monkeypatch):
    from typer.testing import CliRunner

    from pytestlab.cli import app

    wire = Wire()
    prober = AutoDevice.from_preset("suss/PA200", backend_override=wire)
    assert isinstance(prober, ProfileMotionDevice)
    assert "wait" not in prober.get_capabilities().supports
    assert not prober._backend.has_operation("reset_chuck")
    bench = type("Bench", (), {"devices": {"prober": prober}, "close_all": lambda _: None})()
    monkeypatch.setattr("pytestlab.cli_typer._open_cli_bench", lambda _, **_kwargs: bench)
    with patch("pytestlab.profile_transport.time.sleep"):
        result = CliRunner().invoke(app, ["position", "prober", "--json"])
    assert result.exit_code == 0, result.stdout
    assert '"x": 1.0' in result.stdout
    assert ("query", "31", 0.1) in wire.calls
    assert not any(call[0] == "write" for call in wire.calls)


def test_second_protocol_has_identical_public_api():
    settings = deepcopy(spec())
    settings["wire_scale"] = 1
    settings["commands"]["move_relative"]["template"] = "SHIFT {x},{y}"
    settings["queries"]["position"] = {
        "template": "WHERE",
        "response": {"type": "axis_tuple", "axes": ["x", "y"]},
    }
    settings.pop("success_token")
    stage, wire = make(settings, Wire("2.5 -1.0"))
    stage.move_relative({"x": 0.25, "y": -0.1})
    assert stage.get_position() == {"x": 2.5, "y": -1}
    assert ("write", "SHIFT 0.25,-0.1") in wire.calls
    assert ("query", "WHERE", None) in wire.calls


def test_motion_cli_reports_unsupported_capability_without_a_traceback(monkeypatch):
    from typer.testing import CliRunner

    from pytestlab.cli import app

    settings = spec()
    settings["supports"] = []
    stage, wire = make(settings)
    bench = type("Bench", (), {"devices": {"stage": stage}, "close_all": lambda _: None})()
    monkeypatch.setattr("pytestlab.cli_typer._open_cli_bench", lambda _, **_kwargs: bench)
    result = CliRunner().invoke(app, ["position", "stage", "--json"])
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "not supported" in result.stderr
    assert isinstance(result.exception, SystemExit)
    assert wire.calls == []


def test_prober_native_status_does_not_use_a_text_command():
    wire = Wire()
    wire.read_status_byte = lambda: 0x10
    prober = AutoDevice.from_preset("suss/PA200", backend_override=wire)
    assert prober.read_status_byte() == 0x10
    assert not any(call[0] in {"write", "query"} for call in wire.calls)


def test_units_frames_and_groups_survive_yaml_factory_loading(tmp_path):
    import yaml

    config = {
        "manufacturer": "Example",
        "model": "micron-stage",
        "device_type": "motion_stage",
        "role": "fixture",
        "motion": {
            "axes": [{"name": "u", "units": "um"}],
            "units": ["um"],
            "frames": [
                {"name": "machine", "parent": "base"},
                {"name": "wafer", "parent": "machine"},
            ],
            "axis_groups": [{"name": "probe", "axes": ["u"]}],
            "commands": {"move_relative": {"template": "STEP {u} {frame}"}},
            "queries": {
                "position": {
                    "template": "WHERE",
                    "response": {
                        "type": "axis_tuple",
                        "axes": ["u"],
                    },
                }
            },
        },
    }
    path = tmp_path / "stage.yaml"
    path.write_text(yaml.safe_dump(config))
    wire = Wire("12.5")
    stage = AutoDevice.from_file(path, backend_override=wire)
    capabilities = stage.get_capabilities()
    assert capabilities.units == ("um",)
    assert capabilities.frames[0].parent == "base"
    assert capabilities.axis_groups[0].axes == ("u",)
    stage.move_relative({"u": 2.5}, units="um", frame="wafer", axis_group="probe")
    assert stage.get_position(units="um", frame="wafer") == {"u": 12.5}
    assert ("write", "STEP 2.5 wafer") in wire.calls
    with pytest.raises(ValueError, match="axis group"):
        stage.move_relative({"u": 1}, units="um", axis_group="unknown")
    with pytest.raises(ValueError, match="frame"):
        stage.get_position(units="um", frame="undeclared")


def test_profile_command_sequences_are_not_silently_truncated():
    settings = spec()
    settings["commands"]["move_relative"] = {"sequence": ["PREP", "34 {x} {y} R"]}
    stage, wire = make(settings, Wire("0 accepted"))
    stage.move_relative({"x": 0.01, "y": 0})
    assert [call[1] for call in wire.calls if call[0] == "query"] == ["PREP", "34 10.0 0.0 R"]


def test_entire_motion_sequence_formats_before_first_command():
    settings = spec()
    settings["commands"]["move_relative"] = {"sequence": ["PREP", "MOVE {missing}"]}
    stage, wire = make(settings)
    with pytest.raises(RuntimeError, match="Missing parameter"):
        stage.move_relative({"x": 0, "y": 0})
    assert not any(call[0] in {"write", "query"} for call in wire.calls)


def test_multi_transaction_query_is_rejected_instead_of_truncated():
    settings = spec()
    settings["queries"]["position"] = {"sequence": ["PREP", "31"]}
    stage, wire = make(settings)
    with pytest.raises(ValueError, match="exactly one"):
        stage.get_position()
    assert not any(call[0] in {"write", "query"} for call in wire.calls)


def test_simultaneous_queries_cannot_overlap_profile_exchanges():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    first_entered, release_first, second_entered = Event(), Event(), Event()

    class BlockingWire(Wire):
        def query(self, command, delay=None):
            if not first_entered.is_set():
                first_entered.set()
                assert release_first.wait(2)
            else:
                second_entered.set()
            return super().query(command, delay=delay)

    stage, _ = make(spec(), BlockingWire())
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(stage.get_position)
        assert first_entered.wait(2)
        second = executor.submit(stage.get_position)
        try:
            assert not second_entered.wait(0.05)
        finally:
            release_first.set()
        first.result(timeout=2)
        second.result(timeout=2)
    assert second_entered.is_set()


def test_unsupported_wait_is_rejected_before_motion_is_sent():
    stage, wire = make(spec(), Wire("0 accepted"))
    with pytest.raises(NotImplementedError, match="wait"):
        stage.move_relative({"x": 0, "y": 0}, wait=True)
    assert wire.calls == []


def test_missing_underlying_status_capability_is_reported_offline():
    stage, wire = make(spec())
    assert not stage.supports_native_status_byte()
    with pytest.raises(InstrumentConfigurationError, match="does not provide native"):
        stage.read_status_byte()
    assert wire.calls == []


def test_consistent_axis_units_are_inferred_when_profile_units_are_omitted():
    settings = spec()
    settings["axes"] = [{"name": "x", "units": "um"}, {"name": "y", "units": "um"}]
    stage, wire = make(settings)
    assert stage.get_capabilities().units == ("um",)
    with pytest.raises(ValueError, match="units"):
        stage.move_relative({"x": 0, "y": 0})
    assert not any(call[0] in {"query", "write"} for call in wire.calls)


def test_axis_group_cannot_silently_accept_other_axes():
    settings = spec()
    settings["axis_groups"] = [{"name": "x-only", "axes": ["x"]}]
    stage, wire = make(settings)
    with pytest.raises(ValueError, match="outside motion axis group"):
        stage.move_relative({"x": 0, "y": 0}, axis_group="x-only")
    assert not any(call[0] in {"query", "write"} for call in wire.calls)


def test_native_cli_reports_transport_capability_error_cleanly(monkeypatch):
    from typer.testing import CliRunner

    from pytestlab.cli import app
    from pytestlab.errors import InstrumentCommunicationError

    class UnsupportedServer(Wire):
        def query(self, command, delay=None):
            raise InstrumentCommunicationError(
                message="LAMB server does not advertise query_delay_ms capability"
            )

    stage, _ = make(spec(), UnsupportedServer())
    bench = type("Bench", (), {"devices": {"stage": stage}, "close_all": lambda _: None})()
    monkeypatch.setattr("pytestlab.cli_typer._open_cli_bench", lambda _, **_kwargs: bench)
    result = CliRunner().invoke(app, ["position", "stage", "--json"])
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "query_delay_ms" in result.stderr
    assert isinstance(result.exception, SystemExit)


def test_native_status_cli_is_generic_and_never_uses_a_query_template(monkeypatch):
    from typer.testing import CliRunner

    from pytestlab.cli import app

    wire = Wire()
    wire.read_status_byte = lambda: 0x10
    stage, _ = make(spec(), wire)
    bench = type("Bench", (), {"resources": {"stage": stage}, "close_all": lambda _: None})()
    monkeypatch.setattr("pytestlab.cli_typer._open_cli_bench", lambda _, **_kwargs: bench)
    result = CliRunner().invoke(app, ["device", "status-byte", "stage", "--json"])
    assert result.exit_code == 0, result.stdout
    assert '"status_byte": 16' in result.stdout
    assert '"status_hex": "0x10"' in result.stdout
    assert not any(call[0] in {"query", "write"} for call in wire.calls)


def test_native_status_cli_fails_cleanly_for_an_unsupported_device(monkeypatch):
    from typer.testing import CliRunner

    from pytestlab.cli import app

    stage, wire = make(spec())
    bench = type("Bench", (), {"devices": {"stage": stage}, "close_all": lambda _: None})()
    monkeypatch.setattr("pytestlab.cli_typer._open_cli_bench", lambda _, **_kwargs: bench)
    result = CliRunner().invoke(app, ["device", "status-byte", "stage"])
    assert result.exit_code == 1
    assert "does not provide native" in " ".join(result.stdout.split())
    assert isinstance(result.exception, SystemExit)
    assert wire.calls == []


def test_generic_identity_cli_does_not_probe_scpi_on_a_motion_device(monkeypatch):
    from typer.testing import CliRunner

    from pytestlab.cli import app

    stage, wire = make(spec())
    monkeypatch.setattr("pytestlab.config.loader.load_device_profile", lambda _: stage.config)
    monkeypatch.setattr(AutoDevice, "from_config", lambda **_: stage)
    result = CliRunner().invoke(app, ["device", "idn", "unused"])
    assert result.exit_code == 1
    assert "identity capability" in result.stdout
    assert not any(call[0] in {"connect", "query", "write"} for call in wire.calls)
