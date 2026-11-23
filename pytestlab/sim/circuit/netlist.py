from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class IncludeExpansionResult:
    text: str
    include_files: list[str]


def expand_includes(
    text: str,
    *,
    root: Path,
    allowed_includes: set[str],
    max_depth: int,
    max_files: int,
    max_file_bytes: int,
) -> IncludeExpansionResult:
    include_files: list[str] = []

    def _expand(src_text: str, depth: int) -> list[str]:
        if depth > max_depth:
            raise ValueError("include depth exceeds manifest constraint")
        expanded: list[str] = []
        for raw in src_text.splitlines():
            include_match = re.match(r"^\s*\.(?:inc|include)\s+(.+)$", raw, flags=re.IGNORECASE)
            if include_match:
                token = include_match.group(1).strip().strip('"').strip("'")
                if token not in allowed_includes:
                    raise ValueError(
                        f"Netlist includes {token!r} but it is not listed in manifest.allowed_includes"
                    )
                inc_path = (root / token).resolve()
                if not inc_path.is_relative_to(root.resolve()):
                    raise ValueError("include path escapes package root")
                if inc_path.stat().st_size > max_file_bytes:
                    raise ValueError("included file exceeds max_file_bytes constraint")
                include_files.append(token)
                if len(include_files) > max_files:
                    raise ValueError("include file count exceeds manifest constraint")
                inc_text = inc_path.read_text()
                expanded.extend(_expand(inc_text, depth + 1))
                continue
            expanded.append(raw)
        return expanded

    lines = _expand(text, 0)
    return IncludeExpansionResult(text="\n".join(lines), include_files=include_files)


# Device-type rules for locating node columns on an element line. SPICE lists a
# device's connection nodes as the columns immediately after the instance name,
# but how many columns are nodes depends on the device letter.
#
#   FIXED2  - exactly the first two columns are nodes (the main terminals);
#             anything after is a model name, value, or source spec.
#   TRAILER - every column between the name and the trailing model/subcircuit
#             name is a node (handles transistors with 3-4 terminals, MOSFETs
#             with 4, and ``X`` subcircuit instances with arbitrary pin counts).
#
# ``K`` (mutual inductance) references inductors by name and has no nodes.
_FIXED2_DEVICES = set("RCLDVIBFHSW")
_TRAILER_DEVICES = set("QMJZXE G".replace(" ", ""))
_NO_NODE_DEVICES = set("K")

_INCLUDE_RE = re.compile(r"^\s*\.(?:inc|include)\s+(.+)$", flags=re.IGNORECASE)
_MAX_INCLUDE_DEPTH = 16


def _strip_inline_comment(line: str) -> str:
    """Remove a trailing ngspice inline comment (``;`` anywhere, or `` $``).

    Without this, comment words on a transistor/subcircuit line leak into the
    node set (e.g. ``Q1 c b e QMOD ; note`` would otherwise yield ``note``).
    """
    semi = line.find(";")
    if semi != -1:
        line = line[:semi]
    dollar = re.search(r"\s\$", line)
    if dollar:
        line = line[: dollar.start()]
    return line


def _logical_lines(netlist_text: str) -> list[str]:
    """Yield netlist lines with inline comments removed and ``+`` continuations
    folded into their parent. Comments are stripped per physical line *before*
    folding so a comment never swallows a continued node column."""
    logical: list[str] = []
    for raw in netlist_text.splitlines():
        stripped = _strip_inline_comment(raw).strip()
        if stripped.startswith("+"):
            if logical:
                logical[-1] = f"{logical[-1]} {stripped[1:].strip()}"
            continue
        logical.append(stripped)
    return logical


def _node_columns(device: str, parts: list[str]) -> list[str]:
    """Return the node tokens for a single element line.

    ``parts`` is the whitespace-split line (``parts[0]`` is the instance name).
    """
    if device in _NO_NODE_DEVICES:
        return []
    if device in _TRAILER_DEVICES:
        # Nodes are every non-parameter column except the trailing model or
        # subcircuit name, e.g. ``Q1 vcc b1 drive QNPN`` -> [vcc, b1, drive].
        core = [tok for tok in parts[1:] if "=" not in tok]
        return core[:-1] if len(core) > 1 else core
    # FIXED2 and any unrecognised device: the first two columns are the nodes.
    return parts[1:3]


def _include_target(line: str, base_dir: Path | None) -> Path | None:
    match = _INCLUDE_RE.match(line)
    if match is None or base_dir is None:
        return None
    token = match.group(1).strip().strip('"').strip("'")
    candidate = (base_dir / token).resolve()
    return candidate if candidate.is_file() else None


def extract_nodes(
    netlist_text: str,
    *,
    base_dir: Path | None = None,
    _depth: int = 0,
) -> set[str]:
    """Extract the set of top-level node names defined by a SPICE netlist.

    This is the authoritative node set used to validate wiring/port node names
    before simulation. It is device-type aware (so transistor, MOSFET, and
    subcircuit terminals are all captured) and skips ``.subckt`` bodies, whose
    internal nodes are not reachable as wiring targets.

    When ``base_dir`` is given, ``.include``/``.inc`` files are resolved
    relative to it and their nodes merged in — matching what ngspice sees at
    simulation time. Resolution is permissive and depth-limited; missing or
    unresolvable includes are skipped rather than raised, since this is a
    read-only analysis used only to improve validation and error messages.
    """
    nodes: set[str] = {"0"}
    subckt_depth = 0
    for line in _logical_lines(netlist_text):
        if not line or line.startswith("*"):
            continue
        low = line.lower()
        if low.startswith((".include", ".inc")):
            target = _include_target(line, base_dir)
            if target is not None and _depth < _MAX_INCLUDE_DEPTH:
                nodes |= extract_nodes(
                    target.read_text(errors="replace"),
                    base_dir=target.parent,
                    _depth=_depth + 1,
                )
            continue
        if low.startswith(".subckt"):
            subckt_depth += 1
            continue
        if low.startswith(".ends"):
            if subckt_depth > 0:
                subckt_depth -= 1
            continue
        if low.startswith("."):
            continue
        if subckt_depth > 0:
            continue
        parts = line.split()
        if not parts:
            continue
        device = parts[0][0].upper()
        nodes.update(_node_columns(device, parts))
    return nodes
