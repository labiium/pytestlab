from __future__ import annotations

from typing import Any
from typing import cast

import pytest

import pytestlab.bench as bench_module
from pytestlab.bench import Bench
from pytestlab.config.bench_config import BenchConfigExtended
from pytestlab.config.loader import load_device_profile
from pytestlab.devices.providers import BackendResourceScope
from pytestlab.instruments.PowerSupply import PowerSupply


class _Resource:
    def __init__(self, *, fail_connect: bool = False) -> None:
        self.fail_connect = fail_connect
        self.close_calls = 0

    def connect_backend(self) -> None:
        if self.fail_connect:
            raise RuntimeError("connect failed")

    def close(self) -> None:
        self.close_calls += 1


def _config(*aliases: str) -> BenchConfigExtended:
    return BenchConfigExtended.model_validate(
        {
            "bench_name": "cleanup",
            "devices": {alias: {"profile": "keysight/EDU34450A"} for alias in aliases},
        }
    )


def test_open_closes_prior_device_and_shared_session_on_later_device_failure(monkeypatch, tmp_path):
    config = _config("first", "second")
    first = _Resource()
    shared = _Resource()
    hooks: list[str] = []

    scope = BackendResourceScope()

    class _Provider:
        def is_configured(self, _config):
            return True

        def prepare(self, _config, *, base_path):
            return shared

        def cleanup(self, resource):
            resource.close()

    scope.add("circuit_sim", _Provider(), shared)
    monkeypatch.setattr(bench_module, "load_bench_yaml", lambda _path: config)
    monkeypatch.setattr(
        bench_module, "prepare_backend_resources", lambda _config, *, base_path: scope
    )

    def initialize(self, alias, _entry, *, must_be_instrument=False, connect=True):
        if alias == "second":
            raise RuntimeError("second failed")
        self._device_instances[alias] = first

    monkeypatch.setattr(Bench, "_initialize_device", initialize)
    monkeypatch.setattr(Bench, "_run_automation_hook", lambda _self, hook: hooks.append(hook))

    with pytest.raises(RuntimeError, match="second failed"):
        Bench.open(tmp_path / "bench.yaml")

    assert first.close_calls == 1
    assert shared.close_calls == 1
    assert hooks == []


@pytest.mark.parametrize("failure_stage", ["pre_experiment", "experiment", "database"])
def test_open_failure_cleanup_skips_post_hook_and_preserves_exception(monkeypatch, failure_stage):
    config = _config("device")
    resource = _Resource()
    hooks: list[str] = []
    monkeypatch.setattr(bench_module, "load_bench_yaml", lambda _data: config)
    monkeypatch.setattr(
        Bench,
        "_initialize_device",
        lambda self, alias, _entry, **_kwargs: self._device_instances.__setitem__(alias, resource),
    )

    def hook(_self, name):
        hooks.append(name)
        if failure_stage == "pre_experiment" and name == "pre_experiment":
            raise RuntimeError("pre_experiment failed")

    monkeypatch.setattr(Bench, "_run_automation_hook", hook)
    if failure_stage == "experiment":
        monkeypatch.setattr(
            Bench,
            "initialize_experiment",
            lambda _self: (_ for _ in ()).throw(RuntimeError("experiment failed")),
        )
    if failure_stage == "database":
        monkeypatch.setattr(
            Bench,
            "initialize_database",
            lambda _self: (_ for _ in ()).throw(RuntimeError("database failed")),
        )

    with pytest.raises(RuntimeError, match=f"{failure_stage} failed"):
        Bench.open({"ignored": True})

    assert resource.close_calls == 1
    assert hooks == ["pre_experiment"]


def test_initialize_device_closes_local_device_when_connect_raises(monkeypatch):
    config = _config("device")
    bench = Bench(config)
    resource = _Resource(fail_connect=True)
    monkeypatch.setattr(Bench, "_instantiate_device_from_preset", lambda *_a, **_k: resource)
    monkeypatch.setattr(Bench, "_resolved_device_role", lambda *_a: "fixture")

    with pytest.raises(RuntimeError, match="connect failed"):
        bench._initialize_device("device", config.devices["device"])

    assert resource.close_calls == 1
    assert bench.resources == {}


def test_close_all_is_idempotent(monkeypatch):
    config = _config("device")
    bench = Bench(config)
    resource = _Resource()
    hooks: list[str] = []
    bench._device_instances["device"] = cast(Any, resource)
    bench._opened_successfully = True
    monkeypatch.setattr(Bench, "_run_automation_hook", lambda _self, hook: hooks.append(hook))

    bench.close_all()
    bench.close_all()

    assert resource.close_calls == 1
    assert hooks == ["post_experiment"]


class _ResetBackend:
    is_simulated = False

    def __init__(self, name, events, *, fail_reset=False, fail_close=False):
        self.name = name
        self.events = events
        self.fail_reset = fail_reset
        self.fail_close = fail_close

    def connect(self):
        self.events.append(("connect", self.name))

    def write(self, command):
        assert command == "*RST"
        self.events.append(("reset", self.name))
        if self.fail_reset:
            raise OSError("reset communication failure")

    def query(self, command, delay=None):
        assert "ERR" in command.upper()
        return '+0,"No error"'

    def close(self):
        self.events.append(("close", self.name))
        if self.fail_close:
            raise OSError("close failure")


@pytest.mark.parametrize("setting", [None, False, True])
def test_reset_on_open_is_opt_in_and_precedes_hooks_for_selected_alias_only(monkeypatch, setting):
    events = []
    config = {
        "bench_name": "Opt-in reset",
        "devices": {
            "selected": {"profile": "keysight/EDU36311A", "address": "GPIB0::11::INSTR"},
            "other": {"profile": "keysight/EDU36311A", "address": "GPIB0::12::INSTR"},
        },
    }
    if setting is not None:
        config["reset_on_open"] = setting

    def build(**kwargs):
        assert kwargs["address_override"] == "GPIB0::11::INSTR"
        return _ResetBackend("selected", events)

    monkeypatch.setattr("pytestlab.devices.AutoDevice._build_backend", staticmethod(build))
    monkeypatch.setattr(Bench, "_run_automation_hook", lambda self, hook: events.append(hook))
    monkeypatch.setattr(Bench, "initialize_experiment", lambda self: events.append("experiment"))
    monkeypatch.setattr(Bench, "initialize_database", lambda self: events.append("database"))

    bench = Bench.open(config, aliases={"selected"})
    try:
        startup_resets = [("reset", "selected")] if setting else []
        assert events == [
            ("connect", "selected"),
            *startup_resets,
            "pre_experiment",
            "experiment",
            "database",
        ]
        assert set(bench.resources) == {"selected"}
        bench.reset()
        assert events[-1] == ("reset", "selected")
    finally:
        bench.close_all()
    assert events[-2:] == ["post_experiment", ("close", "selected")]


def test_explicit_bench_reset_skips_unmapped_adapter_and_noninstrument_but_calls_native_driver():
    config = _config("unmapped")
    bench = Bench(config)
    events = []
    profile = load_device_profile("keysight/EDU36311A")
    assert profile.scpi is not None and profile.scpi.commands is not None
    profile.scpi.commands.pop("reset")

    class NativePowerSupply(PowerSupply):
        def reset(self):
            events.append("native reset")

    class SupportDevice:
        def reset(self):
            pytest.fail("Bench.reset() must not call a support device")

    fallback = _ResetBackend("unexpected", events)
    unmapped = PowerSupply(profile, backend=fallback)
    native = NativePowerSupply(profile, backend=fallback)
    bench._device_instances["support"] = SupportDevice()
    bench._instrument_instances.update({"unmapped": unmapped, "native": native})

    assert not unmapped.has_profile_alias("reset")
    bench.reset()
    assert events == ["native reset"]


def test_failed_startup_reset_names_alias_closes_every_resource_and_runs_no_hooks(monkeypatch):
    events = []
    config = {
        "bench_name": "Failed reset",
        "reset_on_open": True,
        "devices": {
            "failed_psu": {"profile": "keysight/EDU36311A", "address": "GPIB0::11::INSTR"},
            "untouched": {"profile": "keysight/EDU36311A", "address": "GPIB0::12::INSTR"},
        },
    }

    def build(**kwargs):
        first = kwargs["address_override"] == "GPIB0::11::INSTR"
        return _ResetBackend(
            "failed_psu" if first else "untouched", events, fail_reset=first, fail_close=first
        )

    monkeypatch.setattr("pytestlab.devices.AutoDevice._build_backend", staticmethod(build))
    monkeypatch.setattr(Bench, "_run_automation_hook", lambda self, hook: events.append(hook))
    monkeypatch.setattr(Bench, "initialize_experiment", lambda self: events.append("experiment"))

    with pytest.raises(RuntimeError, match="failed_psu.*reset communication failure") as raised:
        Bench.open(config)

    assert raised.value.__cause__ is not None
    assert events == [
        ("connect", "failed_psu"),
        ("connect", "untouched"),
        ("reset", "failed_psu"),
        ("close", "failed_psu"),
        ("close", "untouched"),
    ]


def test_reset_alias_remains_addressable_without_shadowing_bench_method(monkeypatch):
    events = []
    config = {
        "bench_name": "Existing reset alias",
        "reset_on_open": True,
        "devices": {
            "reset": {
                "profile": "keysight/EDU36311A",
                "address": "GPIB0::11::INSTR",
                "safety_limits": {"channels": {1: {"voltage": {"max": 1}}}},
            },
            "reset_on_open": {"profile": "keysight/EDU36311A", "address": "GPIB0::12::INSTR"},
        },
    }

    def build(**kwargs):
        alias = "reset" if kwargs["address_override"] == "GPIB0::11::INSTR" else "reset_on_open"
        return _ResetBackend(alias, events)

    monkeypatch.setattr("pytestlab.devices.AutoDevice._build_backend", staticmethod(build))

    with Bench.open(config) as bench:
        assert callable(bench.reset)
        assert bench.resources["reset"] is bench.instruments["reset"]
        assert bench.instruments["reset"].safety_limits.channels[1].voltage == {"max": 1}
        assert bench.reset_on_open is bench.instruments["reset_on_open"]
        assert events == [
            ("connect", "reset"),
            ("connect", "reset_on_open"),
            ("reset", "reset"),
            ("reset", "reset_on_open"),
        ]
