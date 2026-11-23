from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from pytestlab.camera import Camera
from pytestlab.cli import app
from pytestlab.cli import resolve_bench_path
from pytestlab.config.device_config import DeviceConfig
from pytestlab.motion import MotionDevice


class CameraBackend:
    def __init__(self) -> None:
        self.paths: list[Path] = []

    def connect(self) -> None:
        pass

    def capture_to(self, path: str | Path, **_: object) -> None:
        self.paths.append(Path(path))
        Path(path).write_bytes(b"frame")


class MotionBackend:
    def connect(self) -> None:
        pass

    def write(self, command: str) -> None:
        self.command = command

    def query(self, command: str, delay: float | None = None) -> str:
        return '{"x": 1.0}'

    def close(self) -> None:
        pass


def _config(device_type: str) -> DeviceConfig:
    return DeviceConfig(
        manufacturer="test", model=device_type, device_type=device_type, role="fixture"
    )


def test_resolve_bench_prefers_explicit_then_environment_then_nearest(tmp_path, monkeypatch):
    explicit = tmp_path / "explicit.yaml"
    explicit.write_text("bench_name: explicit\n")
    env = tmp_path / "env.yaml"
    env.write_text("bench_name: env\n")
    monkeypatch.setenv("PYTESTLAB_BENCH", str(env))
    assert resolve_bench_path(explicit) == explicit.resolve()
    assert resolve_bench_path() == env.resolve()

    monkeypatch.delenv("PYTESTLAB_BENCH")
    nested = tmp_path / "nested"
    nested.mkdir()
    nearest = nested / "bench.yml"
    nearest.write_text("bench_name: nearest\n")
    monkeypatch.chdir(nested)
    assert resolve_bench_path() == nearest.resolve()


def test_resolve_bench_rejects_ambiguity_and_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "bench.yaml").write_text("bench_name: one\n")
    (tmp_path / "bench.yml").write_text("bench_name: two\n")
    try:
        resolve_bench_path()
    except ValueError as exc:
        assert "Ambiguous" in str(exc)
    else:
        raise AssertionError("expected ambiguous bench failure")
    (tmp_path / "bench.yml").unlink()
    (tmp_path / "bench.yaml").unlink()
    try:
        resolve_bench_path()
    except FileNotFoundError as exc:
        assert "No bench configuration" in str(exc)
    else:
        raise AssertionError("expected missing bench failure")


def test_camera_capture_single_and_repeated_paths(monkeypatch, tmp_path):
    backend = CameraBackend()
    resource = Camera(_config("camera"), backend)
    bench = type(
        "Bench", (), {"devices": {"microscope": resource}, "close_all": lambda self: None}
    )()
    monkeypatch.setattr("pytestlab.cli_typer._open_cli_bench", lambda _, **_kwargs: bench)
    runner = CliRunner()

    single = runner.invoke(app, ["camera", "capture", "microscope", str(tmp_path / "x.png")])
    assert single.exit_code == 0
    assert (tmp_path / "x.png").read_bytes() == b"frame"

    repeated = runner.invoke(
        app,
        ["camera", "capture", "microscope", str(tmp_path / "x.png"), "--count", "2", "--json"],
    )
    assert repeated.exit_code == 0
    payload = json.loads(repeated.stdout)
    assert payload["paths"] == [str(tmp_path / "x_001.png"), str(tmp_path / "x_002.png")]


def test_camera_capture_requires_alias(monkeypatch):
    def unexpected_open(*args, **kwargs):
        raise AssertionError("missing alias reached bench opening")

    monkeypatch.setattr("pytestlab.cli_typer._open_cli_bench", unexpected_open)
    result = CliRunner().invoke(app, ["camera", "capture"])

    assert result.exit_code == 2
    assert "Missing argument" in result.output


def test_camera_list_json_reports_capabilities(monkeypatch):
    resource = Camera(_config("camera"), CameraBackend())
    bench = type(
        "Bench", (), {"devices": {"microscope": resource}, "close_all": lambda self: None}
    )()
    monkeypatch.setattr("pytestlab.cli_typer._open_cli_bench", lambda _, **_kwargs: bench)

    result = CliRunner().invoke(app, ["camera", "list", "--json"])

    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)[0]["alias"] == "microscope"


def test_motion_commands_dispatch_capabilities(monkeypatch):
    resource = MotionDevice(_config("motion"), MotionBackend())
    bench = type("Bench", (), {"devices": {"stage": resource}, "close_all": lambda self: None})()
    monkeypatch.setattr("pytestlab.cli_typer._open_cli_bench", lambda _, **_kwargs: bench)
    runner = CliRunner()

    moved = runner.invoke(app, ["move", "stage", "x=2", "y=-1"])
    assert moved.exit_code == 0
    assert json.loads(resource._backend.command.split(" ", 2)[2])["position"] == {
        "x": 2.0,
        "y": -1.0,
    }
    homed = runner.invoke(app, ["home", "stage", "x", "y"])
    stopped = runner.invoke(app, ["stop", "stage"])
    positioned = runner.invoke(app, ["position", "stage", "--json"])
    assert homed.exit_code == stopped.exit_code == positioned.exit_code == 0
    assert json.loads(positioned.stdout) == {"x": 1.0}
