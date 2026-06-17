from __future__ import annotations

from abc import ABC
from abc import abstractmethod

import numpy as np


class PhysicsModel(ABC):
    @abstractmethod
    def forward(self, vin: float | np.ndarray) -> float | np.ndarray: ...

    def dc_operating_point(self, vin: float) -> float:
        return float(self.forward(float(vin)))

    def frequency_response(self, freq_hz: np.ndarray) -> np.ndarray:
        raise NotImplementedError(f"{type(self).__name__} must override frequency_response()")


class LinearModel(PhysicsModel):
    """Single-pole H(s) = A / (1 + s/w0)."""

    def __init__(self, gain: float, pole_hz: float):
        self.gain = float(gain)
        self.pole_hz = float(pole_hz)

    def forward(self, vin):
        return self.gain * np.asarray(vin, dtype=float)

    def frequency_response(self, freq_hz):
        s = 1j * 2 * np.pi * np.asarray(freq_hz, dtype=float)
        return self.gain / (1 + s / (2 * np.pi * self.pole_hz))
