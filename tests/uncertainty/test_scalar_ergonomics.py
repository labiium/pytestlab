from __future__ import annotations

import math
from typing import Any
from typing import cast

import numpy as np
import pytest
from uncertainties import ufloat as ext_ufloat

import pytestlab.uncertainty as ptu
from pytestlab.experiments.uncertainty_serialization import deserialize_uncertain_value
from pytestlab.experiments.uncertainty_serialization import serialize_uncertain_value
from pytestlab.uncertainty import CorrelationComponentWarning
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


def test_lossy_float_conversion_is_rejected():
    q = uq(2.0, 0.1, "V")
    with pytest.raises(TypeError, match="nominal extraction"):
        float(q)
    with pytest.raises(TypeError, match="nominal extraction"):
        np.asarray([q], dtype=float)


def test_uncertainty_formatting_and_html_repr():
    q = uq(2.0, 0.1)
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
    assert z.budget().to_dicts()[0]["label"] in {"x", "y"}
    assert z.budget().to_polars().height == 2


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
