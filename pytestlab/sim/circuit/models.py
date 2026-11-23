from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class SourceDescriptor:
    kind: Literal["awg", "psu"]
    key: str
    vsrc_name: str
    hi_node: str
    lo_node: str
