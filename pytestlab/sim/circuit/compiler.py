from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import SourceDescriptor
from .spice import _build_augmented_netlist


@dataclass(frozen=True)
class CompiledNetlist:
    lines: list[str]
    text: str
    sources: tuple[SourceDescriptor, ...]
    element_currents: dict[str, str]
    metadata: dict[str, Any]


class BenchCompiler:
    """Compile circuit + bench + wiring + variations into an augmented netlist."""

    def __init__(self, session) -> None:
        self.session = session

    def compile(self) -> CompiledNetlist:
        lines, sources, element_currents, metadata = _build_augmented_netlist(self.session)
        text = "\n".join(lines)
        return CompiledNetlist(
            lines=lines,
            text=text,
            sources=sources,
            element_currents=element_currents,
            metadata=metadata,
        )
