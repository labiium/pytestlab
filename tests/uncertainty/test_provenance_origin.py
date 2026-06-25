from __future__ import annotations

import json
from xml.etree import ElementTree as ET

import pytest

from pytestlab.instruments.uncertainty_adapters import nominal_measurement_quantity
from pytestlab.instruments.waveform_result import WaveformResult
from pytestlab.uncertainty import DataOrigin
from pytestlab.uncertainty import EvidencePurpose
from pytestlab.uncertainty import QuantityArray
from pytestlab.uncertainty import ResultProvenance
from pytestlab.uncertainty import quantity_to_pytestlab_evidence_xml
from pytestlab.uncertainty import waveform_reductions_to_digital_exports
from pytestlab.uncertainty.metrology import report_grade_blockers
from pytestlab.uncertainty.specs import AccuracySpec


def test_result_provenance_serializes_origin_and_purpose() -> None:
    provenance = ResultProvenance.current(
        data_origin=DataOrigin.MEASURED,
        evidence_purpose=EvidencePurpose.MEASUREMENT_RESULT,
        origin_detail="fixture live acquisition",
        provenance_complete=True,
    )

    payload = provenance.model_dump(mode="json")

    assert payload["data_origin"] == "measured"
    assert payload["evidence_purpose"] == "measurement_result"
    assert payload["origin_detail"] == "fixture live acquisition"
    assert payload["git_sha"]


def test_report_grade_blocks_unknown_origin_even_with_complete_provenance() -> None:
    waveform = QuantityArray.from_samples([1.0, 2.0, 3.0], unit="V", independent_std=0.1)
    q = waveform.mean()
    q.provenance = ResultProvenance.current(provenance_complete=True)

    blockers = report_grade_blockers(q)

    assert any("data_origin 'unknown'" in blocker for blocker in blockers)


def test_nominal_measurement_quantity_is_explicitly_non_report_grade() -> None:
    reason = "unit-test profile is missing readback accuracy metadata"

    quantity = nominal_measurement_quantity(
        1.23,
        "V",
        function="read_voltage",
        output_name="read_voltage_ch1",
        reason=reason,
    )

    assert quantity.nominal == pytest.approx(1.23)
    assert quantity.u == pytest.approx(0.0)
    assert not quantity.is_report_grade
    assert reason in quantity.report_grade_blockers()
    assert quantity.measurement_model is not None
    assert quantity.provenance is not None
    assert quantity.provenance.data_origin is DataOrigin.MEASURED
    assert quantity.provenance.evidence_purpose is EvidencePurpose.MEASUREMENT_RESULT


def test_non_measured_evidence_export_requires_explicit_override() -> None:
    waveform = QuantityArray.from_samples([1.0, 2.0, 3.0], unit="V", independent_std=0.1)
    waveform.provenance = ResultProvenance.current(
        data_origin=DataOrigin.SYNTHETIC_KNOWN_TRUTH,
        evidence_purpose=EvidencePurpose.SOFTWARE_VALIDATION,
        origin_detail="unit-test synthetic waveform",
        provenance_complete=False,
    )
    q = waveform.mean()

    with pytest.raises(ValueError, match="allow_non_measured=True"):
        quantity_to_pytestlab_evidence_xml(q, identifier="synthetic", allow_incomplete=True)

    xml = quantity_to_pytestlab_evidence_xml(
        q,
        identifier="synthetic",
        allow_incomplete=True,
        allow_non_measured=True,
    )
    root = ET.fromstring(xml)
    administrative = root.find("administrativeData")
    assert administrative is not None
    assert administrative.findtext("dataOrigin") == "synthetic_known_truth"
    assert administrative.findtext("evidencePurpose") == "software_validation"
    assert administrative.findtext("originDetail") == "unit-test synthetic waveform"


def test_waveform_reduction_exports_carry_origin_and_purpose() -> None:
    waveform = QuantityArray.from_samples([0.0, 1.0, -1.0], unit="V", independent_std=0.1)
    waveform.provenance = ResultProvenance.current(
        data_origin=DataOrigin.REPLAYED,
        evidence_purpose=EvidencePurpose.REPLAY_REGRESSION,
        origin_detail="fixture replay",
        provenance_complete=False,
    )

    exports = waveform_reductions_to_digital_exports(
        {"mean": waveform.mean()}, identifier_prefix="fixture", allow_incomplete=True
    )

    row = exports["reductions"]["mean"]
    assert row["data_origin"] == "replayed"
    assert row["evidence_purpose"] == "replay_regression"
    assert "<dataOrigin>replayed</dataOrigin>" in row["dcc_xml"]


def test_waveform_result_evidence_bundle_records_measured_origin(tmp_path) -> None:
    wave = WaveformResult(
        [0.0, 0.5, -0.5],
        unit="V",
        channel=1,
        metadata={
            "waveform_uncertainty": {
                "unit": "V",
                "resolution": 0.01,
                "accuracy_spec": AccuracySpec(offset=0.01, distribution="standard"),
                "data_origin": "measured",
                "evidence_purpose": "measurement_result",
                "origin_detail": "unit-test live-like capture",
            }
        },
    )

    path = wave.to_evidence_bundle(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["data_origin"] == "measured"
    assert payload["evidence_purpose"] == "measurement_result"
    assert payload["origin_detail"] == "unit-test live-like capture"
    assert {metric["data_origin"] for metric in payload["metrics"].values()} == {"measured"}
