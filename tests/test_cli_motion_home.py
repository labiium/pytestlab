from __future__ import annotations

import json

from typer.testing import CliRunner

from pytestlab.cli import app
from pytestlab.motion import MotionResult
from pytestlab.motion import OperationState


class FakeMotionResource:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object, bool | None]] = []

    def move_absolute(self, *_args: object, **_kwargs: object) -> None:
        pass

    def move_relative(self, *_args: object, **_kwargs: object) -> None:
        pass

    def get_position(self, *_args: object, **_kwargs: object) -> dict[str, float]:
        return {"x": 0.0}

    def get_status(self, *_args: object, **_kwargs: object) -> object:
        return object()

    def set_home(self, axes: object = None) -> MotionResult:
        self.calls.append(("set_home", axes, None))
        return MotionResult("set-home-1", "set_home", OperationState.SUCCEEDED)

    def move_home(self, axes: object = None, *, wait: bool = False) -> MotionResult:
        self.calls.append(("move_home", axes, wait))
        return MotionResult("move-home-1", "move_home", OperationState.SUCCEEDED)


class UnsupportedHomeResource:
    def move_absolute(self, *_args: object, **_kwargs: object) -> None:
        pass

    def move_relative(self, *_args: object, **_kwargs: object) -> None:
        pass

    def get_position(self, *_args: object, **_kwargs: object) -> dict[str, float]:
        return {"x": 0.0}

    def get_status(self, *_args: object, **_kwargs: object) -> object:
        return object()


class Bench:
    def __init__(self, resource: object) -> None:
        self.devices = {"prober": resource}
        self.closed = False

    def close_all(self) -> None:
        self.closed = True


def test_set_home_dispatches_typed_capability_with_optional_axes_and_json(monkeypatch):
    resource = FakeMotionResource()
    bench = Bench(resource)
    monkeypatch.setattr("pytestlab.cli_typer._open_cli_bench", lambda _, **_kwargs: bench)

    result = CliRunner().invoke(
        app,
        ["set-home", "prober", "x", "y", "--json", "--bench", "offline.yaml"],
    )

    assert result.exit_code == 0, result.stdout
    assert resource.calls == [("set_home", ["x", "y"], None)]
    assert json.loads(result.stdout)["operation"] == "set_home"
    assert bench.closed


def test_move_home_dispatches_typed_capability_and_wait(monkeypatch):
    resource = FakeMotionResource()
    bench = Bench(resource)
    monkeypatch.setattr("pytestlab.cli_typer._open_cli_bench", lambda _, **_kwargs: bench)

    result = CliRunner().invoke(
        app,
        ["move-home", "prober", "x", "--wait", "--json", "--bench", "offline.yaml"],
    )

    assert result.exit_code == 0, result.stdout
    assert resource.calls == [("move_home", ["x"], True)]
    assert json.loads(result.stdout)["operation"] == "move_home"
    assert bench.closed


def test_home_commands_report_unsupported_capability_and_cleanup(monkeypatch):
    resource = UnsupportedHomeResource()
    bench = Bench(resource)
    monkeypatch.setattr("pytestlab.cli_typer._open_cli_bench", lambda _, **_kwargs: bench)

    result = CliRunner().invoke(app, ["set-home", "prober"])

    assert result.exit_code == 1
    assert "does not provide a MotionDevice capability" in result.output
    assert bench.closed


def test_set_home_does_not_accept_wait(monkeypatch):
    resource = FakeMotionResource()
    bench = Bench(resource)
    monkeypatch.setattr("pytestlab.cli_typer._open_cli_bench", lambda _, **_kwargs: bench)

    result = CliRunner().invoke(app, ["set-home", "prober", "--wait"])

    assert result.exit_code != 0
    assert "No such option" in result.output
    assert not bench.closed
