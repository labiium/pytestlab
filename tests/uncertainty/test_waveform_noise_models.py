from __future__ import annotations

import math

import numpy as np
import pytest

from pytestlab.uncertainty.noise import effective_sample_size
from pytestlab.uncertainty.noise import enob_standard_uncertainty
from pytestlab.uncertainty.noise import lag1_autocorrelation
from pytestlab.uncertainty.noise import mean_uncertainty_with_autocorrelation


def test_enob_standard_uncertainty_matches_lsb_rectangular_model() -> None:
    assert enob_standard_uncertainty(8.0, 2.0) == pytest.approx((2.0 / 256.0) / math.sqrt(12.0))


def test_autocorrelation_reduces_effective_sample_size() -> None:
    n_eff_uncorrelated = effective_sample_size(100, 0.0)
    n_eff_correlated = effective_sample_size(100, 0.8)

    assert n_eff_uncorrelated == pytest.approx(100.0)
    assert n_eff_correlated < n_eff_uncorrelated


def test_mean_uncertainty_increases_for_correlated_waveform() -> None:
    rng = np.random.default_rng(1234)
    white = rng.normal(0.0, 1.0, 512)
    correlated = np.empty_like(white)
    correlated[0] = white[0]
    for idx in range(1, white.size):
        correlated[idx] = 0.9 * correlated[idx - 1] + white[idx]

    white_u, white_n_eff = mean_uncertainty_with_autocorrelation(white)
    corr_u, corr_n_eff = mean_uncertainty_with_autocorrelation(correlated)

    assert lag1_autocorrelation(correlated) > lag1_autocorrelation(white)
    assert corr_n_eff < white_n_eff
    assert corr_u > white_u
