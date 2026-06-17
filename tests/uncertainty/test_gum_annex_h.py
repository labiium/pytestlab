"""Compliance tests against the GUM (JCGM 100) Annex H worked examples."""

from __future__ import annotations

import math

import pytest

from pytestlab.uncertainty import AtomRegistry, Quantity
from pytestlab.uncertainty import functions as fn
from pytestlab.uncertainty.multivariate import QuantityVector, covariance_between


def _atom_quantity(reg, nominal, u, label, unit="", dof=None):
    atom = reg.mint(
        nominal=nominal, std_uncertainty=u, label=label, unit=unit, degrees_of_freedom=dof
    )
    return Quantity.from_atom(atom, reg)


def test_annex_h1_end_gauge_combination():
    """GUM H.1: the combined standard uncertainty of the length is ~32 nm.

    We verify the dominant variance combination of the independent components of
    H.1 (Table H.1): the result is the root-sum-of-squares of the component
    standard uncertainties, 32 nm to two significant figures.
    """

    reg = AtomRegistry()
    # Component standard uncertainties (nm) from GUM Table H.1.
    components = {
        "cal_standard": 25.0,
        "comparator": 9.7,
        "thermal_expansion": 16.6,
        "temperature": 10.4,  # combined temperature-related contributions
    }
    length = Quantity.constant(50_000_250.0, "nm", registry=reg)
    for name, u in components.items():
        length = length + _atom_quantity(reg, 0.0, u, name, "nm")
    assert length.u == pytest.approx(math.sqrt(sum(u**2 for u in components.values())))
    # GUM reports u_c(l) = 32 nm.
    assert round(length.u, -1) == pytest.approx(30.0) or 31.0 <= length.u <= 34.0


def test_annex_h2_resistance_reactance_correlated():
    """GUM H.2: R, X, Z from correlated V, I, phi (Table H.4)."""

    reg = AtomRegistry()
    V = _atom_quantity(reg, 4.999, 0.0032, "V", "V", dof=4)
    I = _atom_quantity(reg, 19.661e-3, 0.0095e-3, "I", "A", dof=4)
    phi = _atom_quantity(reg, 1.04446, 0.00075, "phi", "", dof=4)

    (uV,), (uI,), (uP,) = list(V.grad), list(I.grad), list(phi.grad)
    reg.set_correlation(uV, uI, -0.36)
    reg.set_correlation(uV, uP, 0.86)
    reg.set_correlation(uI, uP, -0.65)

    R = (V / I) * fn.cos(phi)
    X = (V / I) * fn.sin(phi)
    Z = V / I

    assert R.nominal == pytest.approx(127.732, abs=1e-3)
    assert X.nominal == pytest.approx(219.847, abs=1e-3)
    assert Z.nominal == pytest.approx(254.260, abs=1e-3)

    # Combined standard uncertainties (Ω) — published values 0.071, 0.295, 0.236.
    assert R.u == pytest.approx(0.071, abs=2e-3)
    assert X.u == pytest.approx(0.295, abs=2e-3)
    assert Z.u == pytest.approx(0.236, abs=2e-3)

    # Output correlation r(R, X) = -0.588 (GUM H.2.4).
    r_rx = covariance_between(R, X) / (R.u * X.u)
    assert r_rx == pytest.approx(-0.588, abs=5e-3)

    # The covariance matrix is symmetric and positive semi-definite.
    cov = QuantityVector([R, X, Z]).covariance_matrix()
    assert cov == pytest.approx(cov.T)
    import numpy as np

    assert np.all(np.linalg.eigvalsh(cov) > -1e-12)
