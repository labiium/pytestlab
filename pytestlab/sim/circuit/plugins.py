from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import Any
from typing import Protocol

from .models import SourceDescriptor


@dataclass
class PluginInjection:
    netlist_lines: list[str] = field(default_factory=list)
    sources: list[SourceDescriptor] = field(default_factory=list)
    element_currents: dict[str, str] = field(default_factory=dict)


class InstrumentPlugin(Protocol):
    kind: str

    def list_terminals(self, inst_id: str, config: Any) -> list[str]: ...

    def create_twin(self, seed: int, config: Any, limits: Any): ...

    def inject(
        self,
        session,
        inst_id: str,
        config: Any,
    ) -> PluginInjection: ...


_PLUGIN_REGISTRY: dict[str, InstrumentPlugin] = {}


def register_plugin(plugin: InstrumentPlugin) -> None:
    _PLUGIN_REGISTRY[plugin.kind.upper()] = plugin


def get_plugin(kind: str) -> InstrumentPlugin | None:
    return _PLUGIN_REGISTRY.get(kind.upper())
