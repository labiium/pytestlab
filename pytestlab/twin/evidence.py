"""Read/write helpers for digital-twin evidence artifacts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .base import TwinFidelity
from .base import TwinValidationEvidence
from .base import TwinValidationStatus
from .residuals import ResidualReport


class TwinEvidenceError(RuntimeError):
    """Raised when a twin evidence artifact is missing or tampered."""


def write_twin_evidence(path: str | Path, evidence: TwinValidationEvidence) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(evidence.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    return out


def check_twin_evidence(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    _check_payload_hash(payload, kind="twin evidence")
    _check_twin_claim_semantics(payload)
    return payload


def write_residual_report(path: str | Path, report: ResidualReport) -> Path:
    """Write a tamper-checkable residual report."""

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    return out


def load_residual_report(path: str | Path) -> ResidualReport:
    """Load and hash-check a residual report as typed objects."""

    payload = check_residual_report(path)
    return ResidualReport.from_dict(payload)


def check_residual_report(path: str | Path) -> dict[str, Any]:
    """Check a residual-report JSON artifact for tampering and required labels."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    _check_payload_hash(payload, kind="residual report")
    if payload.get("schema") != "pytestlab.twin.residual_report.v1":
        raise TwinEvidenceError("unsupported residual report schema")
    if payload.get("data_origin") not in {"measured", "replayed"}:
        raise TwinEvidenceError("residual report data_origin must be measured or replayed")
    if payload.get("evidence_purpose") not in {"twin_validation", "replay_regression"}:
        raise TwinEvidenceError(
            "residual report evidence_purpose must be twin_validation or replay_regression"
        )
    if payload.get("evidence_purpose") == "twin_validation" and payload.get("status") != "pass":
        raise TwinEvidenceError("twin-validation residual report must have status=pass")
    return payload


def _check_payload_hash(payload: dict[str, Any], *, kind: str) -> None:
    recorded = payload.get("payload_sha256")
    if not isinstance(recorded, str):
        raise TwinEvidenceError(f"{kind} missing payload_sha256")
    actual_payload = {k: v for k, v in payload.items() if k != "payload_sha256"}
    actual = hashlib.sha256(
        json.dumps(actual_payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    if actual != recorded:
        raise TwinEvidenceError(f"{kind} payload hash mismatch: {actual} != {recorded}")


def _check_twin_claim_semantics(payload: dict[str, Any]) -> None:
    fidelity = payload.get("fidelity")
    status = payload.get("status")
    data_origin = payload.get("data_origin")
    evidence_purpose = payload.get("evidence_purpose")
    if fidelity not in {item.value for item in TwinFidelity}:
        raise TwinEvidenceError("twin evidence has invalid fidelity")
    if status not in {item.value for item in TwinValidationStatus}:
        raise TwinEvidenceError("twin evidence has invalid status")
    claim = str(payload.get("claim", ""))
    if fidelity == TwinFidelity.CHARACTERIZED.value:
        if status != TwinValidationStatus.PASS.value:
            raise TwinEvidenceError("characterized twin evidence must have status=pass")
        if data_origin != "characterized_twin" or evidence_purpose != "twin_validation":
            raise TwinEvidenceError(
                "characterized twin evidence requires data_origin=characterized_twin "
                "and evidence_purpose=twin_validation"
            )
        _require_claim_boundary_text(
            claim,
            phrases=(
                "not a measured calibration result",
                "not a calibration certificate",
                "not accreditation",
                "not a signed dcc",
            ),
            label="characterized twin",
        )
    if fidelity == TwinFidelity.IDEAL.value:
        if data_origin != "twin_oracle" or evidence_purpose != "software_validation":
            raise TwinEvidenceError(
                "ideal twin oracle evidence requires data_origin=twin_oracle "
                "and evidence_purpose=software_validation"
            )
        _require_claim_boundary_text(
            claim,
            phrases=(
                "not a characterized hardware twin",
                "not characterized hardware",
                "not a hardware twin",
            ),
            label="ideal twin oracle",
        )


def _require_claim_boundary_text(claim: str, *, phrases: tuple[str, ...], label: str) -> None:
    normalized = claim.casefold()
    if not any(phrase in normalized for phrase in phrases):
        raise TwinEvidenceError(f"{label} claim text must explicitly state its non-claim boundary")
