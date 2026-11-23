from __future__ import annotations

import random
from dataclasses import dataclass
from dataclasses import field
from typing import Any


@dataclass
class MeasurementResult:
    """Nominal simulated instrument reading with units and metadata."""

    values: Any
    units: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class InstrumentState:
    """Mutable state payload shared by simulated instrument twins."""

    enabled: bool = False


class InstrumentTwin:
    """Base state container and deterministic measurement helper for instrument twins."""

    def __init__(self, seed: int):
        self.seed = seed
        self.random = random.Random(seed)
        self.state = InstrumentState()
        self.last_warnings: list[str] = []

    def describe(self) -> dict[str, Any]:
        raise NotImplementedError

    def get_state(self) -> InstrumentState:
        return self.state

    def set_state(self, **kwargs: Any) -> None:
        for key, value in kwargs.items():
            if hasattr(self.state, key):
                setattr(self.state, key, value)
            else:
                raise ValueError(f"unknown state field {key}")

    def _clear_warnings(self) -> None:
        self.last_warnings.clear()

    def _warn(self, message: str) -> None:
        self.last_warnings.append(message)

    def self_test(self) -> dict[str, Any]:
        return {"status": "ok", "seed": self.seed}

    def _apply_noise(self, value: float, noise_rms: float) -> float:
        return value + self.random.normalvariate(0, noise_rms)
