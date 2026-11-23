"""Oscilloscope twin taxonomy: validation oracle vs characterized twin."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pytestlab.validation.scope_twin import ScopeTwinValidationReport
from pytestlab.validation.scope_twin import run_scope_twin_known_truth_validation

from .base import DigitalTwin
from .base import TwinDomain
from .base import TwinFidelity
from .base import TwinIdentity
from .base import TwinValidationEvidence
from .base import TwinValidationStatus
from .residuals import ResidualReport


@dataclass(frozen=True)
class ScopeValidationOracle(DigitalTwin):
    """Synthetic known-truth oscilloscope oracle for validating PyTestLab algorithms."""

    identity: TwinIdentity = TwinIdentity(model="ScopeValidationOracle", twin_id="known_truth")
    fidelity: TwinFidelity = TwinFidelity.IDEAL
    domain: TwinDomain = TwinDomain(
        quantities=("mean", "rms", "peak_to_peak"),
        sample_rate_sps=(1_000_000.0, 1_000_000.0),
        amplitude_v=(0.75, 0.75),
        frequency_hz=(15_625.0, 15_625.0),
        notes=("deterministic synthetic known-truth oracle",),
    )

    def run(self, output_dir: str | Path, *, mc_samples: int = 3000) -> ScopeTwinValidationReport:
        return run_scope_twin_known_truth_validation(output_dir, mc_samples=mc_samples)

    def validation_evidence(self) -> TwinValidationEvidence:
        return TwinValidationEvidence.build(
            schema="pytestlab.twin.scope_validation_oracle.v1",
            twin_identity=self.identity,
            fidelity=self.fidelity,
            status=TwinValidationStatus.INCOMPLETE,
            domain=self.domain,
            metrics=[],
            data_origin="twin_oracle",
            evidence_purpose="software_validation",
            claim="Synthetic oracle validates waveform algorithms only; it is not a characterized hardware twin.",
        )


@dataclass(frozen=True)
class CharacterizedScopeTwin(DigitalTwin):
    """A scope twin fitted/validated against a declared physical instrument domain."""

    identity: TwinIdentity
    domain: TwinDomain
    residual_report: ResidualReport
    fidelity: TwinFidelity = TwinFidelity.CHARACTERIZED

    def __post_init__(self) -> None:
        if self.fidelity is not TwinFidelity.CHARACTERIZED:
            raise ValueError("CharacterizedScopeTwin requires fidelity=CHARACTERIZED")
        if self.residual_report.status is not TwinValidationStatus.PASS:
            raise ValueError("CharacterizedScopeTwin requires a passing residual report")
        if self.residual_report.evidence_purpose != "twin_validation":
            raise ValueError(
                "CharacterizedScopeTwin requires independent twin_validation residual evidence"
            )
        if self.residual_report.twin_identity != self.identity:
            raise ValueError("residual report identity must match the characterized twin")
        if self.domain != self.residual_report.domain:
            raise ValueError(
                "CharacterizedScopeTwin domain must exactly match the residual report domain"
            )

    def validation_evidence(self) -> TwinValidationEvidence:
        return TwinValidationEvidence.build(
            schema="pytestlab.twin.characterized_scope_twin.v1",
            twin_identity=self.identity,
            fidelity=self.fidelity,
            status=self.residual_report.status,
            domain=self.domain,
            metrics=[metric.to_dict() for metric in self.residual_report.metrics],
            data_origin="characterized_twin",
            evidence_purpose="twin_validation",
            claim="Characterized scope twin evidence is valid only inside the declared domain and is not a measured calibration result.",
        )
