from __future__ import annotations

from pathlib import Path

from pytestlab.evidence import build_digital_export_evidence
from pytestlab.evidence import scan_claim_boundaries
from pytestlab.uncertainty import QuantityArray
from pytestlab.uncertainty import validate_dcc_profile_xml
from pytestlab.uncertainty import waveform_reductions_to_digital_exports


def test_waveform_scalar_reductions_export_dsi_and_unsigned_dcc_subset() -> None:
    waveform = QuantityArray.from_samples([0.0, 1.0, -1.0, 0.5], unit="V", independent_std=0.02)
    exports = waveform_reductions_to_digital_exports(
        {
            "mean": waveform.mean(),
            "rms": waveform.rms(),
            "peak_to_peak": waveform.peak_to_peak_monte_carlo(samples=2000, seed=7),
        },
        identifier_prefix="scope-ch1",
        allow_incomplete=True,
    )

    assert exports["unsigned_dcc_subset"] is True
    assert "not an accredited calibration certificate" in exports["non_claim"]
    assert set(exports["reductions"]) == {"mean", "rms", "peak_to_peak"}
    for item in exports["reductions"].values():
        assert item["dsi"]["unit"] == "V"
        assert item["dsi"]["dsi_schema_version"] == "2.2.1"
        assert 'unsigned="true"' in item["dcc_xml"]
        validate_dcc_profile_xml(item["dcc_xml"])


def test_evidence_digital_export_rows_are_validated() -> None:
    evidence = build_digital_export_evidence()

    assert evidence["unsigned_dcc_subset"] is True
    assert [row["status"] for row in evidence["rows"]] == ["pass", "pass", "pass"]
    assert {row["name"] for row in evidence["rows"]} == {"mean", "rms", "peak_to_peak"}
    assert all(len(row["dcc_xml_sha256"]) == 64 for row in evidence["rows"])


def test_claims_document_and_scan_block_overclaiming_language() -> None:
    claims = Path("docs/validation/CLAIMS.md").read_text(encoding="utf-8")
    assert "PyTestLab is not an accredited calibration laboratory" in claims
    assert "does not confer ISO/IEC 17025 accreditation" in claims

    scan = scan_claim_boundaries()
    assert scan["status"] == "pass"
    assert scan["findings"] == []
