from __future__ import annotations

import json
from io import StringIO

import pytest
import yaml
from rich.console import Console
from typer.main import get_command
from typer.testing import CliRunner

from pytestlab import cli
from pytestlab import cli_typer
from pytestlab.bench import Bench
from pytestlab.devices import AutoDevice
from pytestlab.motion import MotionResult
from pytestlab.motion import MotionStatus
from pytestlab.motion import OperationState


def test_public_help_matches_visible_commands_and_hides_legacy_motion(monkeypatch, capsys):
    root = get_command(cli_typer.app)
    visible = {name for name, command in root.commands.items() if not command.hidden}
    monkeypatch.setattr(cli.sys, "argv", ["ptl", "--help"])
    assert cli.main() == 0
    advertised = capsys.readouterr().out.split("Commands:\n", 1)[1].split()
    assert set(advertised) == visible
    assert len(advertised) == len(visible)
    assert {"bench", "motion", "camera", "prober"} <= visible
    assert root.commands["move"].hidden
    motion = root.commands["motion"]
    assert set(motion.commands) == {"position", "move", "status"}
    prober = root.commands["prober"]
    assert {name for name, cmd in prober.commands.items() if not cmd.hidden} == {
        "contact",
        "separate",
    }
    for args in (["move", "--help"], ["prober", "vacuum", "--help"]):
        assert CliRunner().invoke(cli_typer.app, args).exit_code == 0


@pytest.mark.parametrize("selector", ["nearest", "env", "option", "positional"])
def test_bench_inventory_and_validate_resolve_same_descriptor_without_backends(
    monkeypatch, tmp_path, selector
):
    descriptor = tmp_path / ("bench.yaml" if selector == "nearest" else "chosen.yml")
    descriptor.write_text(
        """
bench_name: Offline station
backend_defaults: {type: visa}
devices:
  microscope:
    device_type: camera
    backend: {type: lamb, resource_string: CAMERA::known}
instruments:
  meter:
    profile: keysight/34470A
"""
    )
    nested = tmp_path / "nested"
    nested.mkdir()
    monkeypatch.chdir(nested)
    monkeypatch.delenv("PYTESTLAB_BENCH", raising=False)

    def forbidden(*_args, **_kwargs):
        pytest.fail("inventory/validation must not open benches or construct backends")

    monkeypatch.setattr(Bench, "open", forbidden)
    monkeypatch.setattr(AutoDevice, "_build_backend", forbidden)
    monkeypatch.setattr("pytestlab.bench.prepare_backend_resources", forbidden)
    if selector == "env":
        monkeypatch.setenv("PYTESTLAB_BENCH", str(descriptor))
    extra = (
        ["--bench", str(descriptor)]
        if selector == "option"
        else [str(descriptor)]
        if selector == "positional"
        else []
    )
    runner = CliRunner()
    listed = runner.invoke(cli_typer.app, ["bench", "ls", "--json", *extra])
    assert listed.exit_code == 0, listed.output
    payload = json.loads(listed.stdout)
    assert payload["path"] == str(descriptor.resolve())
    rows = {row["alias"]: row for row in payload["resources"]}
    assert rows["microscope"]["address"] == "CAMERA::known"
    assert rows["microscope"]["backend"] == "lamb"
    assert rows["meter"]["address"] is None
    assert rows["meter"]["backend"] is None
    assert rows["meter"]["simulate"] is False

    text = runner.invoke(cli_typer.app, ["bench", "ls", *extra])
    assert text.exit_code == 0
    assert "Unknown" in text.stdout
    assert "N/A (simulated)" not in text.stdout
    validated = runner.invoke(cli_typer.app, ["bench", "validate", *extra])
    assert validated.exit_code == 0, validated.output
    assert "keysight/34470A" in validated.stdout


@pytest.fixture
def strict_validation_tripwires(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("strict validation reached plugin loading, a runtime factory, or a hook")

    monkeypatch.setattr("pytestlab.devices.registry.load_entry_points", forbidden)
    monkeypatch.setattr("pytestlab.config.loader.load_import_path", forbidden)
    monkeypatch.setattr("pytestlab.devices.factory.load_import_path", forbidden)
    monkeypatch.setattr("pytestlab.bench.prepare_backend_resources", forbidden)
    monkeypatch.setattr(Bench, "open", forbidden)
    monkeypatch.setattr(Bench, "_run_automation_hook", forbidden)
    monkeypatch.setattr(AutoDevice, "from_config", forbidden)
    monkeypatch.setattr(AutoDevice, "_instantiate_loaded_config", forbidden)
    monkeypatch.setattr(AutoDevice, "_build_backend", forbidden)


@pytest.mark.usefixtures("strict_validation_tripwires")
@pytest.mark.parametrize(
    ("instrument_function", "rule", "camera_address", "error"),
    [
        ("dc_voltage", "meter['profile'] == 'keysight/34470A'", "CAMERA::known", None),
        ("unsupported_sensor", "True", "CAMERA::known", "is not supported"),
        ("dc_voltage", "False", "CAMERA::known", "Custom validation failed"),
        ("dc_voltage", "unknown_function()", "CAMERA::known", "Unsupported validation expression"),
        ("dc_voltage", "True", None, "requires an explicit nonempty address"),
    ],
)
def test_strict_validate_statically_checks_executable_plan_and_fail_closed_rules(
    tmp_path, instrument_function, rule, camera_address, error
):
    descriptor = tmp_path / "bench.yaml"
    camera = {"device_type": "camera", "backend": {"type": "lamb"}}
    if camera_address is not None:
        camera["address"] = camera_address
    descriptor.write_text(
        yaml.safe_dump(
            {
                "bench_name": "Strict offline station",
                "devices": {"camera": camera},
                "instruments": {"meter": {"profile": "keysight/34470A"}},
                "automation": {"pre_experiment": ["never-run"], "post_experiment": ["never-run"]},
                "custom_validations": [rule],
                "measurement_plan": [
                    {
                        "name": "check_meter",
                        "instrument": "meter",
                        "target": {"kind": "multimeter_function", "function": instrument_function},
                    }
                ],
            }
        )
    )

    result = CliRunner().invoke(cli_typer.app, ["bench", "validate", str(descriptor), "--strict"])
    assert result.exit_code == (0 if error is None else 1), result.output
    if error is None:
        assert "Strict offline validation passed" in result.output
    else:
        assert error in " ".join(result.output.split())
        assert "Strict offline validation passed" not in result.output
        assert "is valid." not in result.output


@pytest.mark.usefixtures("strict_validation_tripwires")
@pytest.mark.parametrize("key", ["driver", "config_model"])
def test_strict_validate_rejects_custom_profile_import_before_plugin_loading(tmp_path, key):
    profile = tmp_path / "meter.yaml"
    profile.write_text(
        yaml.safe_dump({"device_type": "multimeter", key: "custom_extension:NeverImport"})
    )
    descriptor = tmp_path / "bench.yaml"
    descriptor.write_text(
        yaml.safe_dump(
            {"bench_name": "Custom profile", "instruments": {"meter": {"file": profile.name}}}
        )
    )

    result = CliRunner().invoke(cli_typer.app, ["bench", "validate", str(descriptor), "--strict"])
    assert result.exit_code == 1
    assert f"Custom {key} imports are not supported" in " ".join(result.output.split())
    assert "Strict offline validation passed" not in result.output


@pytest.mark.parametrize("verb", ["ls", "validate"])
def test_bench_commands_refuse_two_explicit_paths(verb):
    result = CliRunner().invoke(cli_typer.app, ["bench", verb, "one.yaml", "--bench", "two.yaml"])
    assert result.exit_code == 2
    assert "Specify the bench path once" in result.output


class _FakeMotion:
    def __init__(self, state):
        self.state = state
        self.closed = 0
        self.devices = {"stage": self}

    def move_absolute(self, coordinates, **_kwargs):
        return MotionResult("move-1", "move_absolute", self.state, requested=coordinates)

    move_relative = move_absolute

    def get_position(self, **_kwargs):
        return {"x": 1.5, "y": -2.0}

    def get_status(self):
        return MotionStatus("idle", settled=True)

    def close_all(self):
        self.closed += 1


@pytest.mark.parametrize(
    ("state", "label", "exit_code"),
    [
        (OperationState.SUCCEEDED, "Completed", 0),
        (OperationState.QUEUED, "Queued", 0),
        (OperationState.RUNNING, "Running", 0),
        (OperationState.CANCELLED, "Cancelled", 0),
        (OperationState.UNKNOWN, "Unconfirmed", 0),
        (OperationState.FAILED, "Failed", 1),
        (OperationState.FAULTED, "Faulted", 1),
    ],
)
def test_motion_move_named_and_legacy_stdout_contract(monkeypatch, state, label, exit_code):
    bench = _FakeMotion(state)

    def open_bench(path, *, aliases):
        assert path.name == "offline.yaml"
        assert aliases == {"stage"}
        return bench

    monkeypatch.setattr(cli_typer, "_open_cli_bench", open_bench)
    runner = CliRunner()
    command = ["move", "stage", "x=1", "--bench", "offline.yaml"]
    text = runner.invoke(cli_typer.app, ["motion", *command])
    assert text.exit_code == exit_code, text.output
    assert text.stdout == f"stage: {label} move_absolute (move-1)\n"
    assert "\x1b" not in text.stdout
    json_result = runner.invoke(cli_typer.app, [*command, "--json"])
    assert json_result.exit_code == exit_code, json_result.output
    assert json.loads(json_result.stdout)["state"] == state
    assert bool(json_result.stderr) == (exit_code != 0)
    assert bench.closed == 2


def test_motion_position_and_status_human_output_and_optional_json(monkeypatch):
    bench = _FakeMotion(OperationState.SUCCEEDED)
    monkeypatch.setattr(cli_typer, "_open_cli_bench", lambda *_args, **_kwargs: bench)
    runner = CliRunner()
    assert runner.invoke(cli_typer.app, ["motion", "position", "stage"]).stdout == (
        "stage (machine, mm): x=1.5, y=-2\n"
    )
    assert runner.invoke(cli_typer.app, ["motion", "status", "stage"]).stdout == (
        "stage: idle (settled: yes)\n"
    )
    assert json.loads(
        runner.invoke(cli_typer.app, ["motion", "position", "stage", "--json"]).stdout
    ) == {"x": 1.5, "y": -2.0}
    assert (
        json.loads(runner.invoke(cli_typer.app, ["motion", "status", "stage", "--json"]).stdout)[
            "settled"
        ]
        is True
    )

    color = StringIO()
    console = Console(file=color, force_terminal=True, color_system="standard")
    monkeypatch.setattr("rich.get_console", lambda: console)
    cli_typer._report_motion_result(MotionResult("one", "move", OperationState.SUCCEEDED))
    assert "\x1b" in color.getvalue()
