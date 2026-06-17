"""Compliance tests against JCGM 102 (GUM Supplement 2): multivariate/complex."""

from __future__ import annotations

import math

import numpy as np
import pytest

from pytestlab.uncertainty import AtomRegistry, Quantity
from pytestlab.uncertainty.multivariate import (
    ComplexQuantity,
    QuantityVector,
    covariance_between,
)


def test_from_covariance_reproduces_matrix_exactly():
    """Importing a covariance matrix (correlated inputs) reproduces it exactly."""

    cov = np.array([[4.0, 1.2, 0.0], [1.2, 9.0, -2.0], [0.0, -2.0, 1.0]])
    means = [1.0, 2.0, 3.0]
    vec = QuantityVector.from_covariance(means, cov, registry=AtomRegistry())
    assert vec.means() == pytest.approx(np.array(means))
    assert vec.covariance_matrix() == pytest.approx(cov, abs=1e-9)


def test_propagated_covariance_is_J_Sigma_Jt():
    """Σ_Y = J Σ_X Jᵀ for a linear vector transform of correlated inputs."""

    cov = np.array([[4.0, 1.0], [1.0, 2.0]])
    reg = AtomRegistry()
    vec = QuantityVector.from_covariance([0.0, 0.0], cov, registry=reg)
    x1, x2 = vec[0], vec[1]
    # y1 = 2 x1 + x2 ; y2 = x1 - 3 x2
    y1 = 2 * x1 + x2
    y2 = x1 - 3 * x2
    J = np.array([[2.0, 1.0], [1.0, -3.0]])
    expected = J @ cov @ J.T
    out = QuantityVector([y1, y2]).covariance_matrix()
    assert out == pytest.approx(expected, abs=1e-9)


def test_complex_magnitude_and_phase_propagation():
    """Complex measurand: |Γ| and phase propagate with correlated Re/Im."""

    cov = np.array([[1e-4, 0.3e-4], [0.3e-4, 4e-4]])
    reg = AtomRegistry()
    vec = QuantityVector.from_covariance([0.6, 0.2], cov, registry=reg)
    gamma = ComplexQuantity(vec[0], vec[1])

    mag = gamma.magnitude()
    phase = gamma.phase()
    assert mag.nominal == pytest.approx(math.hypot(0.6, 0.2))
    assert phase.nominal == pytest.approx(math.atan2(0.2, 0.6))

    # Compare magnitude uncertainty to the closed-form first-order expression:
    # u(|G|)^2 = (a^2 u_a^2 + b^2 u_b^2 + 2 a b cov) / (a^2+b^2)
    a, b = 0.6, 0.2
    ua2, ub2, cab = cov[0, 0], cov[1, 1], cov[0, 1]
    expected = math.sqrt((a**2 * ua2 + b**2 * ub2 + 2 * a * b * cab) / (a**2 + b**2))
    assert mag.u == pytest.approx(expected, rel=1e-9)


def test_complex_product_covariance_symmetric_psd():
    reg = AtomRegistry()
    g1 = ComplexQuantity(*QuantityVector.from_covariance(
        [0.5, 0.1], np.array([[1e-4, 0.0], [0.0, 1e-4]]), registry=reg, key_prefix="g1"
    ).components)
    g2 = ComplexQuantity(*QuantityVector.from_covariance(
        [0.2, 0.3], np.array([[2e-4, 0.0], [0.0, 1e-4]]), registry=reg, key_prefix="g2"
    ).components)
    prod = g1 * g2
    cov = prod.covariance_matrix()
    assert cov == pytest.approx(cov.T)
    assert np.all(np.linalg.eigvalsh(cov) > -1e-12)
