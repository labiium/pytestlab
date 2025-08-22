"""
pytestlab.measurements
======================

Notebook-friendly *builder* for complex measurement sweeps.  See the extensive
documentation in :pymod:`pytestlab.measurements.session`.
"""

from typing import TYPE_CHECKING

__all__ = ["Measurement", "MeasurementSession"]

if TYPE_CHECKING:
    # For static type checkers only; avoids runtime import and circular dependency
    from .session import Measurement  # noqa: F401
    from .session import MeasurementSession  # noqa: F401


def __getattr__(name: str):
    if name in __all__:
        from . import session as _session

        return getattr(_session, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
