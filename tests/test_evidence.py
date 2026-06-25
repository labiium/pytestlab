from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from pytestlab.cli import app
from pytestlab.evidence import EvidenceDriftError
from pytestlab.evidence import check_evidence
from pytestlab.evidence import generate_evidence
from pytestlab.evidence import payload_hash


def test_evidence_generate_writes_manifest_and_report(tmp_path) -> None:
    bundle = generate_evidence(tmp_path)

    assert bundle.manifest_path.exists()
    assert bundle.report_path.exists()
    manifest = json.loads(bundle.manifest_path.read_text(encoding="utf-8"))
    assert manifest["payload_sha256"] == payload_hash(manifest)
    assert "not accreditation certificates" in manifest["non_accreditation_notice"]
    assert manifest["release_hygiene"]["status"] == "pass"
    assert (
        manifest["release_hygiene"]["runtime_version"]
        == manifest["release_hygiene"]["commitizen_version"]
    )
    assert (
        "data_origin=measured"
        in manifest["release_hygiene"]["report_grade_gate_policy"]["measured_report_grade_requires"]
    )
    assert {"dcc", "d-si"} <= set(manifest["schema_hashes"])
    assert any("test_gum_annex_h.py" in item["path"] for item in manifest["source_artifacts"])
    report = bundle.report_path.read_text(encoding="utf-8")
    assert "PyTestLab Evidence Bundle" in report
    assert "Release Hygiene" in report
    assert "non-measured export gate" in report
    assert manifest["payload_sha256"] in report


def test_evidence_check_accepts_fresh_bundle_ignoring_timestamp(tmp_path) -> None:
    bundle = generate_evidence(tmp_path)
    manifest = json.loads(bundle.manifest_path.read_text(encoding="utf-8"))
    manifest["generated_utc"] = "2099-01-01T00:00:00Z"
    bundle.manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )

    result = check_evidence(tmp_path)

    assert result["status"] == "ok"
    assert result["payload_sha256"] == manifest["payload_sha256"]


def test_evidence_check_rejects_payload_drift(tmp_path) -> None:
    bundle = generate_evidence(tmp_path)
    manifest = json.loads(bundle.manifest_path.read_text(encoding="utf-8"))
    manifest["verification_commands"].append("unexpected command")
    bundle.manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )

    with pytest.raises(EvidenceDriftError, match="payload_sha256"):
        check_evidence(tmp_path)


def test_evidence_check_rejects_report_tampering(tmp_path) -> None:
    bundle = generate_evidence(tmp_path)
    bundle.report_path.write_text(
        bundle.report_path.read_text(encoding="utf-8") + "\nunaudited edit\n",
        encoding="utf-8",
    )

    with pytest.raises(EvidenceDriftError, match="report hash"):
        check_evidence(tmp_path)


def test_evidence_cli_generate_and_check(tmp_path) -> None:
    runner = CliRunner()

    generate_result = runner.invoke(app, ["evidence", "generate", "--output", str(tmp_path)])
    assert generate_result.exit_code == 0, generate_result.output
    assert (tmp_path / "manifest.json").exists()

    check_result = runner.invoke(app, ["evidence", "check", str(tmp_path)])
    assert check_result.exit_code == 0, check_result.output
    assert "Evidence OK" in check_result.output


def test_evidence_conformance_rows_are_all_passing() -> None:
    from pytestlab.evidence import build_jcgm_conformance_rows

    rows = build_jcgm_conformance_rows()

    assert len(rows) >= 8
    assert {row["standard"] for row in rows} >= {"JCGM 100:2008", "JCGM 101:2008", "JCGM 102:2011"}
    assert [row for row in rows if row["status"] != "pass"] == []
