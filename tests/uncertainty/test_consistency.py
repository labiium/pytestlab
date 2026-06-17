"""Property / internal-consistency tests for the uncertainty engine."""

from __future__ import annotations

import math

import pytest

from pytestlab.experiments.uncertainty_serialization import deserialize_uncertain_value
from pytestlab.experiments.uncertainty_serialization import serialize_uncertain_value
from pytestlab.uncertainty import AtomRegistry
from pytestlab.uncertainty import Quantity
from pytestlab.uncertainty import round_to_significant
from pytestlab.uncertainty.multivariate import covariance_between


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
    from pytestlab.uncertainty import UnitCompatibilityError
    from pytestlab.uncertainty import functions as fn

    reg = AtomRegistry()
    volts = _q(reg, 2.0, 0.1, "v", unit="V")
    with pytest.raises(UnitCompatibilityError):
        fn.log(volts)


def test_unit_prefix_reconciliation_in_mul_and_div():
    """Regression: mul/div must reconcile unit prefixes (V / mV == 2.0)."""

    reg = AtomRegistry()
    volts = _q(reg, 2.0, 0.02, "v", unit="V")
    millivolts = _q(reg, 1000.0, 1.0, "mv", unit="mV")
    ratio = volts / millivolts
    assert ratio.nominal == pytest.approx(2.0)
    assert ratio.unit == ""
    assert ratio.relative_u == pytest.approx(math.hypot(0.02 / 2.0, 1.0 / 1000.0))


def test_empty_unit_scalar_add_sub_adopts_unit():
    """Regression: a unitless scalar combines with a united quantity."""

    reg = AtomRegistry()
    v = _q(reg, 2.0, 0.1, "v", unit="V")
    assert (5 - v).nominal == pytest.approx(3.0)
    assert (5 - v).unit == "V"
    assert (1 + v).nominal == pytest.approx(3.0)
    assert (v + 1).unit == "V"


def test_variance_cost_is_independent_of_registry_size():
    """u_c() cost depends on the quantity's complexity, not the registry's."""

    import time

    reg = AtomRegistry()
    atoms = [reg.mint(nominal=0.0, std_uncertainty=1.0, label=f"a{i}") for i in range(2000)]
    for i in range(0, 1998, 2):
        reg.set_correlation(atoms[i].uid, atoms[i + 1].uid, 0.3)
    small = Quantity.from_atom(atoms[0], reg) + Quantity.from_atom(atoms[1], reg)
    assert small.u == pytest.approx(math.sqrt(2.6))  # 1 + 1 + 2*0.3
    start = time.perf_counter()
    for _ in range(2000):
        _ = small.u
    per_call_us = (time.perf_counter() - start) / 2000 * 1e6
    assert per_call_us < 20.0, f"{per_call_us:.1f} us/call is too slow"


def test_registry_clear_and_keyed_reads_stay_bounded():
    from pytestlab.uncertainty.specs import AccuracySpec
    from pytestlab.uncertainty.specs import UncertaintyContext

    reg = AtomRegistry()
    spec = AccuracySpec(reading_percent=0.1, range_percent=0.01)
    for i in range(1000):
        spec.quantity(
            UncertaintyContext(
                reading=5.0 + i * 1e-6, unit="V", range_value=10.0, source_key="dmm1:VDC:10.0"
            ),
            reg,
        )
    # gain + range atoms are reused across reads at the same operating point.
    assert len(reg.atoms) == 2
    reg.clear()
    assert len(reg.atoms) == 0 and not reg.has_correlations


def test_non_psd_correlations_raise_not_silently_clamp():
    """Inconsistent (non-PSD) declared correlations must fail loudly."""

    reg = AtomRegistry()
    a, b, c = _q(reg, 0, 1, "a"), _q(reg, 0, 1, "b"), _q(reg, 0, 1, "c")
    ua, ub, uc = list(a.grad)[0], list(b.grad)[0], list(c.grad)[0]
    reg.set_correlation(ua, ub, 0.9)
    reg.set_correlation(ub, uc, 0.9)
    reg.set_correlation(ua, uc, -0.9)
    with pytest.raises(ValueError, match="positive semi-definite"):
        _ = (a - b + c).u
    # A valid linear combination in the same registry still evaluates.
    assert (a + b).u == pytest.approx(math.sqrt(2 + 2 * 0.9))


def test_correlation_coefficient_bounds_enforced():
    reg = AtomRegistry()
    a, b = _q(reg, 0, 1, "a"), _q(reg, 0, 1, "b")
    with pytest.raises(ValueError, match=r"\[-1, 1\]"):
        reg.set_correlation(list(a.grad)[0], list(b.grad)[0], 1.5)


def test_domain_errors_raise_clearly():
    from pytestlab.uncertainty import functions as fn

    reg = AtomRegistry()
    neg = _q(reg, -4.0, 0.1, "neg")
    zero = _q(reg, 0.0, 0.1, "zero")
    one = _q(reg, 1.0, 0.1, "one")
    with pytest.raises(ValueError):
        fn.sqrt(neg)
    with pytest.raises(ValueError):
        fn.log(zero)
    with pytest.raises(ZeroDivisionError):
        _ = one / zero


def test_zero_uncertainty_atom_behaves_as_exact():
    reg = AtomRegistry()
    exact = _q(reg, 5.0, 0.0, "exact")
    noisy = _q(reg, 2.0, 0.1, "noisy")
    assert exact.u == 0.0
    assert (exact * noisy).u == pytest.approx(5.0 * 0.1)
