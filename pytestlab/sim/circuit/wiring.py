from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import get_close_matches
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import field_validator
from pydantic import model_validator

from .bench import BenchConfig
from .netlist import extract_nodes


class UnknownNode(ValueError):
    """Raised when a wiring/port target node is not defined by the netlist.

    Subclasses :class:`ValueError` so existing callers that catch wiring
    ``ValueError``\\ s continue to work, while exposing structured fields for
    programmatic handling.
    """

    reason = "UNKNOWN_NODE"

    def __init__(
        self,
        node: str,
        *,
        available: set[str] | None = None,
        terminal: str | None = None,
    ) -> None:
        self.node = node
        self.available = sorted(available) if available else []
        self.terminal = terminal
        self.suggestion = self._closest(node, self.available)
        message = f"unknown node {node!r}"
        if terminal is not None:
            message += f" wired to terminal {terminal}"
        if self.suggestion:
            message += f" — did you mean {self.suggestion!r}?"
        elif self.available:
            message += f". Available nodes: {', '.join(self.available)}"
        super().__init__(message)

    @staticmethod
    def _closest(node: str, available: list[str]) -> str | None:
        matches = get_close_matches(str(node).lower(), [a.lower() for a in available], n=1, cutoff=0.5)
        if not matches:
            return None
        # Map the lowercased match back to the original spelling.
        lowered = matches[0]
        for candidate in available:
            if candidate.lower() == lowered:
                return candidate
        return lowered


@dataclass(frozen=True)
class NodeRef:
    """Typed reference to a SPICE node.

    ``NodeRef`` is intentionally a tiny value object.  It keeps user-facing
    wiring code autocomplete-friendly while preserving the existing string
    serialization boundary used by ``WiringConfig`` and YAML.
    """

    name: str

    def __post_init__(self) -> None:
        if not str(self.name).strip():
            raise ValueError("node name must be non-empty")

    @classmethod
    def ground(cls) -> NodeRef:
        return cls("0")

    def __str__(self) -> str:
        return self.name


class Netlist:
    """A SPICE netlist with a validated node namespace.

    ``Netlist`` is the recommended way to obtain :class:`NodeRef`\\ s: it knows
    the real nodes of a circuit, so referencing one validates it *at the line
    you write it* rather than at simulation time. A typo therefore fails
    immediately and points at a likely fix, instead of silently floating.

    >>> net = Netlist.from_file("amp.sp")
    >>> net.vout            # attribute access -> validated NodeRef
    >>> net.node("vout")    # explicit, raises UnknownNode on a typo
    """

    def __init__(self, text: str, *, source: Path | None = None) -> None:
        self.text = text
        self.source = source
        base_dir = source.parent if source is not None else None
        self.nodes: set[str] = extract_nodes(text, base_dir=base_dir)
        self._by_lower = {n.lower(): n for n in self.nodes}

    @classmethod
    def from_file(cls, path: str | Path) -> Netlist:
        resolved = Path(path)
        return cls(resolved.read_text(), source=resolved)

    def node(self, name: str | NodeRef) -> NodeRef:
        """Return a validated :class:`NodeRef`, or raise :class:`UnknownNode`."""
        canonical = str(name).strip()
        low = canonical.lower()
        if low in {"0", "gnd"}:
            return NodeRef.ground()
        original = self._by_lower.get(low)
        if original is None:
            raise UnknownNode(canonical, available=self.nodes)
        return NodeRef(original)

    def ground(self) -> NodeRef:
        return NodeRef.ground()

    def __contains__(self, name: object) -> bool:
        return str(name).strip().lower() in self._by_lower

    def __getattr__(self, name: str) -> NodeRef:
        # Only invoked for names not found as real attributes. Reserve dunder /
        # private names so __init__ and copy/pickle probes behave normally.
        if name.startswith("_"):
            raise AttributeError(name)
        try:
            return self.node(name)
        except UnknownNode as exc:
            raise AttributeError(str(exc)) from exc

    def __repr__(self) -> str:
        where = f" source={self.source}" if self.source else ""
        return f"Netlist(nodes={sorted(self.nodes)}{where})"


@dataclass(frozen=True)
class TerminalRef:
    """Typed reference to an instrument terminal."""

    instrument_id: str
    path: tuple[str, ...]

    def __post_init__(self) -> None:
        if not str(self.instrument_id).strip():
            raise ValueError("instrument id must be non-empty")

    def child(self, *parts: str) -> TerminalRef:
        return TerminalRef(self.instrument_id, self.path + tuple(_terminal_part(p) for p in parts))

    def __str__(self) -> str:
        if not self.path:
            return self.instrument_id
        return ".".join((self.instrument_id, *self.path))


def _terminal_part(value: str) -> str:
    part = str(value).strip()
    if not part:
        raise ValueError("terminal path parts must be non-empty")
    return part


def _channel_name(channel: int | str) -> str:
    if isinstance(channel, str):
        text = channel.strip().upper()
        if text.startswith("CH"):
            return text
        channel = int(text)
    return f"CH{int(channel)}"


@dataclass(frozen=True)
class TerminalPairRef:
    prefix: TerminalRef

    @property
    def hi(self) -> TerminalRef:
        return self.prefix.child("HI")

    @property
    def lo(self) -> TerminalRef:
        return self.prefix.child("LO")

    @property
    def plus(self) -> TerminalRef:
        return self.hi

    @property
    def minus(self) -> TerminalRef:
        return self.lo


@dataclass(frozen=True)
class PsuRef:
    instrument_id: str

    def ch(self, channel: int | str = 1) -> TerminalPairRef:
        return TerminalPairRef(TerminalRef(self.instrument_id, (_channel_name(channel),)))


@dataclass(frozen=True)
class AwgRef:
    instrument_id: str

    @property
    def out(self) -> TerminalPairRef:
        return TerminalPairRef(TerminalRef(self.instrument_id, ()))


@dataclass(frozen=True)
class ScopeRef:
    instrument_id: str

    def ch(self, channel: int | str = 1) -> TerminalPairRef:
        return TerminalPairRef(TerminalRef(self.instrument_id, (_channel_name(channel),)))


@dataclass(frozen=True)
class DmmRef:
    instrument_id: str

    @property
    def voltage(self) -> TerminalPairRef:
        return TerminalPairRef(TerminalRef(self.instrument_id, ("V",)))

    @property
    def current(self) -> TerminalPairRef:
        return TerminalPairRef(TerminalRef(self.instrument_id, ("I",)))


class InstrumentRefs:
    """Factory namespace for typed instrument references."""

    def psu(self, instrument_id: str) -> PsuRef:
        return PsuRef(instrument_id)

    def awg(self, instrument_id: str) -> AwgRef:
        return AwgRef(instrument_id)

    def scope(self, instrument_id: str) -> ScopeRef:
        return ScopeRef(instrument_id)

    def dmm(self, instrument_id: str) -> DmmRef:
        return DmmRef(instrument_id)


instrument_refs = InstrumentRefs()


class Connection(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    from_: str = Field(alias="from")
    to: str

    if TYPE_CHECKING:
        def __init__(self, *, from_: TerminalRef | str, to: NodeRef | str) -> None: ...

    @field_validator("from_", "to", mode="before")
    @classmethod
    def stringify_refs(cls, value):
        if isinstance(value, NodeRef | TerminalRef):
            return str(value)
        return value


class ProbeModel(BaseModel):
    attenuation: float | None = None
    rin_ohm: float | None = None
    cin_f: float | None = None
    lin_h: float | None = None


class WiringRules(BaseModel):
    forbid_multiple_ground_nodes: bool = True
    allow_floating_instruments: bool = True
    allow_output_sharing: bool = False


class WiringConfig(BaseModel):
    format_version: str = "1.0"
    ground_node: str = "0"
    connections: list[Connection]
    probe_models: dict[str, ProbeModel] = Field(default_factory=dict)
    rules: WiringRules = WiringRules()

    @model_validator(mode="after")
    def ensure_ground(self) -> WiringConfig:
        grounds = [c.to for c in self.connections if c.to == self.ground_node]
        if not grounds:
            raise ValueError("at least one ground reference required")
        return self

    def probe_model_for(self, terminal: str) -> ProbeModel | None:
        """Return the probe model that applies to a concrete terminal.

        Probe models may be keyed either by the full terminal (e.g.
        ``scope1.CH1.HI``) or by the channel/function prefix (e.g.
        ``scope1.CH1`` or ``dmm1.V``).
        """

        direct = self.probe_models.get(terminal)
        if direct is not None:
            return direct

        base, _, suffix = terminal.rpartition(".")
        if suffix in {"HI", "LO"} and base:
            return self.probe_models.get(base)
        return None


class WiringBuilder:
    """Fluent builder that converts typed references into ``WiringConfig``."""

    def __init__(
        self,
        *,
        ground: NodeRef | str = "0",
        rules: WiringRules | None = None,
        probe_models: dict[str | TerminalRef, ProbeModel] | None = None,
    ):
        self.ground = _node_name(ground)
        self.rules = rules or WiringRules()
        self._connections: list[Connection] = []
        self._probe_models: dict[str, ProbeModel] = {}
        if probe_models:
            for terminal, model in probe_models.items():
                self.probe_model(terminal, model)

    def connect(self, terminal: TerminalRef | str, node: NodeRef | str) -> WiringBuilder:
        self._connections.append(Connection(from_=_terminal_name(terminal), to=_node_name(node)))
        return self

    def probe_model(
        self, terminal: TerminalRef | str, model: ProbeModel | dict[str, float | None]
    ) -> WiringBuilder:
        probe = model if isinstance(model, ProbeModel) else ProbeModel(**model)
        self._probe_models[_terminal_name(terminal)] = probe
        return self

    def to_config(self) -> WiringConfig:
        return WiringConfig(
            ground_node=self.ground,
            connections=list(self._connections),
            probe_models=dict(self._probe_models),
            rules=self.rules,
        )


def _terminal_name(value: TerminalRef | str) -> str:
    if isinstance(value, TerminalRef):
        return str(value)
    return str(value)


def _node_name(value: NodeRef | str) -> str:
    if isinstance(value, NodeRef):
        return str(value)
    return str(value)


class WiringCompiler:
    def __init__(
        self,
        bench: BenchConfig,
        wiring: WiringConfig,
        nodes: set[str] | None = None,
    ):
        self.bench = bench
        self.wiring = wiring
        self.terminals: set[str] = set()
        for inst_id in self.bench.instruments:
            self.terminals.update(self.bench.list_terminals(inst_id))
        # Authoritative set of node names defined by the netlist. ``None`` means
        # the node set is unavailable, in which case node validation is skipped
        # to preserve behaviour for callers that do not supply a netlist.
        self.nodes = nodes
        self._nodes_lower = (
            {self._canonical_node(n) for n in nodes} if nodes is not None else None
        )

    @staticmethod
    def _canonical_node(name: str) -> str:
        # ngspice node names are case-insensitive.
        return str(name).strip().lower()

    def _is_known_node(self, node: str) -> bool:
        if self._nodes_lower is None:
            return True
        canonical = self._canonical_node(node)
        if canonical in {"0", self._canonical_node(self.wiring.ground_node)}:
            return True
        return canonical in self._nodes_lower

    def compile(self) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for connection in self.wiring.connections:
            self._validate_connection(connection)
            existing = mapping.get(connection.from_)
            if existing is not None and existing != connection.to:
                raise ValueError(f"terminal {connection.from_} connected to multiple nodes")
            mapping[connection.from_] = connection.to
        self._validate_ground_policy()
        self._validate_floating_instruments(mapping)
        self._detect_conflicts()
        return mapping

    def _validate_connection(self, connection: Connection) -> None:
        if connection.from_ not in self.terminals:
            suggestion = self._terminal_suggestion(connection.from_)
            raise ValueError(f"unknown terminal {connection.from_}{suggestion}")
        if not self._is_known_node(connection.to):
            raise UnknownNode(
                connection.to,
                available=self.nodes or set(),
                terminal=connection.from_,
            )

    def _validate_ground_policy(self) -> None:
        if not self.wiring.rules.forbid_multiple_ground_nodes:
            return
        lo_targets = {
            conn.to
            for conn in self.wiring.connections
            if _is_ground_reference_terminal(conn.from_)
        }
        if len(lo_targets) > 1:
            raise ValueError("multiple grounds detected while forbidden")

    def _validate_floating_instruments(self, mapping: dict[str, str]) -> None:
        if self.wiring.rules.allow_floating_instruments:
            return
        connected_instruments = {terminal.split(".", 1)[0] for terminal in mapping}
        missing = [
            inst_id for inst_id in self.bench.instruments if inst_id not in connected_instruments
        ]
        if missing:
            raise ValueError(
                f"floating instruments detected while forbidden: {', '.join(sorted(missing))}"
            )

    def _detect_conflicts(self) -> None:
        outputs: dict[str, str] = {}
        for conn in self.wiring.connections:
            inst_id = conn.from_.split(".", 1)[0]
            instrument = self.bench.instruments[inst_id]
            if instrument.kind == "AWG" and not conn.from_.upper().endswith(".HI"):
                continue
            if instrument.kind == "PSU" and not conn.from_.upper().endswith(".HI"):
                continue
            if instrument.kind not in {"PSU", "AWG"}:
                continue

            if conn.to in outputs and outputs[conn.to] != conn.from_:
                if self.wiring.rules.allow_output_sharing:
                    continue
                raise ValueError(f"output short detected on node {conn.to}")
            outputs[conn.to] = conn.from_

    def inject_probe_loading(self) -> list[str]:
        injected = []
        for key, probe in self.wiring.probe_models.items():
            terminal = self._resolve_probe_terminal(key)
            if terminal is None:
                raise ValueError(f"unknown probe terminal {key}")
            node_hi = terminal
            node_lo = self.wiring.ground_node
            base, _, suffix = terminal.rpartition(".")
            if suffix in {"HI", "LO"} and base:
                other = f"{base}.{'LO' if suffix == 'HI' else 'HI'}"
                if other in self.terminals:
                    node_lo = other
            elements = []
            probe_node = node_hi
            if probe.lin_h:
                safe_key = re.sub(r"[^A-Za-z0-9_]", "_", key)
                probe_node = f"n_probe_{safe_key}"
                elements.append(f"L_{key} {node_hi} {probe_node} {probe.lin_h}")
            if probe.rin_ohm:
                elements.append(f"R_{key} {probe_node} {node_lo} {probe.rin_ohm}")
            if probe.cin_f:
                elements.append(f"C_{key} {probe_node} {node_lo} {probe.cin_f}")
            injected.extend(elements)
        return injected

    def _resolve_probe_terminal(self, key: str) -> str | None:
        if key in self.terminals:
            return key
        for suffix in (".HI", ".LO"):
            candidate = f"{key}{suffix}"
            if candidate in self.terminals:
                return candidate
        return None

    def _terminal_suggestion(self, terminal: str) -> str:
        candidates = sorted(self.terminals)
        hints = _terminal_alias_hints(terminal, candidates)
        if not hints:
            hints = get_close_matches(terminal, candidates, n=3, cutoff=0.45)
        if not hints:
            return f". Available terminals: {', '.join(candidates)}"
        return f". Did you mean {', '.join(hints)}?"


def _terminal_alias_hints(terminal: str, candidates: list[str]) -> list[str]:
    hints: list[str] = []
    if terminal.endswith("+"):
        hints.append(f"{terminal[:-1]}.HI")
    elif terminal.endswith("-"):
        hints.append(f"{terminal[:-1]}.LO")
    elif terminal.upper().endswith(".PLUS"):
        hints.append(f"{terminal[:-5]}.HI")
    elif terminal.upper().endswith(".MINUS"):
        hints.append(f"{terminal[:-6]}.LO")
    return [hint for hint in hints if hint in candidates]


def _is_ground_reference_terminal(terminal: str) -> bool:
    upper = terminal.upper()
    if not upper.endswith(".LO"):
        return False
    # DMM current LO is a series measurement terminal. Treating it as a
    # required ground reference rejects realistic burden-resistor insertion
    # between two non-ground circuit nodes.
    return not upper.endswith(".I.LO")
