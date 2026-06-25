"""Optional waveform noise-model helpers.

The core waveform path stays conservative and diagonal when no correlation data
are supplied.  These helpers let users quantify ENOB and autocorrelation effects
without manipulating covariance atoms directly.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike


@dataclass(frozen=True)
class ENOBNoiseModel:
    """Effective-number-of-bits noise model for oscilloscope waveforms."""

    enob: float
    full_scale_v: float

    @property
    def step_v(self) -> float:
        if self.enob <= 0.0:
            raise ValueError("enob must be positive")
        if self.full_scale_v <= 0.0:
            raise ValueError("full_scale_v must be positive")
        return self.full_scale_v / (2.0**self.enob)

    @property
    def standard_uncertainty_v(self) -> float:
        return self.step_v / math.sqrt(12.0)


def enob_standard_uncertainty(enob: float, full_scale_v: float) -> float:
    """Return the standard uncertainty implied by ENOB and full-scale range."""

    return ENOBNoiseModel(enob=enob, full_scale_v=full_scale_v).standard_uncertainty_v


def lag1_autocorrelation(values: ArrayLike) -> float:
    """Estimate lag-1 autocorrelation with safe finite-sample behavior."""

    x = np.asarray(values, dtype=float)
    if x.ndim != 1 or x.size < 3:
        return 0.0
    centered = x - float(np.mean(x))
    denom = float(np.dot(centered, centered))
    if denom <= 0.0:
        return 0.0
    rho = float(np.dot(centered[:-1], centered[1:]) / denom)
    return max(-0.999, min(0.999, rho))


def effective_sample_size(sample_count: int, lag1_rho: float) -> float:
    """Return AR(1)-style effective sample size for mean uncertainty."""

    if sample_count <= 0:
        raise ValueError("sample_count must be positive")
    rho = max(-0.999, min(0.999, float(lag1_rho)))
    n_eff = float(sample_count) * (1.0 - rho) / (1.0 + rho)
    return max(1.0, min(float(sample_count), n_eff))


def mean_uncertainty_with_autocorrelation(
    values: ArrayLike,
    *,
    sample_std: float | None = None,
    lag1_rho: float | None = None,
) -> tuple[float, float]:
    """Return ``(u_mean, n_eff)`` including optional lag-1 correlation."""

    x = np.asarray(values, dtype=float)
    if x.ndim != 1 or x.size < 2:
        raise ValueError("values must be a one-dimensional array with at least two samples")
    std = float(sample_std) if sample_std is not None else float(np.std(x, ddof=1))
    rho = lag1_autocorrelation(x) if lag1_rho is None else float(lag1_rho)
    n_eff = effective_sample_size(int(x.size), rho)
    return std / math.sqrt(n_eff), n_eff
