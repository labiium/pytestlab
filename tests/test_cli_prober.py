from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from pytestlab.cli_prober import prober_app
from pytestlab.motion import AxisSpec
from pytestlab.motion import CoordinateFrame
from pytestlab.motion import MotionCapabilities
from pytestlab.motion import MotionResult
from pytestlab.motion import OperationState


class FakeProber:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.contact_error: Exception | None = None
        self.supports = MotionCapabilities(
            axes=(AxisSpec("x"), AxisSpec("y")),
            frames=(CoordinateFrame("machine"),),
            supports=frozenset({"contact", "separate", "set_vacuum", "configure_chuck"}),
        )

    def move_absolute(self, *_args: object, **_kwargs: object) -> None:
        pass

    def move_relative(self, *_args: object, **_kwargs: object) -> None:
        pass

    def get_position(self, *_args: object, **_kwargs: object) -> dict[str, float]:
        return {"x": 0.0}

    def get_status(self, *_args: object, **_kwargs: object) -> object:
        return object()

    def get_capabilities(self) -> MotionCapabilities:
        return self.supports

    def preflight_recipe(self, required=None) -> tuple[str, ...]:
        self.calls.append(("preflight_recipe", {"required": required}))
        if required is None:
            raise NotImplementedError("contact state readback is not declared by the profile")
        return tuple(required)

    def _action(self, name: str, **kwargs: object) -> MotionResult:
        self.calls.append((name, kwargs))
        return MotionResult("operation-1", name, OperationState.SUCCEEDED)

    def contact(self, *, wait: bool = False) -> MotionResult:
        if self.contact_error is not None:
            raise self.contact_error
        return self._action("contact", wait=wait)

    def separate(self, *, wait: bool = False) -> MotionResult:
        return self._action("separate", wait=wait)

    def move_to_align(self, *, wait: bool = False) -> MotionResult:
        return self._action("move_to_align", wait=wait)

    def move_to_load(self, *, wait: bool = False) -> MotionResult:
        return self._action("move_to_load", wait=wait)

    def set_vacuum(self, enabled: bool, *, wait: bool = False) -> MotionResult:
        return self._action("set_vacuum", enabled=enabled, wait=wait)

    def configure_chuck(
        self,
        overtravel: bool,
        auto_z: bool,
        interlock: bool,
        edge_sensor: bool,
        *,
        wait: bool = False,
    ) -> MotionResult:
        return self._action(
            "configure_chuck",
            overtravel=overtravel,
            auto_z=auto_z,
            interlock=interlock,
            edge_sensor=edge_sensor,
            wait=wait,
        )

    def get_contact_state(self) -> bool:
        raise NotImplementedError("contact state readback is not declared by the profile")


class FakeBench:
    def __init__(self, resource: FakeProber) -> None:
        self.devices = {"prober": resource}
        self.closed = False

    def close_all(self) -> None:
        self.closed = True


def _install_bench(monkeypatch, resource: FakeProber) -> FakeBench:
    bench = FakeBench(resource)

    def open_bench(_path, *, aliases):
        assert aliases == {"prober"}
        return bench

    monkeypatch.setattr("pytestlab.cli_typer._open_cli_bench", open_bench)
    return bench


def test_capabilities_are_json_and_use_lazy_alias_scoped_bench(monkeypatch):
    resource = FakeProber()
    bench = _install_bench(monkeypatch, resource)

    result = CliRunner().invoke(prober_app, ["capabilities", "prober", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert [axis["name"] for axis in payload["axes"]] == ["x", "y"]
    assert payload["supports"] == ["configure_chuck", "contact", "separate", "set_vacuum"]
    assert resource.calls == []
    assert bench.closed


def test_preflight_fails_closed_on_missing_full_recipe_readback(monkeypatch):
    resource = FakeProber()
    bench = _install_bench(monkeypatch, resource)

    result = CliRunner().invoke(prober_app, ["preflight", "prober"])

    assert result.exit_code == 1
    assert "contact state readback is not declared" in result.output
    assert len(resource.calls) == 1
    assert bench.closed


def test_chuck_requires_explicit_boolean_choices_and_dispatches_typed_method(monkeypatch):
    resource = FakeProber()
    bench = _install_bench(monkeypatch, resource)
    runner = CliRunner()

    missing = runner.invoke(prober_app, ["configure-chuck", "prober", "--interlock"])
    assert missing.exit_code == 2
    assert resource.calls == []
    assert not bench.closed

    result = runner.invoke(
        prober_app,
        [
            "configure-chuck",
            "prober",
            "--no-overtravel",
            "--auto-z",
            "--no-interlock",
            "--edge-sensor",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert resource.calls == [
        (
            "configure_chuck",
            {
                "overtravel": False,
                "auto_z": True,
                "interlock": False,
                "edge_sensor": True,
                "wait": False,
            },
        )
    ]
    assert json.loads(result.stdout)["operation"] == "configure_chuck"
    assert bench.closed


def test_vacuum_requires_explicit_state(monkeypatch):
    resource = FakeProber()
    bench = _install_bench(monkeypatch, resource)

    missing = CliRunner().invoke(prober_app, ["vacuum", "prober"])
    assert missing.exit_code == 2
    assert resource.calls == []

    result = CliRunner().invoke(prober_app, ["vacuum", "prober", "--on", "--json"])
    assert result.exit_code == 0, result.output
    assert resource.calls == [("set_vacuum", {"enabled": True, "wait": False})]
    assert json.loads(result.stdout)["operation"] == "set_vacuum"
    assert bench.closed


def test_contact_command_forwards_wait_and_closes_bench_on_failure(monkeypatch):
    resource = FakeProber()
    bench = _install_bench(monkeypatch, resource)

    result = CliRunner().invoke(prober_app, ["contact", "prober", "--wait", "--json"])

    assert result.exit_code == 0, result.output
    assert resource.calls == [("contact", {"wait": True})]
    assert json.loads(result.stdout)["operation"] == "contact"
    assert bench.closed

    resource.contact_error = NotImplementedError("profile does not support verified waiting")
    bench = _install_bench(monkeypatch, resource)
    failed = CliRunner().invoke(prober_app, ["contact", "prober", "--wait"])
    assert failed.exit_code == 1
    assert "verified waiting" in failed.output
    assert bench.closed


def test_missing_physical_readback_returns_error_and_closes_bench(monkeypatch):
    resource = FakeProber()
    bench = _install_bench(monkeypatch, resource)

    result = CliRunner().invoke(prober_app, ["contact-state", "prober"])

    assert result.exit_code == 1
    assert "contact state readback is not declared" in result.output
    assert bench.closed


@pytest.mark.parametrize(
    ("command", "options"),
    [
        ("vacuum", []),
        ("configure-chuck", ["--auto-z", "--interlock", "--edge-sensor"]),
        ("configure-chuck", ["--overtravel", "--interlock", "--edge-sensor"]),
        ("configure-chuck", ["--overtravel", "--auto-z", "--edge-sensor"]),
        ("configure-chuck", ["--overtravel", "--auto-z", "--interlock"]),
    ],
)
def test_prober_partial_boolean_choices_never_open_bench(monkeypatch, command, options):
    opened = []

    def open_bench(*args, **kwargs):
        opened.append((args, kwargs))
        pytest.fail("incomplete safety choices must not open a bench")

    monkeypatch.setattr("pytestlab.cli_typer._open_cli_bench", open_bench)
    result = CliRunner().invoke(prober_app, [command, "prober", *options])
    assert result.exit_code == 2, result.output
    assert opened == []
