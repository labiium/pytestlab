"""Digital-twin taxonomy and validation records for PyTestLab.

These records deliberately separate validation oracles (software known-truth
checks) from characterized twins of a physical instrument.  The distinction is a
scientific safety boundary: an oracle can validate algorithms without becoming a
claim about a specific hardware unit.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from enum import Enum
from typing import Any


class TwinFidelity(str, Enum):
    """Machine-readable fidelity level for twin-origin evidence."""

    IDEAL = "ideal"
    BEHAVIORAL = "behavioral"
    CALIBRATED_BEHAVIORAL = "calibrated_behavioral"
    CHARACTERIZED = "characterized"


class TwinValidationStatus(str, Enum):
    """Validation decision for a twin evidence artifact."""

    PASS = "pass"
    FAIL = "fail"
    OUT_OF_DOMAIN = "out_of_domain"
    INCOMPLETE = "incomplete"


@dataclass(frozen=True)
class TwinIdentity:
    """Identity of a twin or source instrument without exposing raw secrets."""

    model: str
    serial_hash: str | None = None
    firmware: str | None = None
    profile_sha256: str | None = None
    twin_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TwinDomain:
    """Declared domain over which a twin validation decision is meaningful."""

    quantities: tuple[str, ...]
    sample_rate_sps: tuple[float | None, float | None] = (None, None)
    amplitude_v: tuple[float | None, float | None] = (None, None)
    frequency_hz: tuple[float | None, float | None] = (None, None)
    notes: tuple[str, ...] = ()

    def contains(self, context: dict[str, float]) -> bool:
        return (
            _within(context.get("sample_rate_sps"), self.sample_rate_sps)
            and _within(context.get("amplitude_v"), self.amplitude_v)
            and _within(context.get("frequency_hz"), self.frequency_hz)
        )

    def missing_required_context(self, context: dict[str, float]) -> tuple[str, ...]:
        missing: list[str] = []
        for name, bounds in (
            ("sample_rate_sps", self.sample_rate_sps),
            ("amplitude_v", self.amplitude_v),
            ("frequency_hz", self.frequency_hz),
        ):
            if _is_bounded(bounds) and context.get(name) is None:
                missing.append(name)
        return tuple(missing)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TwinValidationEvidence:
    """Top-level validation evidence envelope."""

    schema: str
    generated_utc: str
    twin_identity: TwinIdentity
    fidelity: TwinFidelity
    status: TwinValidationStatus
    domain: TwinDomain
    metrics: list[dict[str, Any]]
    data_origin: str
    evidence_purpose: str
    claim: str
    payload_sha256: str | None = None

    @classmethod
    def build(
        cls,
        *,
        schema: str,
        twin_identity: TwinIdentity,
        fidelity: TwinFidelity,
        status: TwinValidationStatus,
        domain: TwinDomain,
        metrics: list[dict[str, Any]],
        data_origin: str,
        evidence_purpose: str,
        claim: str,
    ) -> TwinValidationEvidence:
        _validate_evidence_claim(
            fidelity=fidelity,
            status=status,
            data_origin=data_origin,
            evidence_purpose=evidence_purpose,
            claim=claim,
        )
        evidence = cls(
            schema=schema,
            generated_utc=datetime.now(UTC).isoformat(),
            twin_identity=twin_identity,
            fidelity=fidelity,
            status=status,
            domain=domain,
            metrics=metrics,
            data_origin=data_origin,
            evidence_purpose=evidence_purpose,
            claim=claim,
        )
        return evidence.with_payload_hash()

    @property
    def passed(self) -> bool:
        return self.status is TwinValidationStatus.PASS

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["fidelity"] = self.fidelity.value
        payload["status"] = self.status.value
        return payload

    def with_payload_hash(self) -> TwinValidationEvidence:
        payload = self.to_dict()
        payload.pop("payload_sha256", None)
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        return TwinValidationEvidence(
            schema=self.schema,
            generated_utc=self.generated_utc,
            twin_identity=self.twin_identity,
            fidelity=self.fidelity,
            status=self.status,
            domain=self.domain,
            metrics=self.metrics,
            data_origin=self.data_origin,
            evidence_purpose=self.evidence_purpose,
            claim=self.claim,
            payload_sha256=digest,
        )


class DigitalTwin:
    """Protocol-like base class for named, fidelity-labeled twins."""

    identity: TwinIdentity
    fidelity: TwinFidelity
    domain: TwinDomain

    def validation_evidence(self) -> TwinValidationEvidence:
        raise NotImplementedError


def _within(value: float | None, bounds: tuple[float | None, float | None]) -> bool:
    if value is None:
        return not _is_bounded(bounds)
    lower, upper = bounds
    if lower is not None and value < lower:
        return False
    if upper is not None and value > upper:
        return False
    return True


def _is_bounded(bounds: tuple[float | None, float | None]) -> bool:
    lower, upper = bounds
    return lower is not None or upper is not None


def _validate_evidence_claim(
    *,
    fidelity: TwinFidelity,
    status: TwinValidationStatus,
    data_origin: str,
    evidence_purpose: str,
    claim: str,
) -> None:
    allowed_origins = {
        "twin_oracle",
        "synthetic_known_truth",
        "characterized_twin",
        "simulated",
    }
    allowed_purposes = {"software_validation", "twin_validation", "simulation_study"}
    if data_origin not in allowed_origins:
        raise ValueError(f"invalid twin evidence data_origin={data_origin!r}")
    if evidence_purpose not in allowed_purposes:
        raise ValueError(f"invalid twin evidence evidence_purpose={evidence_purpose!r}")
    if fidelity is TwinFidelity.CHARACTERIZED:
        if data_origin != "characterized_twin" or evidence_purpose != "twin_validation":
            raise ValueError(
                "characterized twin evidence requires data_origin='characterized_twin' "
                "and evidence_purpose='twin_validation'"
            )
        if status is not TwinValidationStatus.PASS:
            raise ValueError("characterized twin evidence must have status=pass")
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
    if fidelity is TwinFidelity.IDEAL:
        if evidence_purpose != "software_validation":
            raise ValueError(
                "ideal validation oracles must use evidence_purpose='software_validation'"
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
        raise ValueError(f"{label} claim text must explicitly state its non-claim boundary")
