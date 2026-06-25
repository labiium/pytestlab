from __future__ import annotations

import hashlib
import json

import pytest
from typer.testing import CliRunner

from pytestlab.cli import app
from pytestlab.twin import CharacterizedScopeTwin
from pytestlab.twin import ResidualReport
from pytestlab.twin import TwinDomain
from pytestlab.twin import TwinEvidenceError
from pytestlab.twin import TwinIdentity
from pytestlab.twin import TwinValidationStatus
from pytestlab.twin import check_residual_report
from pytestlab.twin import check_twin_evidence
from pytestlab.twin import load_residual_report
from pytestlab.twin import residual_metric
from pytestlab.twin import residual_report_from_replay_fixture
from pytestlab.twin import write_residual_report
from pytestlab.twin import write_twin_evidence
from pytestlab.validation.hardware_parity import build_replay_fixture
from pytestlab.validation.hardware_parity import write_replay_fixture


def _binblock(payload: bytes) -> bytes:
    length = str(len(payload)).encode("ascii")
    return b"#" + str(len(length)).encode("ascii") + length + payload


def _fixture() -> dict:
    return build_replay_fixture(
        model="MXR404A",
        idn="KEYSIGHT TECHNOLOGIES,MXR404A,MY99999999,11.2",
        preamble="0,0,8,1,1e-6,0,0,0.01,-1.28,0",
        raw_block=_binblock(bytes([120, 124, 128, 132, 136, 132, 128, 124])),
        sample_rate="1000000",
        source="unit_test_capture",
    )


def _refresh_fixture_hash(fixture: dict) -> dict:
    clean = {k: v for k, v in fixture.items() if k not in {"generated_utc", "payload_sha256"}}
    raw = json.dumps(clean, sort_keys=True, separators=(",", ":")).encode("utf-8")
    fixture["payload_sha256"] = hashlib.sha256(raw).hexdigest()
    return fixture


def test_replay_fixture_carries_redacted_identity_and_transcript_hash() -> None:
    fixture = _fixture()

    assert fixture["instrument_identity"]["model"] == "MXR404A"
    assert fixture["instrument_identity"]["serial_hash"].startswith("sha256:")
    assert "MY99999999" not in json.dumps(fixture)
    assert len(fixture["command_transcript_sha256"]) == 64


def test_fixture_integrity_residual_report_is_not_characterized_twin_validation(tmp_path) -> None:
    fixture_path = write_replay_fixture(tmp_path / "fixture.json", _fixture())

    report = residual_report_from_replay_fixture(fixture_path)

    assert report.passed
    assert report.data_origin == "replayed"
    assert report.evidence_purpose == "replay_regression"
    assert report.context["waveform_sha256"]
    assert report.context["command_transcript_sha256"]
    assert "not characterized-twin validation" in report.context["claim_boundary"]
    with pytest.raises(ValueError, match="twin_validation residual evidence"):
        CharacterizedScopeTwin(
            identity=report.twin_identity,
            domain=report.domain,
            residual_report=report,
        )

    path = write_residual_report(tmp_path / "residual.json", report)
    checked = check_residual_report(path)
    assert checked["payload_sha256"] == report.payload_sha256


def test_independent_parity_residual_report_can_characterize_scope_twin(tmp_path) -> None:
    fixture = _fixture()
    fixture["classification"]["parity_mode"] = "independent_parity"
    fixture["classification"]["expected_source"] = "pinned_characterized_scope_twin"
    fixture["classification"]["stimulus_known"] = True
    fixture_path = write_replay_fixture(tmp_path / "fixture.json", _refresh_fixture_hash(fixture))

    report = residual_report_from_replay_fixture(fixture_path)
    twin = CharacterizedScopeTwin(
        identity=report.twin_identity,
        domain=report.domain,
        residual_report=report,
    )
    evidence = twin.validation_evidence()

    assert report.supports_characterized_twin
    assert report.evidence_purpose == "twin_validation"
    assert evidence.data_origin == "characterized_twin"
    assert evidence.evidence_purpose == "twin_validation"


def test_residual_report_check_detects_tampering(tmp_path) -> None:
    fixture = _fixture()
    fixture["classification"]["parity_mode"] = "independent_parity"
    report = residual_report_from_replay_fixture(_refresh_fixture_hash(fixture))
    path = write_residual_report(tmp_path / "residual.json", report)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["metrics"][0]["residual"] = 123.0
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    with pytest.raises(TwinEvidenceError, match="payload hash mismatch"):
        load_residual_report(path)


def test_twin_cli_generates_residual_and_rejects_fixture_integrity_characterize(tmp_path) -> None:
    fixture_path = write_replay_fixture(tmp_path / "fixture.json", _fixture())
    out = tmp_path / "residual"

    result = CliRunner().invoke(
        app,
        ["twin", "residual-from-replay", str(fixture_path), "--output", str(out), "--check"],
    )

    assert result.exit_code == 0
    assert "replayed / replay_regression" in result.stdout
    residual_path = out / "twin_residual_report.json"
    assert residual_path.exists()

    characterize = CliRunner().invoke(
        app,
        ["twin", "characterize-scope", str(residual_path), "--output", str(tmp_path / "char")],
    )
    assert characterize.exit_code == 1
    assert "Cannot characterize scope twin" in characterize.stdout


def test_twin_cli_characterizes_independent_parity_report(tmp_path) -> None:
    fixture = _fixture()
    fixture["classification"]["parity_mode"] = "independent_parity"
    fixture_path = write_replay_fixture(tmp_path / "fixture.json", _refresh_fixture_hash(fixture))
    residual_out = tmp_path / "residual"
    char_out = tmp_path / "characterized"

    residual = CliRunner().invoke(
        app,
        ["twin", "residual-from-replay", str(fixture_path), "--output", str(residual_out)],
    )
    assert residual.exit_code == 0

    characterized = CliRunner().invoke(
        app,
        [
            "twin",
            "characterize-scope",
            str(residual_out / "twin_residual_report.json"),
            "--output",
            str(char_out),
            "--check",
        ],
    )

    assert characterized.exit_code == 0
    assert "Characterized scope-twin evidence" in characterized.stdout
    assert (char_out / "characterized_scope_twin_evidence.json").exists()


def test_lamb_capture_residual_report_uses_measured_twin_validation_origin() -> None:
    from pytestlab.twin import residual_report_from_lamb_capture

    lamb_payload = {
        "lamb_url": "http://100.95.239.13:8000",
        "capture_waveform": True,
        "strict": True,
        "waveform_reductions": [
            {
                "model": "MXR404A",
                "waveform_sha256": "abc123",
                "preamble_sha256": "def456",
                "point_count": 8,
                "metrics": {
                    "rms": {"nominal": 1.0, "standard_uncertainty": 0.01, "unit": "V"},
                    "mean": {"nominal": 0.0, "standard_uncertainty": 0.01, "unit": "V"},
                },
            }
        ],
    }
    expected = {
        "rms": {"nominal": 1.001, "standard_uncertainty": 0.01, "unit": "V"},
        "mean": {"nominal": 0.0, "standard_uncertainty": 0.01, "unit": "V"},
    }

    report = residual_report_from_lamb_capture(
        lamb_payload,
        model="MXR404A",
        expected_metrics=expected,
        evidence_purpose="twin_validation",
    )

    assert report.passed
    assert report.data_origin == "measured"
    assert report.evidence_purpose == "twin_validation"
    assert report.context["waveform_sha256"] == "abc123"
    assert report.metrics[0].unit == "V"


def test_lamb_capture_residual_report_defaults_to_replay_regression() -> None:
    from pytestlab.twin import residual_report_from_lamb_capture

    report = residual_report_from_lamb_capture(
        {
            "waveform_reductions": [
                {
                    "model": "MXR404A",
                    "metrics": {
                        "rms": {"nominal": 1.0, "standard_uncertainty": 0.01, "unit": "V"},
                    },
                }
            ],
        },
        model="MXR404A",
        expected_metrics={"rms": {"nominal": 1.0, "standard_uncertainty": 0.01, "unit": "V"}},
    )

    assert report.data_origin == "measured"
    assert report.evidence_purpose == "replay_regression"


def test_residual_report_outside_declared_domain_is_not_pass() -> None:
    from pytestlab.twin import TwinDomain
    from pytestlab.twin import TwinIdentity
    from pytestlab.twin import TwinValidationStatus
    from pytestlab.twin import residual_metric
    from pytestlab.twin.residuals import ResidualReport

    identity = TwinIdentity(model="MXR404A")
    domain = TwinDomain(quantities=("rms",), amplitude_v=(0.1, 1.0))
    report = ResidualReport.build(
        twin_identity=identity,
        domain=domain,
        metrics=[
            residual_metric(
                "rms",
                hardware_nominal=1.0,
                twin_nominal=1.001,
                hardware_u=0.01,
                twin_u=0.01,
            )
        ],
        context={"amplitude_v": 5.0},
    )

    assert report.status is TwinValidationStatus.OUT_OF_DOMAIN
    assert not report.supports_characterized_twin


def test_characterized_scope_twin_rejects_domain_widening() -> None:
    identity = TwinIdentity(model="MXR404A", serial_hash="sha256:redacted")
    validated_domain = TwinDomain(quantities=("rms",), amplitude_v=(0.1, 1.0))
    wider_domain = TwinDomain(quantities=("rms",), amplitude_v=(0.0, 100.0))
    report = ResidualReport.build(
        twin_identity=identity,
        domain=validated_domain,
        metrics=[
            residual_metric(
                "rms",
                hardware_nominal=1.0,
                twin_nominal=1.001,
                hardware_u=0.01,
                twin_u=0.01,
            )
        ],
        context={"amplitude_v": 0.5},
    )

    with pytest.raises(ValueError, match="domain must exactly match"):
        CharacterizedScopeTwin(
            identity=identity,
            domain=wider_domain,
            residual_report=report,
        )


def test_bounded_residual_domain_requires_context() -> None:
    identity = TwinIdentity(model="MXR404A")
    domain = TwinDomain(quantities=("rms",), amplitude_v=(0.1, 1.0))
    report = ResidualReport.build(
        twin_identity=identity,
        domain=domain,
        metrics=[
            residual_metric(
                "rms",
                hardware_nominal=1.0,
                twin_nominal=1.001,
                hardware_u=0.01,
                twin_u=0.01,
            )
        ],
    )

    assert report.status is TwinValidationStatus.INCOMPLETE
    assert report.context["missing_domain_context"] == ["amplitude_v"]


def test_twin_evidence_check_rejects_characterized_measurement_result_label(tmp_path) -> None:
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
    path = write_twin_evidence(tmp_path / "bad_label.json", evidence)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["data_origin"] = "measured"
    payload["evidence_purpose"] = "measurement_result"
    payload.pop("payload_sha256")
    import hashlib

    payload["payload_sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    with pytest.raises(TwinEvidenceError, match="characterized twin evidence requires"):
        check_twin_evidence(path)


def test_twin_evidence_build_rejects_separated_negation_overclaim() -> None:
    from pytestlab.twin import TwinFidelity
    from pytestlab.twin import TwinValidationEvidence

    identity = TwinIdentity(model="MXR404A")
    domain = TwinDomain(quantities=("rms",))

    with pytest.raises(ValueError, match="non-claim boundary"):
        TwinValidationEvidence.build(
            schema="pytestlab.twin.characterized_scope_twin.v1",
            twin_identity=identity,
            fidelity=TwinFidelity.CHARACTERIZED,
            status=TwinValidationStatus.PASS,
            domain=domain,
            metrics=[],
            data_origin="characterized_twin",
            evidence_purpose="twin_validation",
            claim="This is not merely advisory; it is a characterized hardware twin.",
        )


def test_twin_evidence_check_rejects_separated_negation_overclaim(tmp_path) -> None:
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
    path = write_twin_evidence(tmp_path / "bad_claim.json", evidence)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["claim"] = "This is not merely advisory; it is a characterized hardware twin."
    payload.pop("payload_sha256")
    payload["payload_sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    with pytest.raises(TwinEvidenceError, match="non-claim boundary"):
        check_twin_evidence(path)
