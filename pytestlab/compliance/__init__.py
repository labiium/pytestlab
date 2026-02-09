"""
Pytestlab Compliance Module

Provides cryptographic signing, audit trails, and timestamping for measurements
using a decorator-based approach that integrates cleanly with MeasurementSession.

Quick Start:
    from pytestlab import Session
    from pytestlab.compliance import ComplianceConfig

    # Configure compliance
    from pytestlab.compliance.paths import audit_db_path
    from pytestlab.compliance.paths import private_key_path

    config = ComplianceConfig(
        signing={"key_file": str(private_key_path("prod.pem"))},
        audit={"audit_db": str(audit_db_path())},
        timestamp={"authority": "https://freetsa.org/tsr"},
    )

    # Use with session - all measurements auto-wrapped
    with Session("experiment", compliance=config) as session:
        @session.measure
        def measure_voltage(dmm):
            return {"voltage": dmm.read_voltage()}

        exp = session.run()

Note: This module does NOT auto-initialize or monkey-patch.
Compliance must be explicitly configured per-session.
"""

from __future__ import annotations

# Import types from interfaces (single source of truth)
from .interfaces import (
    AuditEntry as AuditRecord,
    Signature,
    TimestampToken,
)
from .decorators import (
    CompliantResult,
    VerificationResult,
    audited,
    compliant,
    signed,
    timestamped,
)
from .session import (
    ComplianceConfig,
    create_compliant_session,
)

__all__ = [
    # Result types
    "CompliantResult",
    "Signature",
    "TimestampToken",
    "AuditRecord",
    "VerificationResult",
    # Decorators
    "signed",
    "audited",
    "timestamped",
    "compliant",
    # Session integration
    "ComplianceConfig",
    "create_compliant_session",
]

# IMPORTANT: No auto-initialization!
# Previous versions called initialize() on import which monkey-patched
# classes globally. This is removed - compliance is now opt-in per-session.

# If you need the old behavior temporarily, use:
#   from pytestlab.compliance.legacy import initialize
#   initialize()
# But this is deprecated and will be removed.
