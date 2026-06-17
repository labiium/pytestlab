from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import Protocol

from ..models import SourceDescriptor


@dataclass
class InjectionResult:
    netlist_lines: list[str] = field(default_factory=list)
    sources: list[SourceDescriptor] = field(default_factory=list)
    element_currents: dict[str, str] = field(default_factory=dict)

    def extend(self, other: InjectionResult) -> None:
        self.netlist_lines.extend(other.netlist_lines)
        self.sources.extend(other.sources)
        self.element_currents.update(other.element_currents)


class Injector(Protocol):
    def inject(self, session) -> InjectionResult: ...
