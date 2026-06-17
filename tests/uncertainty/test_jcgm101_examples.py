"""Compliance tests against JCGM 101 (GUM Supplement 1) examples."""

from __future__ import annotations

import math

import numpy as np
import pytest

from pytestlab.uncertainty import AtomRegistry, Distribution, Quantity
from pytestlab.uncertainty.montecarlo import adaptive_monte_carlo, monte_carlo
from pytestlab.uncertainty.validation import validate_model


def _rect_atom(reg, half_width, label):
    # Rectangular on [-a, a] -> standard uncertainty a/sqrt(3).
    atom = reg.mint(
        nominal=0.0,
        std_uncertainty=half_width / math.sqrt(3.0),
        label=label,
        distribution=Distribution.RECTANGULAR,
    )
    return Quantity.from_atom(atom, reg)


def test_jcgm101_additive_model_section_9_2():
    """JCGM 101 §9.2: Y = X1+X2+X3+X4, each rectangular on [-1, 1].

    GUM gives u(y) = 2/sqrt(3) ~= 1.155. Because the convolution of four
    rectangular pdfs is far more peaked than a Gaussian, the Monte Carlo 95 %
    coverage interval is markedly *narrower* than the GUM normal-based ±2.31.
    """

    reg = AtomRegistry()
    xs = {f"x{i}": _rect_atom(reg, 1.0, f"x{i}") for i in range(1, 5)}

    def model(x1, x2, x3, x4):
        return x1 + x2 + x3 + x4

    analytical = model(**xs)
    assert analytical.u == pytest.approx(2.0 / math.sqrt(3.0), rel=1e-12)

    u = 2.0 / math.sqrt(3.0)
    mc = monte_carlo(model, xs, samples=1_000_000, seed=7, confidence=0.95)
    assert mc.std == pytest.approx(u, rel=2e-3)
    assert mc.mean == pytest.approx(0.0, abs=5e-3)

    mc_half = (mc.interval[1] - mc.interval[0]) / 2.0
    # The convolution of four rectangular pdfs is platykurtic (light tails), so
    # its 95 % coverage interval is narrower than the k=2 GUM interval and even
    # marginally narrower than the Gaussian 1.96-sigma interval.
    assert mc_half < 2.0 * u  # narrower than k=2 GUM interval (2.309)
    assert mc_half == pytest.approx(1.96 * u, rel=0.02)  # ~2.24, near-Gaussian


def test_jcgm101_gum_validation_linear_model_passes():
    """A linear model: the GUM result is validated by Monte Carlo (§8)."""

    reg = AtomRegistry()
    a = Quantity.from_atom(reg.mint(nominal=10.0, std_uncertainty=0.1, label="a"), reg)
    b = Quantity.from_atom(reg.mint(nominal=5.0, std_uncertainty=0.2, label="b"), reg)
    # Samples chosen so the MC numerical noise on the interval endpoints is
    # below the validation tolerance delta (JCGM 101 §8 requirement).
    report = validate_model(lambda a, b: a + 2 * b, {"a": a, "b": b}, samples=2_000_000, seed=1)
    assert report.validated


def test_jcgm101_gum_validation_nonlinear_model_fails():
    """A strongly nonlinear, skewed model is *not* validated by GUM (§8)."""

    reg = AtomRegistry()
    a = Quantity.from_atom(reg.mint(nominal=1.0, std_uncertainty=0.3, label="a"), reg)
    report = validate_model(lambda a: a**2, {"a": a}, samples=400_000, seed=2)
    assert not report.validated
    # The MC interval is shifted positive (a^2 >= 0) relative to the symmetric GUM one.
    assert report.mc_interval[0] > report.gum_interval[0]


def test_jcgm101_adaptive_converges():
    reg = AtomRegistry()
    a = Quantity.from_atom(reg.mint(nominal=10.0, std_uncertainty=0.1, label="a"), reg)
    b = Quantity.from_atom(reg.mint(nominal=5.0, std_uncertainty=0.2, label="b"), reg)
    res = adaptive_monte_carlo(lambda a, b: a + 2 * b, {"a": a, "b": b}, seed=3)
    assert res.std == pytest.approx(math.hypot(0.1, 0.4), rel=5e-3)
    assert res.draws >= 200_000


def test_correlated_sampling_matches_declared_correlation():
    reg = AtomRegistry()
    a = Quantity.from_atom(reg.mint(nominal=0.0, std_uncertainty=1.0, label="a"), reg)
    b = Quantity.from_atom(reg.mint(nominal=0.0, std_uncertainty=1.0, label="b"), reg)
    reg.set_correlation(list(a.grad)[0], list(b.grad)[0], 0.8)
    mc = monte_carlo(lambda a, b: a + b, {"a": a, "b": b}, samples=500_000, seed=11)
    # var(a+b) = 1 + 1 + 2*0.8 = 3.6
    assert mc.std == pytest.approx(math.sqrt(3.6), rel=5e-3)
