from __future__ import annotations

import math
import warnings
from typing import Any
from typing import cast

import numpy as np
import pytest
from uncertainties import ufloat as ext_ufloat

import pytestlab.uncertainty as ptu
from pytestlab.experiments.uncertainty_serialization import deserialize_uncertain_value
from pytestlab.experiments.uncertainty_serialization import serialize_uncertain_value
from pytestlab.uncertainty import CorrelationComponentWarning
from pytestlab.uncertainty import NominalOnlyDecisionWarning
from pytestlab.uncertainty import Quantity
from pytestlab.uncertainty import correlated_values
from pytestlab.uncertainty import correlated_values_norm
from pytestlab.uncertainty import correlation_matrix
from pytestlab.uncertainty import covariance_matrix
from pytestlab.uncertainty import from_ufloats
from pytestlab.uncertainty import to_ufloat_correlated
from pytestlab.uncertainty import umath
from pytestlab.uncertainty import uq
from pytestlab.uncertainty.multivariate import QuantityVector


def _q_ufunc(ufunc: Any, *args: Any) -> Quantity:
    return cast(Quantity, ufunc(*args))


def _provenance(value: Quantity) -> ptu.ResultProvenance:
    return cast(ptu.ResultProvenance, value.provenance)


def test_public_scalar_exports_are_available():
    names = [
        "uq",
        "nominal_value",
        "std_dev",
        "nominal_values",
        "std_devs",
        "correlated_values",
        "correlated_values_norm",
        "covariance_matrix",
        "correlation_matrix",
        "from_ufloat",
        "from_ufloats",
        "to_ufloat_correlated",
        "umath",
    ]
    for name in names:
        assert hasattr(ptu, name), name


def test_quick_factory_and_string_constructor():
    direct = uq(1.23, 0.04, "V", label="reading")
    assert isinstance(direct, Quantity)
    assert direct.n == pytest.approx(1.23)
    assert direct.s == pytest.approx(0.04)
    assert direct.unit == "V"

    parsed = uq.fromstr("2.0+/-0.1", label="x")
    assert parsed.n == pytest.approx(2.0)
    assert parsed.s == pytest.approx(0.1)
    assert uq.fromstr("2.0±0.1").s == pytest.approx(0.1)
    assert uq.fromstr("2.00(10)").s == pytest.approx(0.10)

    assert uq.limit(10.0, 0.3).s == pytest.approx(0.3 / math.sqrt(3.0))
    assert uq.percent(10.0, 1.0).s == pytest.approx(0.1)
    assert uq.ppm(10.0, 100.0).s == pytest.approx(0.001)
    assert uq.relative(10.0, 0.02).s == pytest.approx(0.2)


def test_numeric_conversions_return_nominal_values_without_warning():
    q = uq(-2.75, 0.1, "V")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert float(q) == pytest.approx(-2.75)
        assert int(q) == -2
        assert np.asarray([q], dtype=float) == pytest.approx([-2.75])

    assert caught == []


def test_scalar_equality_and_ordering_use_nominal_values():
    q = uq(2.0, 0.1, "V")

    assert q == 2.0
    assert 2.0 == q
    assert q != 2.1
    assert q > 1.0
    assert 1.0 < q
    assert q >= 2.0
    assert q < 3.0
    assert q <= 2.0
    assert q == pytest.approx(2.0)
    assert pytest.approx(2.0) == q
    assert bool(q)
    assert not bool(uq(0.0, 0.1, "V"))

    same = q
    different = uq(2.0, 0.2, "V")
    assert q == same
    assert q == different
    assert q.same_representation(same)
    assert not q.same_representation(different)
    ordered = sorted([uq(3.0, 0.5, "V"), q, uq(1.0, 0.01, "V")])
    assert [value.n for value in ordered] == [1.0, 2.0, 3.0]


def test_nominal_comparisons_convert_units_and_reject_incompatible_units():
    volts = uq(1.0, 0.1, "V", registry=ptu.AtomRegistry())
    millivolts = uq(1000.0, 50.0, "mV", registry=ptu.AtomRegistry())
    higher = uq(1001.0, 0.01, "mV", registry=ptu.AtomRegistry())

    assert volts == millivolts
    assert volts >= millivolts
    assert volts <= millivolts
    assert volts < higher
    assert higher > volts

    with pytest.raises(ptu.UnitCompatibilityError):
        _ = volts > uq(1.0, 0.1, "A")
    with pytest.raises(ptu.UnitCompatibilityError):
        _ = volts == uq(1.0, 0.1)


def test_quantity_decision_helpers_are_guard_banded_and_auditable():
    q = uq(2.0, 0.1, "V")

    # Operators intentionally answer the routine nominal-value question, while
    # decision helpers account for the expanded uncertainty interval.
    assert q > 1.85
    assert not q.exceeds(1.85, k=2.0)
    assert q.consistent_with(2.15, k=2.0)
    assert not q.consistent_with(2.25, k=2.0)
    assert q.en_ratio(2.15, k=2.0) == pytest.approx(0.75)
    assert q.exceeds(1.79, k=2.0)
    assert not q.exceeds(1.85, k=2.0)
    assert q.below(2.21, k=2.0)
    assert not q.below(2.15, k=2.0)
    assert q.within(1.79, 2.21, k=2.0)

    comparison = q.compare(1.79, k=2.0)
    assert comparison.left_nominal == pytest.approx(2.0)
    assert comparison.right_nominal == pytest.approx(1.79)
    assert comparison.combined_standard_uncertainty == pytest.approx(0.1)
    assert comparison.direction == "above"
    assert comparison.unit == "V"


def test_nominal_only_decision_helpers_warn_user():
    q = Quantity.constant(5.0, "V")
    q.provenance = ptu.ResultProvenance.current(
        data_origin=ptu.DataOrigin.MEASURED,
        evidence_purpose=ptu.EvidencePurpose.MEASUREMENT_RESULT,
        origin_detail="missing accuracy metadata",
        provenance_complete=False,
    )

    assert "nominal-only" in repr(q)
    assert "nominal-only" in str(q)
    with pytest.warns(NominalOnlyDecisionWarning, match="not guard-banded"):
        assert q.exceeds(4.9)
    with pytest.warns(NominalOnlyDecisionWarning, match="report_grade_blockers"):
        assert q.consistent_with(5.0)


def test_quantity_comparison_preserves_shared_covariance_for_same_registry():
    x, y = correlated_values(
        [10.0, 10.1],
        [[0.04, 0.04], [0.04, 0.04]],
        units=["V", "V"],
        labels=["x", "y"],
    )

    comparison = y.compare(x, k=2.0)

    assert comparison.delta == pytest.approx(0.1)
    assert comparison.combined_standard_uncertainty == pytest.approx(0.0, abs=1e-8)
    assert comparison.en_ratio > 1e6
    assert not y.consistent_with(x, k=2.0)


def test_scaled_unit_add_sub_and_compare_scale_gradients():
    reg = ptu.AtomRegistry()
    volts = uq(1.0, 0.1, "V", label="volts", registry=reg)
    millivolts = uq(1000.0, 100.0, "mV", label="millivolts", registry=reg)

    summed = volts + millivolts
    difference = volts - millivolts
    comparison = volts.compare(millivolts)

    assert summed.nominal == pytest.approx(2.0)
    assert summed.unit == "V"
    assert summed.u == pytest.approx(math.sqrt(0.1**2 + 0.1**2))
    assert difference.nominal == pytest.approx(0.0)
    assert difference.u == pytest.approx(math.sqrt(0.1**2 + 0.1**2))
    assert comparison.combined_standard_uncertainty == pytest.approx(math.sqrt(0.1**2 + 0.1**2))
    assert comparison.consistent


def test_uncertainty_formatting_and_html_repr():
    q = uq(2.0, 0.1)
    assert f"{q}" == str(q) == "2.0 +/- 0.1"
    assert format(q, ".1u") == "2.0+/-0.1"
    assert format(q, ".1uS") == "2.0(1)"
    assert format(q, ".1uP") == "2.0±0.1"
    assert format(q, ".1uL") == "2.0 \\pm 0.1"
    assert format(q, ".2f") == "2.00"
    html = q._repr_html_()
    assert "nominal" in html and "uncertainty" in html


def test_umath_and_numpy_scalar_ufuncs_propagate_uncertainty():
    x = uq(0.5, 0.01)
    assert umath.exp(x).n == pytest.approx(math.exp(0.5))
    assert umath.exp(x).s == pytest.approx(math.exp(0.5) * 0.01)
    assert np.exp(x).s == pytest.approx(math.exp(0.5) * 0.01)
    assert _q_ufunc(np.add, x, 1.0).n == pytest.approx(1.5)
    assert _q_ufunc(np.multiply, x, 2.0).s == pytest.approx(0.02)
    assert _q_ufunc(np.true_divide, x, 2.0).s == pytest.approx(0.005)
    assert _q_ufunc(np.power, x, 2.0).s == pytest.approx(2.0 * 0.5 * 0.01)
    absolute = abs(uq(-2.0, 0.1, "V"))
    assert absolute.n == pytest.approx(2.0)
    assert absolute.s == pytest.approx(0.1)
    with pytest.raises(TypeError):
        np.isfinite(x)


def test_numpy_scalar_left_hand_ufuncs_do_not_recurse():
    q = uq(2.0, 0.1)

    assert (np.float64(3.0) + q).n == pytest.approx(5.0)
    assert _q_ufunc(np.add, np.float64(3.0), q).s == pytest.approx(0.1)
    assert (np.int64(4) * q).s == pytest.approx(0.4)
    assert _q_ufunc(np.multiply, np.int64(4), q).n == pytest.approx(8.0)
    assert _q_ufunc(np.subtract, np.float64(5.0), q).n == pytest.approx(3.0)
    assert _q_ufunc(np.true_divide, np.float64(4.0), q).s == pytest.approx(0.1)
    assert _q_ufunc(np.equal, np.float64(2.0), q)
    assert _q_ufunc(np.less, np.float64(1.0), q)
    assert _q_ufunc(np.greater, np.float64(3.0), q)
    assert np.float64(1.0) < q
    assert np.float64(3.0) > q


def test_correlated_values_and_uncertainties_migration_round_trip():
    x, y = correlated_values([1.0, 2.0], [[1.0, 0.25], [0.25, 4.0]], labels=["x", "y"])
    assert covariance_matrix([x, y]) == pytest.approx(np.array([[1.0, 0.25], [0.25, 4.0]]))
    corr = correlation_matrix([x, y])
    assert corr[0, 1] == pytest.approx(0.125)

    a, b = correlated_values_norm([(1.0, 1.0), (2.0, 2.0)], [[1.0, -0.5], [-0.5, 1.0]])
    assert covariance_matrix([a, b])[0, 1] == pytest.approx(-1.0)

    ux, uy = to_ufloat_correlated([x, y], tags=["x", "y"])
    restored = from_ufloats([ux, uy], labels=["x", "y"])
    assert covariance_matrix(restored) == pytest.approx(covariance_matrix([x, y]))

    ex = ext_ufloat(3.0, 0.2)
    ey = ex * 2.0
    restored_external = from_ufloats([ex, ey])
    assert covariance_matrix(restored_external) == pytest.approx(
        np.array([[0.04, 0.08], [0.08, 0.16]])
    )


def test_covariance_validation_rejects_invalid_inputs_and_preserves_singular_psd():
    with pytest.raises(ValueError, match="square"):
        correlated_values([1.0, 2.0], [[1.0, 0.0]])
    with pytest.raises(ValueError, match="symmetric"):
        correlated_values([1.0, 2.0], [[1.0, 0.1], [0.2, 1.0]])
    with pytest.raises(ValueError, match="finite"):
        correlated_values([1.0], [[float("nan")]])
    with pytest.raises(ValueError, match="negative variances|positive semi-definite"):
        correlated_values([1.0], [[-1.0]])
    with pytest.raises(ValueError, match="positive semi-definite"):
        QuantityVector.from_covariance([1.0, 2.0], np.array([[1.0, 2.0], [2.0, 1.0]]))

    singular = QuantityVector.from_covariance([1.0, 2.0], np.array([[1.0, 1.0], [1.0, 1.0]]))
    assert singular.covariance_matrix() == pytest.approx(np.array([[1.0, 1.0], [1.0, 1.0]]))


def test_low_level_covariance_mutation_rejects_non_finite_values():
    reg = ptu.AtomRegistry()
    x = reg.mint(nominal=0.0, std_uncertainty=1.0, label="x")
    y = reg.mint(nominal=0.0, std_uncertainty=1.0, label="y")

    with pytest.raises(ValueError, match="covariance must be finite"):
        reg.set_covariance(x.uid, y.uid, float("nan"))
    with pytest.raises(ValueError, match="correlation coefficient must be finite"):
        reg.set_correlation(x.uid, y.uid, float("inf"))


def test_error_components_expose_correlation_cross_terms():
    x, y = correlated_values([1.0, 2.0], [[1.0, -0.5], [-0.5, 4.0]], labels=["x", "y"])
    z = x + y
    with pytest.warns(CorrelationComponentWarning):
        diagonal = z.error_components()
    assert all(row["type"] == "diagonal" for row in diagonal)

    rows = z.error_components(basis="variance", correlation="include_cross")
    assert any(row["type"] == "cross" and row["variance_contribution"] < 0 for row in rows)
    assert sum(row["variance_contribution"] for row in rows) == pytest.approx(z.variance)

    with pytest.warns(CorrelationComponentWarning):
        pct = z.budget().percentage_contributions()
    assert pct
    with pytest.warns(CorrelationComponentWarning):
        dict_rows = z.budget().to_dicts()
    assert dict_rows[0]["label"] in {"x", "y"}
    with pytest.warns(CorrelationComponentWarning):
        polars_rows = z.budget().to_polars()
    assert polars_rows.height == 2


def test_measurement_result_serializes_native_quantity():
    q = uq(5.0, 0.2, "V")
    data, metadata = serialize_uncertain_value(q)
    restored = deserialize_uncertain_value(data, metadata)
    assert isinstance(restored, Quantity)
    assert restored.n == pytest.approx(5.0)
    assert restored.s == pytest.approx(0.2)
    assert restored.unit == "V"


def test_expression_parity_against_uncertainties_for_representative_scalar_case():
    x = uq(2.0, 0.1)
    y = uq(3.0, 0.2, registry=x.registry)
    ptl_result = umath.exp(x / y) + x * y

    ux = ext_ufloat(2.0, 0.1)
    uy = ext_ufloat(3.0, 0.2)
    external = math.e ** (ux / uy) + ux * uy

    assert ptl_result.n == pytest.approx(external.nominal_value)
    assert ptl_result.s == pytest.approx(external.std_dev)


def test_binary_arithmetic_provenance_is_conservatively_incomplete_for_report_grade():
    trace = ptu.TraceabilityRef(source="accredited_cal", certificate_id="CAL-1")
    reg = ptu.AtomRegistry()
    left = uq(1.0, 0.1, "V", label="left", registry=reg, traceability=trace)
    right = uq(2.0, 0.2, "V", label="right", registry=reg, traceability=trace)
    left.provenance = ptu.ResultProvenance.current(provenance_complete=True)
    right.provenance = ptu.ResultProvenance.current(provenance_complete=False)

    derived = left + right
    derived.measurement_model = ptu.MeasurementModel(
        output_name="sum",
        output_unit="V",
        function="left + right",
    )

    assert derived.provenance is not left.provenance
    assert _provenance(derived).provenance_complete is False
    assert ptu.is_report_grade(derived) is False
    assert "provenance_complete is false or missing" in ptu.report_grade_blockers(derived)


def test_unary_math_provenance_is_conservatively_incomplete_for_report_grade():
    trace = ptu.TraceabilityRef(source="accredited_cal", certificate_id="CAL-UNARY")
    q = uq(1.0, 0.1, "", traceability=trace)
    q.provenance = ptu.ResultProvenance.current(provenance_complete=True)

    for derived in (-q, q**2, umath.exp(q)):
        derived.measurement_model = ptu.MeasurementModel(
            output_name="derived",
            output_unit=derived.unit,
            function="unary derived",
        )
        assert derived.provenance is not q.provenance
        assert _provenance(derived).provenance_complete is False
        assert ptu.is_report_grade(derived) is False


def test_atan2_derived_provenance_records_both_operands():
    trace = ptu.TraceabilityRef(source="accredited_cal", certificate_id="CAL-ATAN2")
    reg = ptu.AtomRegistry()
    y = uq(1.0, 0.1, "", registry=reg, label="y", traceability=trace)
    x = uq(2.0, 0.2, "", registry=reg, label="x", traceability=trace)
    y.provenance = ptu.ResultProvenance.current(provenance_complete=True)
    x.provenance = ptu.ResultProvenance.current(provenance_complete=True)

    angle = umath.atan2(y, x)

    assert _provenance(angle).provenance_complete is False
    derived_from = _provenance(angle).amendments[0]["derived_from"]
    assert len(derived_from) == 2


def test_invalid_standard_uncertainties_are_rejected():
    with pytest.raises(ValueError, match="non-negative"):
        uq(1.0, -0.1)
    with pytest.raises(ValueError, match="finite"):
        uq(1.0, float("inf"))
    with pytest.raises(ValueError, match="non-negative"):
        correlated_values_norm([(1.0, -0.1)], [[1.0]])
    with pytest.raises(ValueError, match="finite"):
        correlated_values_norm([(1.0, float("nan"))], [[1.0]])
    with pytest.raises(ValueError, match="non-negative"):
        ptu.QuantityArray.from_samples([1.0, 2.0], independent_std=-0.1)
    with pytest.raises(ValueError, match="finite"):
        ptu.QuantityArray.from_samples([1.0, 2.0], independent_std=[0.1, float("nan")])


def test_html_repr_escapes_unit_text():
    q = uq(1.0, 0.1, '<script>alert("x")</script>')
    html = q._repr_html_()
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_budget_to_dicts_serializes_traceability_as_json_dict():
    trace = ptu.TraceabilityRef(source="accredited_cal", certificate_id="CAL-JSON")
    q = uq(1.0, 0.1, "V", traceability=trace)
    row = q.budget().to_dicts()[0]
    assert row["traceability"]["certificate_id"] == "CAL-JSON"
    assert isinstance(row["traceability"], dict)
