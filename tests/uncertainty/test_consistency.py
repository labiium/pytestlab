"""Property / internal-consistency tests for the uncertainty engine."""

from __future__ import annotations

import math

import numpy as np
import pytest

from pytestlab.uncertainty import AtomRegistry, Distribution, Quantity, round_to_significant
from pytestlab.uncertainty.multivariate import covariance_between
from pytestlab.experiments.uncertainty_serialization import (
    deserialize_uncertain_value,
    serialize_uncertain_value,
)


def _q(reg, nominal, u, label, unit="", dof=None):
    return Quantity.from_atom(
        reg.mint(nominal=nominal, std_uncertainty=u, label=label, unit=unit, degrees_of_freedom=dof),
        reg,
    )


def test_independent_atoms_combine_as_rss():
    reg = AtomRegistry()
    a, b, c = _q(reg, 1, 0.1, "a"), _q(reg, 2, 0.2, "b"), _q(reg, 3, 0.3, "c")
    total = a + b + c
    assert total.u == pytest.approx(math.sqrt(0.1**2 + 0.2**2 + 0.3**2))


def test_shared_atom_is_perfectly_correlated():
    reg = AtomRegistry()
    a = _q(reg, 5.0, 0.2, "a")
    assert (a + a).u == pytest.approx(0.4)
    assert (a - a).u == pytest.approx(0.0)


def test_variance_equals_g_sigma_g():
    reg = AtomRegistry()
    a = _q(reg, 1.0, 0.5, "a")
    b = _q(reg, 1.0, 0.3, "b")
    reg.set_correlation(list(a.grad)[0], list(b.grad)[0], 0.5)
    y = 2 * a - b
    # gᵀΣg with g=(2,-1)
    cov = covariance_between(a, b)
    expected = 4 * 0.25 + 1 * 0.09 - 2 * 2 * 1 * cov
    assert y.variance == pytest.approx(expected)


def test_welch_satterthwaite_matches_formula():
    reg = AtomRegistry()
    a = _q(reg, 100.0, 1.0, "a", dof=10)
    b = _q(reg, 50.0, 2.0, "b", dof=5)
    budget = (a + b).budget()
    u_c = budget.combined_standard_uncertainty
    expected = u_c**4 / (1.0**4 / 10 + 2.0**4 / 5)
    assert budget.effective_degrees_of_freedom == pytest.approx(expected)


def test_significant_figure_rounding():
    assert round_to_significant(0.123456, 2) == pytest.approx(0.12)
    assert round_to_significant(1234.0, 2) == pytest.approx(1200.0)
    assert round_to_significant(0.0, 2) == 0.0


def test_serialization_round_trip_preserves_correlation():
    reg = AtomRegistry()
    a = _q(reg, 5.0, 0.2, "a", unit="V")
    b = _q(reg, 3.0, 0.1, "b", unit="V")
    reg.set_correlation(list(a.grad)[0], list(b.grad)[0], 0.7)
    y = a + b
    data, meta = serialize_uncertain_value(y)
    restored = deserialize_uncertain_value(data, meta)
    assert restored.nominal == pytest.approx(y.nominal)
    assert restored.u == pytest.approx(y.u, rel=1e-12)
    assert restored.unit == y.unit


def test_arbitrary_function_dimensionless_guard():
    from pytestlab.uncertainty import functions as fn
    from pytestlab.uncertainty import UnitCompatibilityError

    reg = AtomRegistry()
    volts = _q(reg, 2.0, 0.1, "v", unit="V")
    with pytest.raises(UnitCompatibilityError):
        fn.log(volts)
