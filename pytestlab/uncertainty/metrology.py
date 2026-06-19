"""Metrology record models for report-grade uncertainty results.

These models do not make PyTestLab or a result ISO/IEC 17025 accredited. They
carry the records needed by a laboratory workflow: traceability references,
measurement-model metadata, provenance, and conformity decisions.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import socket
import subprocess
from datetime import UTC
from datetime import datetime
from typing import Any
from typing import Literal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

TraceabilitySource = Literal[
    "accredited_cal", "nmi", "manufacturer_spec", "type_a_measurement", "assumed"
]


class TraceabilityRef(BaseModel):
    """Reference to evidence supporting one influence quantity."""

    model_config = ConfigDict(extra="forbid")

    certificate_id: str | None = None
    issuing_lab: str | None = None
    accreditation_body: str | None = None
    accreditation_id: str | None = None
    calibration_date: str | None = None
    valid_until: str | None = None
    reference_standard: str | None = None
    cmc: float | None = None
    source: TraceabilitySource = "manufacturer_spec"

    @property
    def supports_si_traceability_claim(self) -> bool:
        """True only for sources that can support an SI-traceability claim."""

        return self.source in {"accredited_cal", "nmi"}


class CalibrationCertificate(BaseModel):
    """Structured calibration-certificate metadata usable by resolvers."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    certificate_id: str
    issuing_lab: str | None = None
    accreditation_body: str | None = None
    accreditation_id: str | None = None
    instrument_model: str | None = None
    instrument_serial: str | None = None
    calibration_date: str | None = None
    valid_until: str | None = None
    conditions: dict[str, Any] = Field(default_factory=dict)
    entries: list[dict[str, Any]] = Field(default_factory=list)


class CalibrationCertificateEntry(BaseModel):
    """One operating-point entry from a calibration certificate.

    The model intentionally allows optional match fields because calibration
    certificates vary by instrument family.  A resolver treats omitted fields as
    wildcards and only returns an entry when every provided field matches the
    measurement context.
    """

    model_config = ConfigDict(extra="allow")

    function: str | None = None
    channel: int | None = None
    range_value: float | None = None
    range_unit: str | None = None
    unit: str | None = None
    lower: float | None = None
    upper: float | None = None
    reference_standard: str | None = None
    cmc: float | None = None


class InputQuantityRecord(BaseModel):
    """Input quantity entry in a serialized measurement model."""

    model_config = ConfigDict(extra="forbid")

    name: str
    unit: str = ""
    distribution: str | None = None
    traceability_ref: TraceabilityRef | None = None
    dof: float | None = None


class CorrectionRecord(BaseModel):
    """Correction record, including zero-valued corrections."""

    model_config = ConfigDict(extra="forbid")

    name: str
    value: float
    u: float = 0.0
    basis: str | None = None


MeasurementMethod = Literal[
    "gum_first_order", "monte_carlo", "analytic_exact", "monte_carlo_required"
]


class MeasurementModel(BaseModel):
    """Machine-readable measurement model emitted with derived quantities."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    output_name: str
    output_unit: str = ""
    function: str
    inputs: list[InputQuantityRecord] = Field(default_factory=list)
    corrections: list[CorrectionRecord] = Field(default_factory=list)
    method: MeasurementMethod = "gum_first_order"
    linearization_note: str | None = None
    assumptions: list[str] = Field(default_factory=list)
    dof_method: str | None = None


class ResultProvenance(BaseModel):
    """Provenance and technical-record integrity metadata."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    created_utc: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z")
    )
    engine_version: str | None = None
    pytestlab_version: str | None = None
    numpy_version: str | None = None
    scipy_version: str | None = None
    input_data_sha256: str | None = None
    operator: str | None = None
    agent_id: str | None = None
    host: str | None = None
    validation_report_id: str | None = None
    provenance_complete: bool = False
    amendments: list[dict[str, Any]] = Field(default_factory=list)

    @classmethod
    def legacy_incomplete(cls) -> ResultProvenance:
        """Provenance marker for legacy records that predate report-grade metadata."""

        return cls(provenance_complete=False)

    @classmethod
    def current(
        cls,
        *,
        input_data: bytes | None = None,
        input_data_sha256: str | None = None,
        operator: str | None = None,
        agent_id: str | None = None,
        validation_report_id: str | None = None,
        provenance_complete: bool = False,
    ) -> ResultProvenance:
        """Build a current technical-record provenance snapshot.

        ``provenance_complete`` defaults to ``False`` deliberately: software can
        populate version/checksum fields, but report-grade completeness also
        depends on traceability, measurement-model and unit gates evaluated by
        :func:`report_grade_blockers`.
        """

        try:
            pytestlab_version = importlib.metadata.version("pytestlab")
        except Exception:
            pytestlab_version = None
        try:
            import numpy as np

            numpy_version = np.__version__
        except Exception:  # pragma: no cover - numpy is a core dependency
            numpy_version = None
        try:
            import scipy

            scipy_version = scipy.__version__
        except Exception:  # pragma: no cover - scipy is a core dependency now, but keep robust
            scipy_version = None
        if input_data is not None:
            input_data_sha256 = hashlib.sha256(input_data).hexdigest()
        return cls(
            engine_version="pytestlab-uncertainty-v1",
            pytestlab_version=pytestlab_version,
            numpy_version=numpy_version,
            scipy_version=scipy_version,
            input_data_sha256=input_data_sha256,
            operator=operator,
            agent_id=agent_id,
            host=socket.gethostname(),
            validation_report_id=validation_report_id,
            provenance_complete=provenance_complete,
        )


class ToleranceInterval(BaseModel):
    """Tolerance interval for conformity assessment."""

    model_config = ConfigDict(extra="forbid")

    lower: float | None = None
    upper: float | None = None
    unit: str = ""


class ConformityResult(BaseModel):
    """Conformity decision record; never a bare pass/fail bool."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    tolerance: ToleranceInterval
    decision_rule: dict[str, Any]
    measured: dict[str, float]
    decision: Literal["pass", "fail", "conditional_pass", "conditional_fail", "indeterminate"]
    measurand_prior_ref: str | None = None
    specific_risk: dict[str, float | None] = Field(
        default_factory=lambda: {"pfa": None, "pfr": None}
    )
    statement: str


REPORT_GRADE_TRACEABILITY_SOURCES = {"accredited_cal", "nmi"}


def current_git_sha(cwd: str | None = None) -> str | None:
    """Return the current git SHA when available without making it mandatory."""

    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=cwd, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return None


def traceability_ref_from_any(value: Any) -> TraceabilityRef | None:
    """Coerce stored traceability data into ``TraceabilityRef`` without breaking legacy reads."""

    if value is None or isinstance(value, TraceabilityRef):
        return value
    if isinstance(value, dict):
        return TraceabilityRef(**value)
    raise TypeError(f"Unsupported traceability reference: {type(value)!r}")


def provenance_from_any(value: Any) -> ResultProvenance:
    """Coerce provenance metadata, returning an incomplete marker for legacy data."""

    if isinstance(value, ResultProvenance):
        return value
    if isinstance(value, dict):
        try:
            return ResultProvenance(**value)
        except Exception:
            return ResultProvenance.legacy_incomplete()
    return ResultProvenance.legacy_incomplete()


def model_from_any(value: Any) -> MeasurementModel | None:
    if value is None or isinstance(value, MeasurementModel):
        return value
    if isinstance(value, dict):
        return MeasurementModel(**value)
    raise TypeError(f"Unsupported measurement model: {type(value)!r}")


def traceability_from_certificate_entry(
    certificate: CalibrationCertificate, entry: CalibrationCertificateEntry | dict[str, Any]
) -> TraceabilityRef:
    """Create a traceability reference from a certificate and one matched entry."""

    entry_model = (
        entry
        if isinstance(entry, CalibrationCertificateEntry)
        else CalibrationCertificateEntry(**entry)
    )
    return TraceabilityRef(
        certificate_id=certificate.certificate_id,
        issuing_lab=certificate.issuing_lab,
        accreditation_body=certificate.accreditation_body,
        accreditation_id=certificate.accreditation_id,
        calibration_date=certificate.calibration_date,
        valid_until=certificate.valid_until,
        reference_standard=entry_model.reference_standard or certificate.instrument_model,
        cmc=entry_model.cmc,
        source="accredited_cal" if certificate.accreditation_id else "nmi",
    )


def resolve_traceability_ref(
    certificates: list[CalibrationCertificate] | None,
    *,
    function: str | None = None,
    channel: int | None = None,
    range_value: float | None = None,
    unit: str | None = None,
) -> TraceabilityRef | None:
    """Resolve an operating-point traceability reference from certificate metadata.

    Omitted entry fields are wildcards.  Provided entry fields must match the
    context exactly, except numeric ranges may match via ``lower``/``upper`` or
    approximate ``range_value`` equality.
    """

    for certificate in certificates or []:
        for raw_entry in certificate.entries:
            entry = CalibrationCertificateEntry(**raw_entry)
            if entry.function is not None and function is not None and entry.function != function:
                continue
            if entry.channel is not None and channel is not None and entry.channel != channel:
                continue
            entry_unit = entry.unit or entry.range_unit
            if entry_unit is not None and unit is not None and entry_unit != unit:
                continue
            if range_value is not None:
                if entry.range_value is not None and abs(
                    entry.range_value - range_value
                ) > 1e-12 * max(1.0, abs(range_value)):
                    continue
                if entry.lower is not None and range_value < entry.lower:
                    continue
                if entry.upper is not None and range_value > entry.upper:
                    continue
            return traceability_from_certificate_entry(certificate, entry)
    return None


def _iter_traceability_refs(value: Any):
    registry = getattr(value, "registry", None)
    if registry is None:
        return
    grad = getattr(value, "grad", None)
    if isinstance(grad, dict):
        for uid in grad:
            atom = registry.atoms.get(uid)
            if atom is not None:
                yield atom.traceability, atom.label
        return
    sensitivities = getattr(value, "atom_sensitivities", None)
    if isinstance(sensitivities, dict):
        for uid in sensitivities:
            atom = registry.atoms.get(uid)
            if atom is not None:
                yield atom.traceability, atom.label


def report_grade_blockers(value: Any) -> list[str]:
    """Return reasons a Quantity/QuantityArray must not be treated as report-grade."""

    blockers: list[str] = []
    provenance = getattr(value, "provenance", None)
    if not isinstance(provenance, ResultProvenance) or not provenance.provenance_complete:
        blockers.append("provenance_complete is false or missing")
    if getattr(value, "measurement_model", None) is None:
        blockers.append("measurement_model is missing")
    dof_method = getattr(value, "dof_method", None) or getattr(
        getattr(value, "measurement_model", None), "dof_method", None
    )
    if isinstance(dof_method, str) and (
        "required" in dof_method or "unresolved" in dof_method or "placeholder" in dof_method
    ):
        blockers.append(f"degrees-of-freedom method is unresolved: {dof_method}")
    try:
        from .units import is_unit_resolvable

        if not is_unit_resolvable(getattr(value, "unit", "")):
            blockers.append(f"unit {getattr(value, 'unit', '')!r} is not D-SI-resolvable")
    except Exception as exc:  # pragma: no cover - defensive
        blockers.append(f"unit resolution failed: {exc}")
    saw_traceability = False
    for traceability, label in _iter_traceability_refs(value) or []:
        saw_traceability = True
        if traceability is None:
            blockers.append(f"input {label!r} has no traceability reference")
        elif traceability.source not in REPORT_GRADE_TRACEABILITY_SOURCES:
            blockers.append(
                f"input {label!r} traceability source {traceability.source!r} cannot support SI traceability claim"
            )
    if not saw_traceability and (
        getattr(value, "grad", None) or getattr(value, "atom_sensitivities", None)
    ):
        blockers.append("no traceability references found for uncertainty inputs")
    return blockers


def is_report_grade(value: Any) -> bool:
    """True only when no conservative report-grade blockers are present."""

    return not report_grade_blockers(value)
