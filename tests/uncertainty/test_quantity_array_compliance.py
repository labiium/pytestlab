from __future__ import annotations

import math

import numpy as np
import pytest

from pytestlab.experiments import MeasurementDatabase
from pytestlab.experiments import MeasurementResult
from pytestlab.experiments.uncertainty_serialization import deserialize_uncertain_value
from pytestlab.experiments.uncertainty_serialization import serialize_uncertain_value
from pytestlab.uncertainty import AtomRegistry
from pytestlab.uncertainty import CalibrationCertificate
from pytestlab.uncertainty import DataOrigin
from pytestlab.uncertainty import Distribution
from pytestlab.uncertainty import EvidencePurpose
from pytestlab.uncertainty import MeasurementModel
from pytestlab.uncertainty import Quantity
from pytestlab.uncertainty import QuantityArray
from pytestlab.uncertainty import ResultProvenance
from pytestlab.uncertainty import ToleranceInterval
from pytestlab.uncertainty import TraceabilityRef
from pytestlab.uncertainty import UnitCompatibilityError
from pytestlab.uncertainty import assess_conformity
from pytestlab.uncertainty import is_report_grade
from pytestlab.uncertainty import quantity_to_unsigned_dcc_xml
from pytestlab.uncertainty import require_dsi_unit
from pytestlab.uncertainty import resolve_traceability_ref
from pytestlab.uncertainty import to_dsi_unit
from pytestlab.uncertainty import verify_cached_schema_files
from pytestlab.uncertainty.specs import AccuracySpec
from pytestlab.uncertainty.specs import UncertaintyContext


def test_dsi_unit_resolution_is_explicit_and_never_guesses() -> None:
    assert to_dsi_unit("V") == ("V", True)
    assert to_dsi_unit("mV")[1] is True
    assert require_dsi_unit("Hz") == "Hz"
    scalar = Quantity.constant(1.2, "V")
    assert scalar.to_dsi()["unit"] == "V"
    with pytest.raises(UnitCompatibilityError):
        require_dsi_unit("not_a_unit")


def test_traceability_ref_round_trips_through_atoms_and_quantity_serialization() -> None:
    trace = TraceabilityRef(
        source="accredited_cal",
        certificate_id="CAL-42",
        issuing_lab="Example Cal Lab",
        reference_standard="SI volt via NMI",
    )
    context = UncertaintyContext(reading=10.0, unit="V", traceability=trace)
    quantity = AccuracySpec(offset=0.1, distribution=Distribution.STANDARD).quantity(
        context, AtomRegistry()
    )

    data, meta = serialize_uncertain_value(quantity)
    restored = deserialize_uncertain_value(data, meta)
    atom_payload = next(iter(restored.to_dict()["atoms"].values()))

    assert atom_payload["traceability"]["certificate_id"] == "CAL-42"
    assert restored.budget().entries[0].traceability.supports_si_traceability_claim is True


def test_quantity_array_covariance_matches_dense_scalar_oracle() -> None:
    reg = AtomRegistry()
    gain = reg.mint(
        nominal=0.0,
        std_uncertainty=0.01,
        label="scope vertical gain",
        unit="",
        distribution=Distribution.STANDARD,
        source="manufacturer_spec",
        traceability=TraceabilityRef(source="manufacturer_spec"),
        key="gain",
    )
    offset = reg.mint(
        nominal=0.0,
        std_uncertainty=0.02,
        label="scope offset",
        unit="V",
        distribution=Distribution.STANDARD,
        source="manufacturer_spec",
        traceability=TraceabilityRef(source="manufacturer_spec"),
        key="offset",
    )
    reg.set_correlation(gain.uid, offset.uid, 0.25)
    nominal = np.array([1.0, -0.5, 0.25])
    diag = np.array([0.001, 0.002, 0.003]) ** 2
    arr = QuantityArray(
        nominal,
        unit="V",
        diagonal_variance=diag,
        atom_sensitivities={gain.uid: nominal, offset.uid: 1.0},
        registry=reg,
    )

    dense = arr.covariance_matrix()
    scalar_components = [
        Quantity(nominal[i], "V", {gain.uid: nominal[i], offset.uid: 1.0}, reg)
        for i in range(len(nominal))
    ]
    oracle = np.empty_like(dense)
    for i, qi in enumerate(scalar_components):
        for j, qj in enumerate(scalar_components):
            cov = 0.0
            for uid_a, ga in qi.grad.items():
                for uid_b, gb in qj.grad.items():
                    cov += ga * gb * reg.covariance(uid_a, uid_b)
            if i == j:
                cov += diag[i]
            oracle[i, j] = cov

    assert dense == pytest.approx(oracle)
    assert arr.variance == pytest.approx(np.diag(oracle))


def test_quantity_array_reductions_emit_measurement_model_and_effective_dof() -> None:
    waveform = QuantityArray.from_samples([1.0, 1.1, 0.9, 1.2], unit="V", independent_std=0.05)

    mean = waveform.mean(dof_method="validated_independent")
    assert mean.nominal == pytest.approx(1.05)
    assert mean.u == pytest.approx(math.sqrt(4 * 0.05**2 / 16))
    assert mean.measurement_model.function == "mean(waveform)"
    assert mean.measurement_model.dof_method == "validated_independent"
    assert mean.budget().effective_degrees_of_freedom == pytest.approx(3.0)

    rms = waveform.rms(dof_method="lag1_autocorrelation")
    assert rms.measurement_model.dof_method in {
        "lag1_autocorrelation",
        "lag1_nonpositive_independent",
        "constant_signal_independent",
    }
    assert rms.measurement_model.method == "gum_first_order"

    vpp = waveform.peak_to_peak()
    assert vpp.measurement_model.method == "monte_carlo_required"
    assert "not report-grade" in vpp.measurement_model.linearization_note


def test_quantity_array_serialization_database_and_npz_sidecar(tmp_path) -> None:
    arr = QuantityArray.from_samples([1.0, 2.0, 3.0], unit="V", independent_std=0.1)
    manifest = arr.save_npz_sidecar(tmp_path / "waveform_uncertainty.npz")
    assert manifest["format"] == "npz"
    assert manifest["schema_version"] == "1.1"
    assert manifest["arrays"]["nominal"] == "nominal"
    assert len(manifest["sha256"]) == 64
    loaded = QuantityArray.load_npz_sidecar(tmp_path / "waveform_uncertainty.npz")
    assert loaded.nominal.tolist() == [1.0, 2.0, 3.0]
    assert loaded.u == pytest.approx(np.full(3, 0.1))
    assert arr.to_dsi()["unit"] == "V"

    payload, metadata = serialize_uncertain_value(arr)
    restored = deserialize_uncertain_value(payload, metadata)
    assert isinstance(restored, QuantityArray)
    assert restored.nominal.tolist() == [1.0, 2.0, 3.0]
    assert restored.provenance.provenance_complete is False

    with MeasurementDatabase(tmp_path / "qa") as db:
        key = db.store_measurement(
            None,
            MeasurementResult(
                values=arr, instrument="scope", units="V", measurement_type="waveform"
            ),
        )
        db_restored = db.retrieve_measurement(key)
    assert isinstance(db_restored.values, QuantityArray)
    assert db_restored.values.u == pytest.approx(np.full(3, 0.1))

    result = MeasurementResult(
        values=arr, instrument="scope", units="V", measurement_type="waveform"
    )
    result.save(str(tmp_path / "direct_save"))
    assert (tmp_path / "direct_save.npz").exists()


def test_quantity_array_legacy_metadata_missing_loads_incomplete() -> None:
    restored = QuantityArray.from_dict({"nominal": [1.0], "unit": "V", "diagonal_variance": [0.0]})
    assert restored.provenance.provenance_complete is False


def test_conformity_result_is_structured_and_specific_risk_requires_prior() -> None:
    measured = Quantity.constant(9.8, "V")
    result = assess_conformity(
        measured,
        ToleranceInterval(lower=9.0, upper=11.0, unit="V"),
        coverage_factor=2.0,
    )

    assert result.decision == "pass"
    assert result.specific_risk == {"pfa": None, "pfr": None}
    assert result.decision_rule["source"]


def test_unsigned_dcc_export_records_schema_and_unsigned_scope() -> None:
    measured = Quantity.constant(1.0, "V")
    with pytest.raises(ValueError, match="non-measured or unknown data origin"):
        quantity_to_unsigned_dcc_xml(measured, identifier="r1")
    xml = quantity_to_unsigned_dcc_xml(
        measured,
        identifier="r1",
        allow_incomplete=True,
        allow_non_measured=True,
    )

    assert 'schemaVersion="3.3.0"' in xml
    assert 'unsigned="true"' in xml
    assert "<dataOrigin>unknown</dataOrigin>" in xml
    assert "<evidencePurpose>measurement_result</evidencePurpose>" in xml
    assert "pytestlabMeasurementEvidence" in xml
    assert "digitalCalibrationCertificate" not in xml
    assert "coverageFactor" in xml
    assert "reportGradeBlockers" in xml


def test_report_grade_requires_accredited_traceability_and_complete_provenance() -> None:
    reg = AtomRegistry()
    trace = TraceabilityRef(source="accredited_cal", certificate_id="CAL-1")
    atom = reg.mint(
        nominal=0.0,
        std_uncertainty=0.01,
        label="gain",
        unit="V",
        distribution=Distribution.STANDARD,
        traceability=trace,
        key="gain",
    )
    q = Quantity(1.0, "V", {atom.uid: 1.0}, reg)
    q.measurement_model = MeasurementModel(output_name="voltage", output_unit="V", function="test")
    q.provenance = ResultProvenance.current(
        data_origin=DataOrigin.MEASURED,
        evidence_purpose=EvidencePurpose.MEASUREMENT_RESULT,
        provenance_complete=True,
    )

    assert is_report_grade(q) is True
    xml = quantity_to_unsigned_dcc_xml(q, identifier="report-grade")
    assert "report-grade" in xml
    assert "reportGrade>true" in xml


def test_certificate_resolver_matches_operating_point() -> None:
    cert = CalibrationCertificate(
        certificate_id="CAL-42",
        issuing_lab="Example Cal Lab",
        accreditation_id="ACC-123",
        entries=[{"function": "read_channels", "channel": 1, "upper": 10.0, "unit": "V"}],
    )

    trace = resolve_traceability_ref(
        [cert], function="read_channels", channel=1, range_value=5.0, unit="V"
    )

    assert trace is not None
    assert trace.certificate_id == "CAL-42"
    assert trace.supports_si_traceability_claim is True


def test_quantity_array_monte_carlo_peak_to_peak_is_explicit_mc() -> None:
    arr = QuantityArray.from_samples([0.0, 1.0, -1.0], unit="V", independent_std=0.01)

    vpp = arr.peak_to_peak_monte_carlo(samples=2_000, seed=123)

    assert vpp.nominal == pytest.approx(2.0)
    assert vpp.u > 0
    assert vpp.measurement_model.method == "monte_carlo"


def test_quantity_array_fft_propagates_linear_covariance() -> None:
    arr = QuantityArray.from_samples([1.0, 0.0, -1.0, 0.0], unit="V", independent_std=0.01)

    spectrum = arr.fft(sample_rate=4.0, window=None)

    assert spectrum.frequency.tolist() == [0.0, 1.0, 2.0]
    assert spectrum.nominal.tolist() == pytest.approx(np.fft.rfft(arr.nominal).tolist())
    magnitude = spectrum.magnitude()
    assert magnitude.nominal.tolist() == pytest.approx(np.abs(np.fft.rfft(arr.nominal)).tolist())
    assert np.all(magnitude.u >= 0)


def test_cached_dcc_dsi_schema_files_are_pinned() -> None:
    verified = verify_cached_schema_files()

    assert set(verified) == {"dcc", "d-si"}
    assert all(len(value) == 64 for value in verified.values())
