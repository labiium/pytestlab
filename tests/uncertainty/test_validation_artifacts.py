from __future__ import annotations

import json
from pathlib import Path


def test_uncertainty_validation_artifact_records_non_accreditation_boundary() -> None:
    text = Path("docs/validation/uncertainty_engine_validation_20260618.md").read_text(
        encoding="utf-8"
    )

    assert "not an accreditation certificate" in text
    assert "does not confer ISO/IEC 17025 accreditation" in text
    assert "DCC 3.3.0" in text
    assert "D-SI 2.2.1" in text


def test_public_docs_do_not_overclaim_accreditation() -> None:
    docs = Path("docs/en/user_guide/uncertainty.md").read_text(encoding="utf-8")

    forbidden = [
        "PyTestLab is ISO/IEC 17025 accredited",
        "PyTestLab confers accreditation",
        "automatically ISO/IEC 17025 compliant",
    ]
    for phrase in forbidden:
        assert phrase not in docs
    assert "PyTestLab is not ISO/IEC 17025 accredited" in docs


def test_uncertainty_json_schemas_are_present_and_parseable() -> None:
    schema_dir = Path("schemas/uncertainty")
    expected = {
        "TraceabilityRef.schema.json",
        "CalibrationCertificate.schema.json",
        "CalibrationCertificateEntry.schema.json",
        "MeasurementModel.schema.json",
        "ResultProvenance.schema.json",
        "ToleranceInterval.schema.json",
        "ConformityResult.schema.json",
    }

    assert expected <= {path.name for path in schema_dir.glob("*.json")}
    for name in expected:
        payload = json.loads((schema_dir / name).read_text(encoding="utf-8"))
        assert payload["type"] == "object"
