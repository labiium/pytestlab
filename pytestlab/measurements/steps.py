"""
Utility helpers that describe non-linear parameter sweeps for MeasurementSession.
"""

from __future__ import annotations

from collections.abc import Callable
from collections.abc import Iterable
from collections.abc import Mapping
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

T_Value = float | int | complex | str | np.ndarray | Sequence[Any]
T_Generator = Callable[[], Iterable[T_Value]]


@dataclass(frozen=True, slots=True)
class StepSpec:
    """
    Declarative description of a parameter sweep.

    A ``StepSpec`` stores a lightweight callable that returns an iterable of
    values (floats, ints, complex numbers, numpy arrays, etc.).  The spec is
    resolved when ``MeasurementSession.parameter`` materializes it into the
    internal parameter grid.
    """

    generator: T_Generator
    label: str = "custom"
    metadata: Mapping[str, Any] | None = None

    def values(self) -> list[T_Value]:
        """Return the generated values as a list."""
        return list(self.generator())


class _StepFactory:
    """Namespace that exposes ergonomic constructors for ``StepSpec`` objects."""

    @staticmethod
    def _ensure_positive_count(count: int) -> None:
        if count <= 0:
            raise ValueError("count must be a positive integer.")

    def linear(
        self,
        start: float | complex,
        stop: float | complex,
        count: int,
        *,
        endpoint: bool = True,
    ) -> StepSpec:
        """
        Evenly spaced values between ``start`` and ``stop`` using ``numpy.linspace``.
        """
        self._ensure_positive_count(count)

        def _factory():
            return np.linspace(start, stop, count, endpoint=endpoint)

        meta: dict[str, Any] = {
            "start": start,
            "stop": stop,
            "count": count,
            "endpoint": endpoint,
        }
        return StepSpec(_factory, label="linear", metadata=meta)

    def log(
        self,
        start: float,
        stop: float,
        count: int,
        *,
        base: float = 10.0,
    ) -> StepSpec:
        """Logarithmically spaced values between ``start`` and ``stop``."""
        self._ensure_positive_count(count)
        if start <= 0 or stop <= 0:
            raise ValueError("log spacing requires positive start/stop values.")

        def _factory():
            start_exp = np.log(start) / np.log(base)
            stop_exp = np.log(stop) / np.log(base)
            return np.logspace(start_exp, stop_exp, count, base=base)

        meta = {"start": start, "stop": stop, "count": count, "base": base}
        return StepSpec(_factory, label="log", metadata=meta)

    def geom(
        self,
        start: float | complex,
        stop: float | complex,
        count: int,
    ) -> StepSpec:
        """Geometrically spaced values (multiplicative steps)."""
        self._ensure_positive_count(count)

        def _factory():
            return np.geomspace(start, stop, count)

        meta = {"start": start, "stop": stop, "count": count}
        return StepSpec(_factory, label="geom", metadata=meta)

    def exp(
        self,
        exponent_start: float | complex,
        exponent_stop: float | complex,
        count: int,
    ) -> StepSpec:
        """
        Exponential curve defined by exponentiating a linear sweep.

        ``exponent_start``/``exponent_stop`` are fed to ``numpy.exp`` after a
        ``numpy.linspace`` step, which allows imaginary or real exponents.
        """
        self._ensure_positive_count(count)

        def _factory():
            lin = np.linspace(exponent_start, exponent_stop, count)
            return np.exp(lin)

        meta = {
            "exponent_start": exponent_start,
            "exponent_stop": exponent_stop,
            "count": count,
        }
        return StepSpec(_factory, label="exp", metadata=meta)

    def points(self, values: Iterable[T_Value]) -> StepSpec:
        """Wrap a user-provided iterable so it can be reused."""
        snapshot = tuple(values)
        if not snapshot:
            raise ValueError("points() requires at least one value.")

        def _factory():
            return snapshot

        meta = {"count": len(snapshot)}
        return StepSpec(_factory, label="points", metadata=meta)

    def custom(self, generator: T_Generator, *, label: str = "custom") -> StepSpec:
        """
        Build a spec from an arbitrary callable returning an iterable.
        """
        if not callable(generator):
            raise TypeError("custom() expects a callable generator.")

        def _factory():
            return generator()

        return StepSpec(_factory, label=label)


step = _StepFactory()

__all__ = ["StepSpec", "step"]
