from __future__ import annotations

import re

_SOURCE_FUNC_RE = re.compile(r"\b(SIN|PULSE)\(", re.IGNORECASE)


def space_source_functions(source_expr: str) -> str:
    """Render EEspice-compatible spacing for simulator-owned source functions."""

    return _SOURCE_FUNC_RE.sub(lambda match: f"{match.group(1).upper()} (", source_expr)
