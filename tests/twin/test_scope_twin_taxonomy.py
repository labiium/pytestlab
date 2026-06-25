from __future__ import annotations

import json

import pytest

from pytestlab.twin import CharacterizedScopeTwin
from pytestlab.twin import OscilloscopeTwinTools
from pytestlab.twin import ScopeValidationOracle
from pytestlab.twin import TwinDomain
from pytestlab.twin import TwinEvidenceError
from pytestlab.twin import TwinIdentity
from pytestlab.twin import TwinValidationStatus
from pytestlab.twin import check_twin_evidence
from pytestlab.twin import residual_metric
from pytestlab.twin import write_twin_evidence
from pytestlab.twin.residuals import ResidualReport
from pytestlab.validation.scope_twin import run_scope_twin_known_truth_validation


def test_scope_validation_oracle_is_not_characterized_hardware(tmp_path) -> None:
    oracle = ScopeValidationOracle()
    evidence = oracle.validation_evidence()

    assert evidence.fidelity.value == "ideal"
    assert evidence.data_origin == "twin_oracle"
    assert evidence.evidence_purpose == "software_validation"
    assert "not a characterized hardware twin" in evidence.claim

    path = write_twin_evidence(tmp_path / "oracle.json", evidence)
    checked = check_twin_evidence(path)
    assert checked["payload_sha256"] == evidence.payload_sha256


def test_oscilloscope_twin_tools_keep_oracle_validation_low_burden(tmp_path) -> None:
    tools = OscilloscopeTwinTools(model="MXR404A")

    report = tools.validate(tmp_path, mc_samples=1000)

    assert report.passed
    assert (tmp_path / "scope_twin_known_truth_report.json").exists()
    with pytest.raises(ValueError, match="Only kind='oracle'"):
        tools.validate(tmp_path, kind="characterized")


def test_scope_known_truth_report_labels_oracle_origin(tmp_path) -> None:
    report = run_scope_twin_known_truth_validation(tmp_path, mc_samples=1000)
    payload = json.loads((tmp_path / "scope_twin_known_truth_report.json").read_text())

    assert report.passed
    assert payload["data_origin"] == "twin_oracle"
    assert payload["evidence_purpose"] == "software_validation"
    assert payload["twin_fidelity"] == "ideal"
    assert "not characterized hardware" in payload["twin_claim_scope"]


def test_characterized_scope_twin_requires_passing_residual_report() -> None:
    identity = TwinIdentity(model="MXR404A", serial_hash="sha256:redacted")
    domain = TwinDomain(
        quantities=("rms",),
        sample_rate_sps=(1e6, 2e6),
        amplitude_v=(0.1, 1.0),
        frequency_hz=(1e3, 1e5),
    )
    failing = residual_metric(
        "rms",
        hardware_nominal=1.0,
        twin_nominal=2.0,
        hardware_u=0.01,
        twin_u=0.01,
    )
    report = ResidualReport.build(
        twin_identity=identity,
        domain=domain,
        metrics=[failing],
        context={"sample_rate_sps": 1.5e6, "amplitude_v": 0.5, "frequency_hz": 10e3},
    )

    assert report.status is TwinValidationStatus.FAIL
    with pytest.raises(ValueError, match="passing residual report"):
        CharacterizedScopeTwin(identity=identity, domain=domain, residual_report=report)


def test_characterized_scope_twin_evidence_is_domain_limited(tmp_path) -> None:
    identity = TwinIdentity(model="MXR404A", serial_hash="sha256:redacted")
    domain = TwinDomain(quantities=("rms",), amplitude_v=(0.1, 1.0))
    metric = residual_metric(
        "rms",
        hardware_nominal=1.0,
        twin_nominal=1.001,
        hardware_u=0.01,
        twin_u=0.01,
    )
    report = ResidualReport.build(
        twin_identity=identity,
        domain=domain,
        metrics=[metric],
        context={"amplitude_v": 0.5},
    )
    twin = CharacterizedScopeTwin(identity=identity, domain=domain, residual_report=report)
    evidence = twin.validation_evidence()

    assert evidence.fidelity.value == "characterized"
    assert evidence.data_origin == "characterized_twin"
    assert evidence.evidence_purpose == "twin_validation"
    assert evidence.status is TwinValidationStatus.PASS
    assert "not a measured calibration result" in evidence.claim

    path = write_twin_evidence(tmp_path / "characterized.json", evidence)
    payload = check_twin_evidence(path)
    payload["status"] = "fail"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    with pytest.raises(TwinEvidenceError, match="payload hash mismatch"):
        check_twin_evidence(path)
