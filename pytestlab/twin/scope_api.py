"""Ergonomic oscilloscope twin helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pytestlab.validation.scope_twin import ScopeTwinValidationReport

from .base import TwinDomain
from .base import TwinIdentity
from .residuals import ResidualReport
from .scope import CharacterizedScopeTwin
from .scope import ScopeValidationOracle


@dataclass(frozen=True)
class OscilloscopeTwinTools:
    """Low-burden twin entry point exposed as ``scope.twin``."""

    model: str
    profile_sha256: str | None = None

    def oracle(self) -> ScopeValidationOracle:
        """Return the built-in known-truth validation oracle."""

        return ScopeValidationOracle()

    def validate(
        self,
        output_dir: str | Path,
        *,
        kind: str = "oracle",
        mc_samples: int = 3000,
    ) -> ScopeTwinValidationReport:
        """Run a validation workflow without exposing internal twin plumbing.

        ``kind='oracle'`` validates PyTestLab's waveform algorithms against a
        deterministic synthetic truth. Characterized hardware validation is
        intentionally created through :meth:`characterized` with an explicit
        residual report so the API cannot accidentally overclaim.
        """

        if kind != "oracle":
            raise ValueError(
                "Only kind='oracle' is automatic. Use characterized(...) with a passing "
                "ResidualReport for physical-instrument twin claims."
            )
        return self.oracle().run(output_dir, mc_samples=mc_samples)

    def characterized(
        self,
        *,
        identity: TwinIdentity | None = None,
        domain: TwinDomain,
        residual_report: ResidualReport,
    ) -> CharacterizedScopeTwin:
        """Create a characterized scope twin from explicit residual evidence."""

        resolved_identity = identity or TwinIdentity(
            model=self.model,
            profile_sha256=self.profile_sha256,
        )
        return CharacterizedScopeTwin(
            identity=resolved_identity,
            domain=domain,
            residual_report=residual_report,
        )
