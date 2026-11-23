from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from pytestlab.devices import providers as provider_registry
from pytestlab.devices.providers import get_backend_provider
from pytestlab.devices.providers import prepare_backend_resources
from pytestlab.devices.providers import register_backend_provider


@dataclass
class _Config:
    enabled: set[str]
    sim_circuit: Any = None


class _Provider:
    def __init__(self, name: str, events: list[str], *, fail: bool = False) -> None:
        self.name = name
        self.events = events
        self.fail = fail

    def is_configured(self, config: _Config) -> bool:
        return self.name in getattr(config, "enabled", set())

    def prepare(self, config: _Config, *, base_path: Path | None) -> str:
        self.events.append(f"prepare:{self.name}:{base_path}")
        if self.fail:
            raise RuntimeError(f"failed:{self.name}")
        return f"resource:{self.name}"

    def cleanup(self, resource: str) -> None:
        self.events.append(f"cleanup:{resource}")


@pytest.fixture(autouse=True)
def _restore_provider_registry():
    providers = dict(provider_registry._providers)
    specs = dict(provider_registry._provider_specs)
    yield
    provider_registry._providers.clear()
    provider_registry._providers.update(providers)
    provider_registry._provider_specs.clear()
    provider_registry._provider_specs.update(specs)


def test_provider_scope_prepares_context_and_cleans_up_in_reverse(tmp_path: Path) -> None:
    events: list[str] = []
    register_backend_provider("test_first", _Provider("first", events), replace=True)
    register_backend_provider("test_second", _Provider("second", events), replace=True)

    scope = prepare_backend_resources(_Config({"first", "second"}), base_path=tmp_path)

    assert scope.get("test_first") == "resource:first"
    assert scope.resources["test_second"] == "resource:second"
    scope.close()
    scope.close()
    assert events == [
        f"prepare:first:{tmp_path}",
        f"prepare:second:{tmp_path}",
        "cleanup:resource:second",
        "cleanup:resource:first",
    ]


def test_provider_scope_rolls_back_prepared_resources_on_failure(tmp_path: Path) -> None:
    events: list[str] = []
    register_backend_provider("test_rollback_a", _Provider("rollback_a", events), replace=True)
    register_backend_provider(
        "test_rollback_b", _Provider("rollback_b", events, fail=True), replace=True
    )

    with pytest.raises(RuntimeError, match="failed:rollback_b"):
        prepare_backend_resources(_Config({"rollback_a", "rollback_b"}), base_path=tmp_path)

    assert events[-1] == "cleanup:resource:rollback_a"


def test_builtin_circuit_provider_is_available_lazily() -> None:
    provider = get_backend_provider("circuit_sim")

    assert provider is not None
    assert provider.is_configured(_Config(set(), sim_circuit=object()))
