"""Residual metrics and validation reports for characterized digital twins."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from pathlib import Path
from typing import Any

from pytestlab.validation.hardware_parity import ParityRow
from pytestlab.validation.hardware_parity import compare_replay_to_expected
from pytestlab.validation.hardware_parity import load_replay_fixture

from .base import TwinDomain
from .base import TwinIdentity
from .base import TwinValidationStatus


@dataclass(frozen=True)
class ResidualMetric:
    """One hardware-vs-twin residual with uncertainty-aware acceptance."""

    name: str
    hardware_nominal: float
    twin_nominal: float
    residual: float
    combined_standard_uncertainty: float
    coverage_factor: float
    passed: bool
    detail: str
    unit: str | None = None
    layer: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ResidualMetric:
        return cls(
            name=str(payload["name"]),
            hardware_nominal=float(payload["hardware_nominal"]),
            twin_nominal=float(payload["twin_nominal"]),
            residual=float(payload["residual"]),
            combined_standard_uncertainty=float(payload["combined_standard_uncertainty"]),
            coverage_factor=float(payload["coverage_factor"]),
            passed=bool(payload["passed"]),
            detail=str(payload.get("detail", "")),
            unit=str(payload["unit"]) if payload.get("unit") is not None else None,
            layer=str(payload["layer"]) if payload.get("layer") is not None else None,
        )


@dataclass(frozen=True)
class ResidualReport:
    """Tamper-checkable residual report for a twin-validation or replay-regression claim."""

    schema: str
    generated_utc: str
    twin_identity: TwinIdentity
    domain: TwinDomain
    status: TwinValidationStatus
    metrics: list[ResidualMetric]
    context: dict[str, Any]
    data_origin: str = "replayed"
    evidence_purpose: str = "twin_validation"
    claim: str = (
        "Residual report compares replayed/measured hardware metrics against an expected "
        "or twin prediction inside the declared domain. It is not a calibration certificate."
    )
    payload_sha256: str | None = None

    @classmethod
    def build(
        cls,
        *,
        twin_identity: TwinIdentity,
        domain: TwinDomain,
        metrics: list[ResidualMetric],
        context: dict[str, Any] | None = None,
        data_origin: str = "replayed",
        evidence_purpose: str = "twin_validation",
        claim: str | None = None,
    ) -> ResidualReport:
        _validate_residual_claim(data_origin=data_origin, evidence_purpose=evidence_purpose)
        context = dict(context or {})
        numeric_context = {k: float(v) for k, v in context.items() if _is_number(v)}
        in_domain = domain.contains(numeric_context)
        missing_context = domain.missing_required_context(numeric_context)
        if missing_context:
            context["missing_domain_context"] = list(missing_context)
        status = (
            TwinValidationStatus.INCOMPLETE
            if not metrics or missing_context
            else TwinValidationStatus.PASS
            if all(metric.passed for metric in metrics) and in_domain
            else TwinValidationStatus.OUT_OF_DOMAIN
            if not in_domain
            else TwinValidationStatus.FAIL
        )
        report = cls(
            schema="pytestlab.twin.residual_report.v1",
            generated_utc=datetime.now(UTC).isoformat(),
            twin_identity=twin_identity,
            domain=domain,
            status=status,
            metrics=metrics,
            context=context,
            data_origin=data_origin,
            evidence_purpose=evidence_purpose,
            claim=claim
            or (
                "Independent hardware-vs-twin residual validation evidence; valid only inside "
                "the declared domain and not a measured calibration result."
                if evidence_purpose == "twin_validation"
                else "Replay fixture regression evidence; this checks fixture/decode stability and "
                "must not be used as characterized-hardware twin validation."
            ),
        )
        return report.with_payload_hash()

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ResidualReport:
        identity_payload = payload["twin_identity"]
        domain_payload = payload["domain"]
        report = cls(
            schema=str(payload["schema"]),
            generated_utc=str(payload["generated_utc"]),
            twin_identity=TwinIdentity(**identity_payload),
            domain=TwinDomain(
                quantities=tuple(domain_payload["quantities"]),
                sample_rate_sps=tuple(domain_payload.get("sample_rate_sps", (None, None))),
                amplitude_v=tuple(domain_payload.get("amplitude_v", (None, None))),
                frequency_hz=tuple(domain_payload.get("frequency_hz", (None, None))),
                notes=tuple(domain_payload.get("notes", ())),
            ),
            status=TwinValidationStatus(str(payload["status"])),
            metrics=[ResidualMetric.from_dict(item) for item in payload.get("metrics", [])],
            context=dict(payload.get("context", {})),
            data_origin=str(payload.get("data_origin", "replayed")),
            evidence_purpose=str(payload.get("evidence_purpose", "twin_validation")),
            claim=str(payload.get("claim", "")),
            payload_sha256=payload.get("payload_sha256"),
        )
        return report

    @property
    def passed(self) -> bool:
        return self.status is TwinValidationStatus.PASS

    @property
    def supports_characterized_twin(self) -> bool:
        return (
            self.passed
            and self.evidence_purpose == "twin_validation"
            and self.data_origin in {"measured", "replayed"}
            and not self.context.get("missing_domain_context")
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        return payload

    def with_payload_hash(self) -> ResidualReport:
        payload = self.to_dict()
        payload.pop("payload_sha256", None)
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        return ResidualReport(
            schema=self.schema,
            generated_utc=self.generated_utc,
            twin_identity=self.twin_identity,
            domain=self.domain,
            status=self.status,
            metrics=self.metrics,
            context=self.context,
            data_origin=self.data_origin,
            evidence_purpose=self.evidence_purpose,
            claim=self.claim,
            payload_sha256=digest,
        )


def residual_metric(
    name: str,
    *,
    hardware_nominal: float,
    twin_nominal: float,
    hardware_u: float,
    twin_u: float,
    coverage_factor: float = 2.0,
    unit: str | None = None,
) -> ResidualMetric:
    if coverage_factor <= 0.0:
        raise ValueError("coverage_factor must be positive")
    combined_u = math.hypot(float(hardware_u), float(twin_u))
    residual = float(hardware_nominal) - float(twin_nominal)
    passed = abs(residual) <= coverage_factor * combined_u if combined_u > 0.0 else residual == 0.0
    return ResidualMetric(
        name=name,
        hardware_nominal=float(hardware_nominal),
        twin_nominal=float(twin_nominal),
        residual=residual,
        combined_standard_uncertainty=combined_u,
        coverage_factor=coverage_factor,
        passed=passed,
        detail="within combined uncertainty" if passed else "outside combined uncertainty",
        unit=unit,
    )


def residual_report_from_parity_rows(
    *,
    twin_identity: TwinIdentity,
    domain: TwinDomain,
    rows: list[ParityRow],
    context: dict[str, Any] | None = None,
    data_origin: str = "replayed",
    evidence_purpose: str = "replay_regression",
) -> ResidualReport:
    """Convert replay/hardware parity rows into a residual-report artifact."""

    metrics = [
        ResidualMetric(
            name=row.name,
            hardware_nominal=row.hardware_nominal,
            twin_nominal=row.expected_nominal,
            residual=row.difference,
            combined_standard_uncertainty=row.combined_standard_uncertainty,
            coverage_factor=row.coverage_factor,
            passed=row.passed,
            detail=row.detail,
            layer=row.layer,
        )
        for row in rows
    ]
    return ResidualReport.build(
        twin_identity=twin_identity,
        domain=domain,
        metrics=metrics,
        context=context,
        data_origin=data_origin,
        evidence_purpose=evidence_purpose,
    )


def residual_report_from_replay_fixture(
    fixture: str | Path | dict[str, Any],
    *,
    identity: TwinIdentity | None = None,
    domain: TwinDomain | None = None,
    coverage_factor: float = 2.0,
    profile_sha256: str | None = None,
    context: dict[str, Any] | None = None,
    evidence_purpose: str = "twin_validation",
) -> ResidualReport:
    """Build a residual report from a replay fixture without overclaiming its purpose.

    Fixtures classified as ``fixture_integrity`` become ``replay_regression`` evidence:
    useful for CI and decoder stability, but intentionally rejected by
    ``CharacterizedScopeTwin``.  Only fixtures explicitly classified as
    ``independent_parity`` become ``twin_validation`` evidence.
    """

    fixture_path: str | None = None
    if isinstance(fixture, str | Path):
        fixture_path = str(fixture)
        payload = load_replay_fixture(fixture)
    else:
        payload = fixture

    rows = compare_replay_to_expected(payload, coverage_factor=coverage_factor)
    classification = payload.get("classification", {})
    if not isinstance(classification, dict):
        classification = {}
    parity_mode = str(classification.get("parity_mode", "fixture_integrity"))
    evidence_purpose = (
        "twin_validation" if parity_mode == "independent_parity" else "replay_regression"
    )
    resolved_identity = identity or _identity_from_fixture(payload, profile_sha256=profile_sha256)
    resolved_domain = domain or _domain_from_fixture(payload, rows)
    resolved_context = {
        "fixture_path": fixture_path,
        "fixture_payload_sha256": payload.get("payload_sha256"),
        "parity_mode": parity_mode,
        "expected_source": classification.get("expected_source"),
        "stimulus_known": classification.get("stimulus_known"),
        "source": payload.get("source"),
        "model": payload.get("model"),
        "point_count": payload.get("point_count"),
        "waveform_sha256": payload.get("waveform_sha256"),
        "sample_rate_sps": _sample_rate_from_fixture(payload),
        "command_transcript_sha256": payload.get("command_transcript_sha256")
        or command_transcript_sha256(payload.get("log", [])),
        "profile_sha256": profile_sha256 or _fixture_identity(payload).get("profile_sha256"),
        "data_origin": "replayed",
        "evidence_purpose": evidence_purpose,
        "claim_boundary": (
            "independent parity supports characterized-twin validation inside the declared domain"
            if evidence_purpose == "twin_validation"
            else "fixture integrity/replay regression; not characterized-twin validation"
        ),
    }
    if context:
        resolved_context.update(context)
    return residual_report_from_parity_rows(
        twin_identity=resolved_identity,
        domain=resolved_domain,
        rows=rows,
        context=resolved_context,
        data_origin="replayed",
        evidence_purpose=evidence_purpose,
    )


def residual_report_from_lamb_capture(
    lamb_report: str | Path | dict[str, Any],
    *,
    model: str,
    expected_metrics: dict[str, Any],
    identity: TwinIdentity | None = None,
    domain: TwinDomain | None = None,
    coverage_factor: float = 2.0,
    profile_sha256: str | None = None,
    context: dict[str, Any] | None = None,
    evidence_purpose: str = "replay_regression",
) -> ResidualReport:
    """Build a residual report from a LAMB waveform-capture report.

    The LAMB report supplies measured hardware reductions; the caller supplies
    the independent expected/twin metrics.  This keeps live-hardware evidence
    separate from simulator truth and prevents self-consistency overclaiming.
    """

    if coverage_factor <= 0.0:
        raise ValueError("coverage_factor must be positive")
    payload = (
        json.loads(Path(lamb_report).read_text(encoding="utf-8"))
        if isinstance(lamb_report, str | Path)
        else lamb_report
    )
    reduction = _find_lamb_reduction(payload, model)
    metrics_payload = reduction.get("metrics", {})
    if not isinstance(metrics_payload, dict):
        raise ValueError("LAMB waveform reduction metrics must be a mapping")
    metrics: list[ResidualMetric] = []
    for name, hw_metric in metrics_payload.items():
        if not isinstance(hw_metric, dict) or name not in expected_metrics:
            continue
        expected = expected_metrics[name]
        if not isinstance(expected, dict):
            continue
        hw_nominal = float(hw_metric["nominal"])
        twin_nominal = float(expected["nominal"])
        hw_u = float(hw_metric.get("standard_uncertainty", 0.0))
        twin_u = float(expected.get("standard_uncertainty", 0.0))
        metrics.append(
            residual_metric(
                str(name),
                hardware_nominal=hw_nominal,
                twin_nominal=twin_nominal,
                hardware_u=hw_u,
                twin_u=twin_u,
                coverage_factor=coverage_factor,
                unit=str(hw_metric["unit"]) if hw_metric.get("unit") is not None else None,
            )
        )
    if not metrics:
        raise ValueError("no overlapping LAMB and expected metrics to compare")
    resolved_identity = identity or TwinIdentity(
        model=model,
        profile_sha256=profile_sha256,
    )
    resolved_domain = domain or TwinDomain(
        quantities=tuple(metric.name for metric in metrics),
        notes=(
            f"model={model}",
            "live LAMB waveform capture compared against caller-supplied expected/twin metrics",
        ),
    )
    resolved_context = {
        "lamb_url": payload.get("lamb_url"),
        "capture_waveform": payload.get("capture_waveform"),
        "strict": payload.get("strict"),
        "model": model,
        "waveform_sha256": reduction.get("waveform_sha256"),
        "preamble_sha256": reduction.get("preamble_sha256"),
        "point_count": reduction.get("point_count"),
        "profile_sha256": profile_sha256,
        "data_origin": "measured",
        "evidence_purpose": evidence_purpose,
        "claim_boundary": (
            "live LAMB hardware residual validation; not a calibration certificate"
            if evidence_purpose == "twin_validation"
            else "live LAMB self-consistency residual evidence; not characterized-twin validation"
        ),
    }
    if context:
        resolved_context.update(context)
    return ResidualReport.build(
        twin_identity=resolved_identity,
        domain=resolved_domain,
        metrics=metrics,
        context=resolved_context,
        data_origin="measured",
        evidence_purpose=evidence_purpose,
        claim=(
            "Live LAMB hardware-vs-twin residual validation evidence; valid only inside "
            "the declared domain and not a measured calibration result."
            if evidence_purpose == "twin_validation"
            else "Live LAMB self-consistency residual evidence for hardware capture/reduction "
            "regression; not characterized-twin validation."
        ),
    )


def _find_lamb_reduction(payload: dict[str, Any], model: str) -> dict[str, Any]:
    reductions = payload.get("waveform_reductions", [])
    if not isinstance(reductions, list):
        raise ValueError("LAMB report waveform_reductions must be a list")
    for reduction in reductions:
        if isinstance(reduction, dict) and str(reduction.get("model", "")).upper() == model.upper():
            return reduction
    raise ValueError(f"LAMB report has no waveform reduction for model {model}")


def command_transcript_sha256(log: Any) -> str:
    """Hash a SCPI transcript using metadata and response hashes, not raw secrets."""

    entries = log if isinstance(log, list) else []
    normalized: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        normalized.append(
            {
                "type": entry.get("type"),
                "command": entry.get("command"),
                "response": entry.get("response"),
                "response_encoding": entry.get("response_encoding"),
                "response_sha256": entry.get("response_sha256"),
            }
        )
    return hashlib.sha256(
        json.dumps(normalized, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def identity_from_idn(
    idn: str,
    *,
    model_hint: str | None = None,
    profile_sha256: str | None = None,
) -> TwinIdentity:
    """Create a twin identity from a SCPI ``*IDN?`` response."""

    parts = [part.strip() for part in idn.split(",")]
    model = model_hint or (parts[1] if len(parts) > 1 and parts[1] else "unknown")
    serial = parts[2] if len(parts) > 2 and parts[2] else None
    firmware = parts[3] if len(parts) > 3 and parts[3] else None
    return TwinIdentity(
        model=model,
        serial_number=serial,
        firmware=firmware,
        profile_sha256=profile_sha256,
    )


def _identity_from_fixture(payload: dict[str, Any], *, profile_sha256: str | None) -> TwinIdentity:
    identity_payload = _fixture_identity(payload)
    if identity_payload:
        return TwinIdentity(
            model=str(identity_payload.get("model") or payload.get("model") or "unknown"),
            serial_number=(
                str(identity_payload["serial_number"])
                if identity_payload.get("serial_number") is not None
                else None
            ),
            firmware=(
                str(identity_payload["firmware"])
                if identity_payload.get("firmware") is not None
                else None
            ),
            profile_sha256=profile_sha256
            or (
                str(identity_payload["profile_sha256"])
                if identity_payload.get("profile_sha256") is not None
                else None
            ),
            twin_id=(
                str(identity_payload["twin_id"])
                if identity_payload.get("twin_id") is not None
                else None
            ),
        )
    idn = _find_log_response(payload.get("log", []), "*IDN?")
    return identity_from_idn(
        str(idn or ""),
        model_hint=str(payload.get("model") or "unknown"),
        profile_sha256=profile_sha256,
    )


def _fixture_identity(payload: dict[str, Any]) -> dict[str, Any]:
    identity = payload.get("instrument_identity")
    return identity if isinstance(identity, dict) else {}


def _domain_from_fixture(payload: dict[str, Any], rows: list[ParityRow]) -> TwinDomain:
    sample_rate = _sample_rate_from_fixture(payload)
    bounds = (sample_rate, sample_rate) if sample_rate is not None else (None, None)
    classification = payload.get("classification", {})
    parity_mode = classification.get("parity_mode") if isinstance(classification, dict) else None
    return TwinDomain(
        quantities=tuple(row.name for row in rows),
        sample_rate_sps=bounds,
        notes=(
            f"model={payload.get('model', 'unknown')}",
            f"parity_mode={parity_mode or 'fixture_integrity'}",
            "domain is fixture-derived unless the caller supplies a broader characterized domain",
        ),
    )


def _sample_rate_from_fixture(payload: dict[str, Any]) -> float | None:
    response = _find_log_response(payload.get("log", []), ":ACQuire:SRATe:ANALog?")
    if response is None:
        return None
    try:
        value = float(str(response))
    except ValueError:
        return None
    return value if math.isfinite(value) and value > 0 else None


def _find_log_response(log: Any, command: str) -> str | None:
    entries = log if isinstance(log, list) else []
    for entry in entries:
        if isinstance(entry, dict) and entry.get("command") == command:
            response = entry.get("response")
            if isinstance(response, str):
                return response
    return None


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and math.isfinite(float(value))


def _validate_residual_claim(*, data_origin: str, evidence_purpose: str) -> None:
    if data_origin not in {"measured", "replayed"}:
        raise ValueError("residual report data_origin must be measured or replayed")
    if evidence_purpose not in {"twin_validation", "replay_regression"}:
        raise ValueError(
            "residual report evidence_purpose must be twin_validation or replay_regression"
        )
