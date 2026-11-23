from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pytestlab.devices import providers
from pytestlab.devices.factory import AutoDevice


@pytest.mark.parametrize(
    "backend_spec,hint,simulate,address,expected",
    [
        (
            {"import_path": "factory:build", "type": "custom_backend"},
            "visa",
            True,
            "GPIB0::1::INSTR",
            "custom_backend",
        ),
        ({"import_path": "factory:build"}, None, False, None, "custom"),
        ({"type": "circuit_sim"}, "visa", True, None, "visa"),
        ({"type": "circuit_sim"}, None, False, None, "circuit_sim"),
        (None, None, True, "GPIB0::1::INSTR", "sim"),
        (None, None, False, "LAMB::GPIB0::1::INSTR", "lamb"),
        (None, None, False, "GPIB0::1::INSTR", "visa"),
        (None, None, False, None, "lamb"),
    ],
)
def test_backend_type_selection_matches_factory_precedence(
    backend_spec: dict[str, Any] | None,
    hint: str | None,
    simulate: bool,
    address: str | None,
    expected: str,
) -> None:
    assert (
        AutoDevice._select_backend_type(
            backend_spec=backend_spec,
            backend_type_hint=hint,
            simulate=simulate,
            address=address,
        )
        == expected
    )


class RecordingProvider:
    def __init__(self, name: str, events: list[tuple[str, str]]) -> None:
        self.name = name
        self.events = events

    def is_configured(self, config: Any) -> bool:
        self.events.append((self.name, "configured"))
        return True

    def prepare(self, config: Any, *, base_path: Path | None) -> str:
        self.events.append((self.name, "prepare"))
        return self.name

    def cleanup(self, resource: str) -> None:
        self.events.append((self.name, "cleanup"))


def test_scoped_provider_preparation_skips_unselected_providers(monkeypatch) -> None:
    events: list[tuple[str, str]] = []
    providers_by_name = {
        name: RecordingProvider(name, events) for name in ("selected", "unrelated")
    }
    get_calls: list[str] = []

    def get_provider(name: str):
        get_calls.append(name)
        return providers_by_name[name]

    monkeypatch.setattr(providers, "_provider_specs", {})
    monkeypatch.setattr(providers, "_providers", providers_by_name)
    monkeypatch.setattr(providers, "get_backend_provider", get_provider)

    scope = providers.prepare_backend_resources(
        object(), base_path=None, backend_types={"selected"}
    )
    assert dict(scope.resources) == {"selected": "selected"}
    assert get_calls == ["selected"]
    assert events == [("selected", "configured"), ("selected", "prepare")]

    scope.close()
    assert events[-1] == ("selected", "cleanup")
    assert all(name == "selected" for name, _ in events)


def test_provider_preparation_defaults_to_all_configured_providers(monkeypatch) -> None:
    events: list[tuple[str, str]] = []
    providers_by_name = {name: RecordingProvider(name, events) for name in ("first", "second")}
    monkeypatch.setattr(providers, "_provider_specs", {})
    monkeypatch.setattr(providers, "_providers", providers_by_name)
    monkeypatch.setattr(providers, "get_backend_provider", providers_by_name.__getitem__)

    scope = providers.prepare_backend_resources(object(), base_path=None)
    assert set(scope.resources) == set(providers_by_name)
    scope.close()
    assert events == [
        ("first", "configured"),
        ("first", "prepare"),
        ("second", "configured"),
        ("second", "prepare"),
        ("second", "cleanup"),
        ("first", "cleanup"),
    ]
