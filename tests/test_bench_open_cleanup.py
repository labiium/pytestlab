from __future__ import annotations

from typing import Any
from typing import cast

import pytest

import pytestlab.bench as bench_module
from pytestlab.bench import Bench
from pytestlab.config.bench_config import BenchConfigExtended
from pytestlab.devices.providers import BackendResourceScope


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

    def initialize(self, alias, _entry, *, must_be_instrument=False):
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
