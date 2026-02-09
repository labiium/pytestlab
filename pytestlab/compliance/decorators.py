"""
Compliance decorators for pytestlab measurements.

These decorators provide cryptographic signing, audit trails, and timestamping
for measurement functions. They are explicit, composable, and testable.

Example:
    from pytestlab import Session
    from pytestlab.compliance import signed, audited, timestamped

    with Session("experiment") as session:
        @session.measure
        # Use resolved paths (see pytestlab.compliance.paths)
        @signed(key_file="/path/to/prod.pem")
        @audited(audit_db="/path/to/audit.sqlite")
        @timestamped(authority="https://freetsa.org/tsr")
        def measure_voltage(dmm):
            return {"voltage": dmm.read_voltage()}

        session.run()
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Callable

from .._log import get_logger
from .interfaces import (
    AuditEntry as AuditRecord,
    Signature,
    TimestampToken,
)

_LOG = get_logger("compliance.decorators")


# ============================================================================
# Result Types
# ============================================================================


@dataclass
class VerificationResult:
    """Result of compliance verification."""

    valid: bool
    signature_valid: bool | None = None
    timestamp_valid: bool | None = None
    audit_valid: bool | None = None
    issues: list[str] | None = None


@dataclass
class CompliantResult:
    """Enhanced measurement result with compliance metadata."""

    # Original data
    data: dict[str, Any]

    # Compliance metadata (optional based on decorators used)
    signature: Signature | None = None
    timestamp_token: TimestampToken | None = None
    audit_record: AuditRecord | None = None

    def verify(self, trust_anchor: Path | str | None = None) -> VerificationResult:
        """Verify this result's compliance data."""
        from .verification import verify_result

        return verify_result(self, trust_anchor)


# ============================================================================
# Helper Functions
# ============================================================================


def _canonicalize(data: dict[str, Any]) -> str:
    """Create canonical JSON representation for signing."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def _hash_result(data: dict[str, Any]) -> str:
    """Compute SHA-256 hash of result data."""
    canonical = _canonicalize(data)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _utc_now() -> str:
    """Get current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat()


# ============================================================================
# Decorators
# ============================================================================


def signed(
    *,
    key_file: str | Path | None = None,
    key_env_var: str | None = None,
    algorithm: str = "ECDSA_P256",
):
    """Decorator that cryptographically signs measurement results.

    Args:
        key_file: Path to private key file (PEM format)
        key_env_var: Environment variable containing private key
        algorithm: Signing algorithm (default: ECDSA with P-256 curve)

    Returns:
        Decorated function that returns CompliantResult with signature

    Example:
        @session.measure
        @signed(key_file="/path/to/prod.pem")
        def measure_voltage(dmm):
            return {"voltage": dmm.read_voltage()}
    """

    def decorator(func: Callable) -> Callable:
        # Load signer on decoration (fail fast if key invalid)
        signer = _load_signer(key_file, key_env_var, algorithm)

        @wraps(func)
        def wrapper(*args, **kwargs) -> CompliantResult:
            # Execute the measurement
            result_data = func(*args, **kwargs)

            # Ensure result is dict
            if not isinstance(result_data, dict):
                result_data = {"value": result_data}

            # Create canonical representation for signing
            canonical = _canonicalize(result_data)

            # Sign the result
            signature_value = signer.sign(canonical)

            # Create signature metadata
            signature = Signature(
                value=signature_value,
                algorithm=f"{algorithm}_SHA256",
                key_fingerprint=signer.fingerprint,
                timestamp=_utc_now(),
            )

            _LOG.debug(f"Signed result from {func.__name__} with key {signer.fingerprint[:16]}...")

            # Return compliant result
            return CompliantResult(data=result_data, signature=signature)

        return wrapper

    return decorator


def audited(
    *,
    audit_db: str | Path | None = None,
    include_params: bool = False,
    include_args: bool = False,
):
    """Decorator that logs measurement execution to audit trail.

    Args:
        audit_db: Path to SQLite audit database
        include_params: Whether to log parameter values
        include_args: Whether to log function arguments

    Returns:
        Decorated function that logs to audit trail

    Example:
        @session.measure
        @audited(audit_db="/path/to/audit.sqlite")
        def measure_voltage(dmm):
            return {"voltage": dmm.read_voltage()}
    """

    def decorator(func: Callable) -> Callable:
        audit_trail = _load_audit_trail(audit_db)

        @wraps(func)
        def wrapper(*args, **kwargs) -> CompliantResult | dict:
            # Create audit entry
            entry = AuditRecord(
                event_type="MEASUREMENT",
                function_name=func.__name__,
                timestamp=_utc_now(),
                result_hash="",  # Will update after execution
                success=False,
                error_message=None,
                metadata={},
            )

            try:
                # Execute the measurement
                result = func(*args, **kwargs)

                # Handle CompliantResult from upstream decorators
                if isinstance(result, CompliantResult):
                    result_data = result.data
                else:
                    result_data = result if isinstance(result, dict) else {"value": result}

                # Compute hash and update entry
                entry = AuditRecord(
                    event_type="MEASUREMENT",
                    function_name=func.__name__,
                    timestamp=entry.timestamp,
                    result_hash=_hash_result(result_data),
                    success=True,
                    error_message=None,
                    metadata={},
                )

                # Add to audit trail
                audit_trail.append(entry)

                _LOG.debug(f"Audited execution of {func.__name__}")

                # Return enhanced result if not already CompliantResult
                if isinstance(result, CompliantResult):
                    result.audit_record = entry
                    return result
                else:
                    return CompliantResult(data=result_data, audit_record=entry)

            except Exception as e:
                # Log failure
                entry = AuditRecord(
                    event_type="MEASUREMENT_FAILURE",
                    function_name=func.__name__,
                    timestamp=entry.timestamp,
                    result_hash="",
                    success=False,
                    error_message=str(e),
                    metadata={},
                )
                audit_trail.append(entry)
                raise

        return wrapper

    return decorator


def timestamped(
    *,
    authority: str | None = None,
    local_fallback: bool = True,
    hash_algorithm: str = "SHA256",
):
    """Decorator that adds TSA (Timestamp Authority) token.

    Args:
        authority: TSA URL (e.g., "https://freetsa.org/tsr")
        local_fallback: Whether to use local timestamp if TSA fails
        hash_algorithm: Hash algorithm for TSA request

    Returns:
        Decorated function with TSA timestamp

    Example:
        @session.measure
        @timestamped(authority="https://freetsa.org/tsr")
        def measure_voltage(dmm):
            return {"voltage": dmm.read_voltage()}
    """

    def decorator(func: Callable) -> Callable:
        tsa_client = _load_tsa(authority, local_fallback)

        @wraps(func)
        def wrapper(*args, **kwargs) -> CompliantResult | dict:
            # Execute the measurement
            result = func(*args, **kwargs)

            # Handle CompliantResult from upstream decorators
            if isinstance(result, CompliantResult):
                result_data = result.data
            else:
                result_data = result if isinstance(result, dict) else {"value": result}

            # Get timestamp from TSA
            try:
                token_value = tsa_client.timestamp(_hash_result(result_data))
                token = TimestampToken(
                    value=token_value,
                    authority=authority or "local",
                    algorithm=hash_algorithm,
                )
                _LOG.debug(f"Timestamped result from {func.__name__} via {token.authority}")
            except Exception as e:
                if local_fallback:
                    _LOG.warning(f"TSA failed, using local timestamp: {e}")
                    token = TimestampToken(
                        value=_utc_now(),
                        authority="local",
                        algorithm="LOCAL_TIMESTAMP",
                    )
                else:
                    raise

            # Return enhanced result
            if isinstance(result, CompliantResult):
                result.timestamp_token = token
                return result
            else:
                return CompliantResult(data=result_data, timestamp_token=token)

        return wrapper

    return decorator


# ============================================================================
# Composite Decorators
# ============================================================================


def compliant(
    *,
    regulation: str | None = None,
    signing: dict | None = None,
    audit: dict | None = None,
    timestamp: dict | None = None,
):
    """All-in-one compliance decorator.

    Applies signing, auditing, and timestamping based on configuration.

    Args:
        regulation: Predefined regulation config ("FDA_21CFR11", "ISO17025")
        signing: Signing configuration dict
        audit: Audit configuration dict
        timestamp: Timestamp configuration dict

    Example:
        @session.measure
        @compliant(regulation="FDA_21CFR11")
        def measure_voltage(dmm):
            return {"voltage": dmm.read_voltage()}
    """
    # Load regulation preset if specified
    if regulation:
        config = _load_regulation_config(regulation)
        signing = signing or config.get("signing")
        audit = audit or config.get("audit")
        timestamp = timestamp or config.get("timestamp")

    def decorator(func: Callable) -> Callable:
        # Apply decorators in reverse order (outer to inner)
        # timestamp -> audit -> signed -> func

        if timestamp:
            func = timestamped(**timestamp)(func)

        if audit:
            func = audited(**audit)(func)

        if signing:
            func = signed(**signing)(func)

        return func

    return decorator


# ============================================================================
# Internal Classes (simplified for demo)
# ============================================================================


class _Signer:
    """Cryptographic signer."""

    def __init__(self, key_file: Path | None, key_env_var: str | None, algorithm: str):
        self.algorithm = algorithm
        self._load_key(key_file, key_env_var)

    def _load_key(self, key_file: Path | None, key_env_var: str | None):
        """Load private key from file or environment."""
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec

        key_data = None

        if key_file:
            key_path = Path(key_file).expanduser()
            if not key_path.exists():
                raise FileNotFoundError(f"Key file not found: {key_path}")
            key_data = key_path.read_bytes()
        elif key_env_var:
            import os

            key_data = os.environ.get(key_env_var, "").encode()
            if not key_data:
                raise ValueError(f"Environment variable {key_env_var} not set")
        else:
            raise ValueError("Must provide key_file or key_env_var")

        # Load private key
        from typing import Any

        self._private_key: Any = serialization.load_pem_private_key(key_data, password=None)

        # Compute public key fingerprint
        public_key = self._private_key.public_key()
        public_bytes = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        self.fingerprint = hashlib.sha256(public_bytes).hexdigest()[:16]

    def sign(self, data: str) -> str:
        """Sign data and return base64-encoded signature."""
        import base64

        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec

        signature = self._private_key.sign(data.encode(), ec.ECDSA(hashes.SHA256()))
        return base64.b64encode(signature).decode()


class _AuditTrail:
    """Simple SQLite-based audit trail."""

    def __init__(self, db_path: Path | None):
        from .paths import audit_db_path

        self.db_path = db_path or audit_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Initialize audit database."""
        import sqlite3

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    function_name TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    result_hash TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    error_message TEXT
                )
            """
            )
            conn.commit()

    def append(self, record: AuditRecord):
        """Append record to audit trail."""
        import sqlite3

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO audit_log
                (event_type, function_name, timestamp, result_hash, success, error_message)
                VALUES (?, ?, ?, ?, ?, ?)
            """,
                (
                    record.event_type,
                    record.function_name,
                    record.timestamp,
                    record.result_hash,
                    1 if record.success else 0,
                    record.error_message,
                ),
            )
            conn.commit()


class _TSAClient:
    """Timestamp Authority client."""

    def __init__(self, authority: str | None, local_fallback: bool):
        self.authority = authority
        self.local_fallback = local_fallback

    def timestamp(self, data_hash: str) -> str:
        """Get timestamp token for data hash."""
        if self.authority:
            # TODO: Implement RFC 3161 TSA request
            # For now, return mock token
            return f"tsa:{self.authority}:{data_hash[:16]}:{_utc_now()}"
        else:
            # Local timestamp
            return f"local:{data_hash[:16]}:{_utc_now()}"


# ============================================================================
# Loader Functions
# ============================================================================


_signer_cache: dict[str, _Signer] = {}


def _load_signer(key_file: str | Path | None, key_env_var: str | None, algorithm: str) -> _Signer:
    """Load or cache signer."""
    cache_key = f"{key_file}:{key_env_var}:{algorithm}"

    if cache_key not in _signer_cache:
        _signer_cache[cache_key] = _Signer(
            Path(key_file) if key_file else None, key_env_var, algorithm
        )

    return _signer_cache[cache_key]


_audit_cache: dict[str, _AuditTrail] = {}


def _load_audit_trail(audit_db: str | Path | None) -> _AuditTrail:
    """Load or cache audit trail."""
    cache_key = str(audit_db) if audit_db else "default"

    if cache_key not in _audit_cache:
        _audit_cache[cache_key] = _AuditTrail(Path(audit_db) if audit_db else None)

    return _audit_cache[cache_key]


_tsa_cache: dict[str, _TSAClient] = {}


def _load_tsa(authority: str | None, local_fallback: bool) -> _TSAClient:
    """Load or cache TSA client."""
    cache_key = f"{authority}:{local_fallback}"

    if cache_key not in _tsa_cache:
        _tsa_cache[cache_key] = _TSAClient(authority, local_fallback)

    return _tsa_cache[cache_key]


def _load_regulation_config(regulation: str) -> dict:
    """Load predefined regulation configuration."""
    from .paths import audit_db_path
    from .paths import private_key_path

    REGULATIONS = {
        "FDA_21CFR11": {
            "signing": {
                "key_file": str(private_key_path("fda.pem")),
                "algorithm": "ECDSA_P256",
            },
            "audit": {
                "audit_db": str(audit_db_path("fda_audit.sqlite")),
                "include_params": True,
            },
            "timestamp": {
                "authority": "https://freetsa.org/tsr",
                "local_fallback": False,
            },
        },
        "ISO17025": {
            "signing": {
                "key_file": str(private_key_path("iso.pem")),
                "algorithm": "ECDSA_P256",
            },
            "audit": {
                "audit_db": str(audit_db_path("iso_audit.sqlite")),
                "include_params": False,
            },
            "timestamp": {
                "authority": None,
                "local_fallback": True,
            },
        },
    }

    if regulation not in REGULATIONS:
        raise ValueError(f"Unknown regulation: {regulation}")

    return REGULATIONS[regulation]
