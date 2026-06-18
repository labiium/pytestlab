"""Compatibility math namespace mirroring :mod:`pytestlab.uncertainty.umath`."""

from __future__ import annotations

from ..umath import absolute
from ..umath import atan2
from ..umath import cos
from ..umath import exp
from ..umath import log
from ..umath import log10
from ..umath import power
from ..umath import sin
from ..umath import sqrt
from ..umath import tan

__all__ = [
    "sqrt",
    "log",
    "log10",
    "exp",
    "sin",
    "cos",
    "tan",
    "atan2",
    "power",
    "absolute",
]
