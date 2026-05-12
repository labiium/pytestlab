"""
Compliance-enabled session with pluggable and legacy configuration.

This module provides:
1. Pluggable interfaces for Signer, Auditor, Timestamper
2. Legacy dict-based configuration (backward compatible)
3. Auto-configuration with sensible defaults

Examples:
    # LEGACY: Dict-based (backward compatible)
    # Use explicit paths resolved by pytestlab
    from pytestlab.compliance.paths import private_key_path
    config = ComplianceConfig(signing={"key_file": str(private_key_path("prod.pem"))})

    # PLUGGABLE: Bring your own implementations
    config = ComplianceConfig(
        signer=MyYubiKeySigner(),
        auditor=MyBlockchainAudit()
    )

    # DEFAULT: Auto-configure (works out of box)
    config = ComplianceConfig()  # Auto-generates keys
"""

from __future__ import annotations

import pathlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC
from typing import TYPE_CHECKING
from typing import Any
from typing import cast

from .._log import get_logger

if TYPE_CHECKING:
    from .interfaces import Auditor
    from .interfaces import Signer
    from .interfaces import Timestamper

_LOG = get_logger("compliance.session")


def _callable_name(func: Callable) -> str:
    return getattr(func, "__name__", func.__class__.__name__)


@dataclass
class ComplianceConfig:
    """Configuration for compliance features.

    Supports three modes:

    1. PLUGGABLE MODE (Production):
       >>> config = ComplianceConfig(
       ...     signer=MyHSM(),
       ...     auditor=MyAudit()
       ... )

    2. LEGACY MODE (Backward compatible):
       >>> config = ComplianceConfig(
       ...     signing={"key_file": "keys/prod.pem"}
       ... )

    3. AUTO MODE (Default):
       >>> config = ComplianceConfig()  # Auto-generates everything

    Attributes:
        enabled: Master switch
        signer: Pluggable Signer implementation (overrides 'signing')
        auditor: Pluggable Auditor implementation (overrides 'audit')
        timestamper: Pluggable Timestamper implementation (overrides 'timestamp')
        signing: Legacy dict config for signing
        audit: Legacy dict config for audit
        timestamp: Legacy dict config for timestamp
        regulation: Regulation preset name
    """

    # Master switch
    enabled: bool = True

    # Pluggable implementations (take precedence over dict configs)
    signer: Signer | None = None
    auditor: Auditor | None = None
    timestamper: Timestamper | None = None

    # Legacy dict configurations (backward compatible)
    signing: dict[str, Any] | None = None
    audit: dict[str, Any] | None = None
    timestamp: dict[str, Any] | None = None

    # Regulation preset
    regulation: str | None = None

    def __post_init__(self):
        """Initialize implementations from configs if needed."""
        # Load regulation preset if specified
        if self.regulation:
            self._apply_regulation_preset()

        # Initialize pluggable implementations from legacy configs
        self._initialize_from_configs()

    def _apply_regulation_preset(self) -> None:
        """Apply regulation preset to configuration."""
        from .paths import audit_db_path
        from .paths import private_key_path

        fda_key = str(private_key_path("fda.pem"))
        iso_key = str(private_key_path("iso.pem"))
        gmp_key = str(private_key_path("gmp.pem"))

        fda_audit = str(audit_db_path("fda_audit.sqlite"))
        iso_audit = str(audit_db_path("iso_audit.sqlite"))
        gmp_audit = str(audit_db_path("gmp_audit.sqlite"))

        REGULATIONS = {
            "FDA_21CFR11": {
                "signing": {
                    "key_file": fda_key,
                    "algorithm": "ECDSA_P256",
                },
                "audit": {
                    "audit_db": fda_audit,
                    "include_params": True,
                },
                "timestamp": {
                    "authority": "https://freetsa.org/tsr",
                    "local_fallback": False,
                },
            },
            "ISO17025": {
                "signing": {
                    "key_file": iso_key,
                    "algorithm": "ECDSA_P256",
                },
                "audit": {
                    "audit_db": iso_audit,
                    "include_params": False,
                },
                "timestamp": {
                    "authority": None,
                    "local_fallback": True,
                },
            },
            "GMP": {
                "signing": {
                    "key_file": gmp_key,
                    "algorithm": "ECDSA_P256",
                },
                "audit": {
                    "audit_db": gmp_audit,
                    "include_params": True,
                },
                "timestamp": None,
            },
        }

        if self.regulation not in REGULATIONS:
            raise ValueError(
                f"Unknown regulation: {self.regulation}. Available: {list(REGULATIONS.keys())}"
            )

        preset = REGULATIONS[self.regulation]

        # Only apply if not explicitly overridden
        if self.signing is None and self.signer is None:
            self.signing = preset.get("signing")
        if self.audit is None and self.auditor is None:
            self.audit = preset.get("audit")
        if self.timestamp is None and self.timestamper is None:
            self.timestamp = preset.get("timestamp")

    def _initialize_from_configs(self) -> None:
        """Initialize pluggable implementations from legacy dict configs."""
        try:
            from .defaults import FileSystemSigner
            from .defaults import LocalTimestamper
            from .defaults import SQLiteAuditor
        except ImportError:
            # cryptography not installed, can't create defaults
            return

        # Create Signer from signing config
        if self.signer is None and self.signing:
            try:
                self.signer = FileSystemSigner(**self.signing)
                _LOG.debug("Initialized FileSystemSigner from config")
            except Exception as e:
                _LOG.warning(f"Failed to initialize signer: {e}")

        # Create Auditor from audit config
        if self.auditor is None and self.audit:
            try:
                self.auditor = SQLiteAuditor(**self.audit)
                _LOG.debug("Initialized SQLiteAuditor from config")
            except Exception as e:
                _LOG.warning(f"Failed to initialize auditor: {e}")

        # Create Timestamper from timestamp config
        if self.timestamper is None and self.timestamp:
            try:
                self.timestamper = LocalTimestamper(**self.timestamp)
                _LOG.debug("Initialized LocalTimestamper from config")
            except Exception as e:
                _LOG.warning(f"Failed to initialize timestamper: {e}")

    def create_compliance_wrapper(
        self, *, transparent: bool = True
    ) -> Callable[[Callable], Callable]:
        """Create a decorator that applies all configured compliance features.

        Returns:
            A decorator function that wraps measurement functions
        """

        def wrapper(func: Callable) -> Callable:
            wrapped = func

            # Apply in reverse order: timestamp -> audit -> sign
            if self.timestamper:
                _LOG.debug(f"Applying timestamper to {_callable_name(func)}")
                wrapped = _wrap_with_timestamper(wrapped, self.timestamper, transparent=transparent)

            if self.auditor:
                _LOG.debug(f"Applying auditor to {_callable_name(func)}")
                wrapped = _wrap_with_auditor(wrapped, self.auditor, transparent=transparent)

            if self.signer:
                _LOG.debug(f"Applying signer to {_callable_name(func)}")
                wrapped = _wrap_with_signer(wrapped, self.signer, transparent=transparent)

            return wrapped

        return wrapper

    @classmethod
    def from_preset(cls, name: str) -> ComplianceConfig:
        """Create config from named preset.

        Args:
            name: Preset name ("auto", "fda", "iso", "gmp")

        Returns:
            ComplianceConfig with preset values
        """
        if name == "auto":
            # Auto-configure with defaults
            return cls()
        elif name.upper() == "FDA_21CFR11" or name.lower() == "fda":
            return cls(regulation="FDA_21CFR11")
        elif name.upper() == "ISO17025" or name.lower() == "iso":
            return cls(regulation="ISO17025")
        elif name.upper() == "GMP" or name.lower() == "gmp":
            return cls(regulation="GMP")
        else:
            raise ValueError(f"Unknown preset: {name}")


# ============================================================================
# Wrapper Functions for Pluggable Interfaces
# ============================================================================


def _json_default(obj: Any):
    """Best-effort JSON default for canonicalization.

    Keeps signing/audit robust for numpy scalars/arrays, complex, Path, bytes.
    """
    try:
        import numpy as np

        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, np.generic):
            return obj.item()
    except Exception:
        pass

    if isinstance(obj, complex):
        return {"__complex__": [obj.real, obj.imag]}
    if isinstance(obj, pathlib.Path):
        return str(obj)
    if isinstance(obj, set | tuple):
        return list(obj)
    if isinstance(obj, bytes):
        import base64

        return {"__bytes__": base64.b64encode(obj).decode()}

    # If we got a CompliantResult, unwrap
    try:
        from .decorators import CompliantResult

        if isinstance(obj, CompliantResult):
            return obj.data
    except Exception:
        pass

    return str(obj)


def _canonical_json(obj: Any) -> str:
    import json

    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=_json_default)


def _wrap_with_signer(func: Callable, signer: Signer, *, transparent: bool) -> Callable:
    """Wrap function with signer implementation."""
    import hashlib
    from functools import wraps

    @wraps(func)
    def wrapper(*args, **kwargs):
        # Execute function
        result = func(*args, **kwargs)

        # Unwrap CompliantResult, normalize to dict
        from .decorators import CompliantResult

        if isinstance(result, CompliantResult):
            result_data = result.data
        else:
            result_data = result if isinstance(result, dict) else {"value": result}

        canonical = _canonical_json(result_data)
        data_hash = hashlib.sha256(canonical.encode()).digest()

        # Sign with pluggable signer
        signature = signer.sign(data_hash)

        if transparent:
            # Keep measurement contract intact; attach compliance metadata under a reserved key.
            result_data["__compliance_signature"] = signature.to_dict()
            return result_data

        from .decorators import CompliantResult

        return CompliantResult(data=result_data, signature=signature)

    return wrapper


def _wrap_with_auditor(func: Callable, auditor: Auditor, *, transparent: bool) -> Callable:
    """Wrap function with auditor implementation."""
    import hashlib
    from datetime import datetime
    from functools import wraps

    from .interfaces import AuditEntry

    @wraps(func)
    def wrapper(*args, **kwargs):
        timestamp = datetime.now(UTC).isoformat()

        try:
            # Execute function
            result = func(*args, **kwargs)

            # Handle CompliantResult from upstream
            from .decorators import CompliantResult

            if isinstance(result, CompliantResult):
                result_data = result.data
            else:
                result_data = result if isinstance(result, dict) else {"value": result}

            # Compute hash
            canonical = _canonical_json(result_data)
            result_hash = hashlib.sha256(canonical.encode()).hexdigest()

            # Create audit entry (using result_hash as expected by interface)
            entry = AuditEntry(
                event_type="MEASUREMENT",
                function_name=_callable_name(func),
                timestamp=timestamp,
                result_hash=result_hash,
                success=True,
                metadata={},
                error_message=None,
            )

            # Append to audit trail
            entry_id = auditor.append(entry)
            _LOG.debug(f"Audited {_callable_name(func)} as {entry_id}")

            if transparent:
                result_data["__compliance_audit_id"] = entry_id
                return result_data

            from .decorators import CompliantResult

            if isinstance(result, CompliantResult):
                result.audit_record = entry
                return result

            return CompliantResult(data=result_data, audit_record=entry)

        except Exception as e:
            # Log failure
            entry = AuditEntry(
                event_type="MEASUREMENT_FAILURE",
                function_name=_callable_name(func),
                timestamp=timestamp,
                result_hash="",
                success=False,
                metadata={},
                error_message=str(e),
            )
            auditor.append(entry)
            raise

    return wrapper


def _wrap_with_timestamper(
    func: Callable, timestamper: Timestamper, *, transparent: bool
) -> Callable:
    """Wrap function with timestamper implementation."""
    import hashlib
    from functools import wraps

    @wraps(func)
    def wrapper(*args, **kwargs):
        # Execute function
        result = func(*args, **kwargs)

        # Handle CompliantResult from upstream
        from .decorators import CompliantResult

        if isinstance(result, CompliantResult):
            result_data = result.data
        else:
            result_data = result if isinstance(result, dict) else {"value": result}

        # Compute hash and timestamp
        canonical = _canonical_json(result_data)
        data_hash = hashlib.sha256(canonical.encode()).hexdigest()

        token = timestamper.timestamp(data_hash)

        if transparent:
            result_data["__compliance_timestamp"] = token.to_dict()
            return result_data

        from .decorators import CompliantResult

        if isinstance(result, CompliantResult):
            result.timestamp_token = token
            return result

        return CompliantResult(data=result_data, timestamp_token=token)

    return wrapper


# ============================================================================
# Factory Function
# ============================================================================


def create_compliant_session(
    name: str,
    compliance: ComplianceConfig | dict[str, Any] | str = "auto",
    **kwargs,
):
    """Create a MeasurementSession with compliance enabled.

    This is a convenience wrapper around `pytestlab.measurements.session.MeasurementSession`.
    The core session already supports compliance; we avoid extra inheritance/mixins
    to keep the model simple and type-checker friendly.

    Args:
        name: Session name
        compliance: ComplianceConfig, dict of settings, or preset name ("auto", "fda", "iso", "gmp")
        **kwargs: Passed through to MeasurementSession
    """
    from ..measurements.session import MeasurementSession

    if isinstance(compliance, str):
        compliance = ComplianceConfig.from_preset(compliance)
    elif isinstance(compliance, dict):
        compliance = ComplianceConfig(**cast(dict[str, Any], compliance))

    return MeasurementSession(name, compliance=compliance, **kwargs)
