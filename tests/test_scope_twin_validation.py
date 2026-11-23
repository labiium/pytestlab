from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from pytestlab.cli import app
from pytestlab.validation.scope_twin import ScopeTwinValidationError
from pytestlab.validation.scope_twin import check_scope_twin_known_truth_validation
from pytestlab.validation.scope_twin import run_scope_twin_known_truth_validation


def test_scope_twin_known_truth_report_brackets_analytic_values(tmp_path):
    report = run_scope_twin_known_truth_validation(tmp_path, mc_samples=1200, seed=1234)

    assert report.passed
    assert {metric.name for metric in report.metrics} == {"mean", "rms", "peak_to_peak"}
    for metric in report.metrics:
        assert metric.interval_low <= metric.true_value <= metric.interval_high
        assert metric.standard_uncertainty > 0.0
    checked = check_scope_twin_known_truth_validation(tmp_path)
    assert checked.payload_sha256 == report.payload_sha256
    assert checked.waveform_sha256 == report.waveform_sha256


def test_scope_twin_known_truth_check_detects_tampering(tmp_path):
    report = run_scope_twin_known_truth_validation(tmp_path, mc_samples=1200, seed=1234)
    report_path = tmp_path / "scope_twin_known_truth_report.json"
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    payload["metrics"][0]["nominal"] += 1.0
    report_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    with pytest.raises(ScopeTwinValidationError, match="payload hash mismatch"):
        check_scope_twin_known_truth_validation(tmp_path)

    assert report.payload_sha256 != ""


def test_scope_twin_known_truth_check_detects_manifest_tampering(tmp_path):
    run_scope_twin_known_truth_validation(tmp_path, mc_samples=1200, seed=1234)
    manifest_path = tmp_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["waveform_sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    with pytest.raises(ScopeTwinValidationError, match="waveform_sha256"):
        check_scope_twin_known_truth_validation(tmp_path)


def test_evidence_scope_twin_cli_generates_and_checks_bundle(tmp_path):
    result = CliRunner().invoke(
        app,
        ["evidence", "scope-twin", "--output", str(tmp_path), "--mc-samples", "1200", "--check"],
    )

    assert result.exit_code == 0
    assert "Scope-twin evidence check passed" in result.stdout
    assert (tmp_path / "scope_twin_known_truth_report.json").is_file()
    assert (tmp_path / "manifest.json").is_file()


def test_evidence_scope_oracle_cli_alias_generates_and_checks_bundle(tmp_path):
    result = CliRunner().invoke(
        app,
        ["evidence", "scope-oracle", "--output", str(tmp_path), "--mc-samples", "1200", "--check"],
    )

    assert result.exit_code == 0
    assert "Scope-twin evidence check passed" in result.stdout
    assert (tmp_path / "scope_twin_known_truth_report.json").is_file()
