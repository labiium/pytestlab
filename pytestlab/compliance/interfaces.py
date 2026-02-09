"""
Compliance interfaces for pluggable security implementations.

This module defines protocols that allow users to bring their own:
- Signer: Cryptographic signing implementations
- Auditor: Audit trail implementations
- Timestamper: Timestamp authority implementations

The library provides default implementations based on the original
design (file-based keys, SQLite audit, local timestamps), but users
can substitute their own for production security requirements.

Example:
    from pytestlab.compliance import ComplianceConfig
    from pytestlab.compliance.interfaces import Signer, Signature

    class MyHSM(Signer):
        def sign(self, data: bytes) -> Signature:
            # Your HSM implementation
            ...

    config = ComplianceConfig(signer=MyHSM())
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


# ============================================================================
# Data Classes
# ============================================================================


@dataclass(frozen=True)
class Signature:
    """Cryptographic signature with metadata."""

    value: str  # Base64-encoded signature
    algorithm: str
    key_fingerprint: str  # Unique identifier for the signing key
    timestamp: str

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for storage."""
        return {
            "value": self.value,
            "algorithm": self.algorithm,
            "key_fingerprint": self.key_fingerprint,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Signature:
        """Deserialize from dictionary."""
        return cls(
            value=data["value"],
            algorithm=data["algorithm"],
            key_fingerprint=data.get("key_fingerprint") or data.get("key_id", ""),
            timestamp=data["timestamp"],
        )


@dataclass(frozen=True)
class TimestampToken:
    """Timestamp authority token."""

    value: str  # Token data (named 'value' for backward compat with decorators)
    authority: str
    algorithm: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "authority": self.authority,
            "algorithm": self.algorithm,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TimestampToken:
        return cls(
            value=data["value"],
            authority=data["authority"],
            algorithm=data["algorithm"],
        )


@dataclass(frozen=True)
class AuditEntry:
    """Single audit trail entry.

    This is the canonical audit record type used across the compliance system.
    """

    event_type: str
    function_name: str
    timestamp: str
    result_hash: str
    success: bool
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "function_name": self.function_name,
            "timestamp": self.timestamp,
            "result_hash": self.result_hash,
            "success": self.success,
            "error_message": self.error_message,
            "metadata": self.metadata,
        }


# ============================================================================
# Protocols
# ============================================================================


@runtime_checkable
class Signer(Protocol):
    """Protocol for cryptographic signing implementations.

    Implementations must provide:
    - key_fingerprint: Unique identifier for the signing key
    - algorithm: Algorithm identifier string
    - sign(): Create signature for data
    - verify(): Verify signature against data

    Example implementations:
    - FileSystemSigner: Default, keys in the local state dir (NOT for production)
    - YubiKeySigner: Hardware security module
    - AWSKMSSigner: Cloud key management service
    - HashiCorpVaultSigner: Enterprise vault
    """

    @property
    def key_fingerprint(self) -> str:
        """Return unique identifier for this key.

        Used to identify which key signed data. Should be stable
        and unique per key (e.g., fingerprint, serial number).
        """
        ...

    @property
    def algorithm(self) -> str:
        """Return algorithm identifier string.

        Examples:
        - "ECDSA_P256_SHA256"
        - "RSA_2048_SHA256"
        - "ED25519"
        """
        ...

    def sign(self, data: bytes) -> Signature:
        """Sign data and return signature.

        Args:
            data: Raw bytes to sign

        Returns:
            Signature object with value, algorithm, key_fingerprint, timestamp

        Raises:
            SigningError: If signing fails
        """
        ...

    def verify(self, data: bytes, signature: Signature) -> bool:
        """Verify signature against data.

        Args:
            data: Raw bytes that were signed
            signature: Signature to verify

        Returns:
            True if signature is valid, False otherwise
        """
        ...

    def export_public_key(self) -> bytes:
        """Export public key for external verification.

        Returns:
            Public key in PEM format (or other standard format)

        Note:
            Not all implementations support this (e.g., HSMs may
            not allow key export). Raise NotImplementedError if
            not supported.
        """
        ...


@runtime_checkable
class Auditor(Protocol):
    """Protocol for audit trail implementations.

    Implementations must provide:
    - append(): Add entry to audit trail
    - get(): Retrieve entry by ID
    - verify(): Verify integrity of audit chain
    - export(): Export audit trail for external analysis

    Example implementations:
    - SQLiteAuditor: Default, local SQLite database
    - BlockchainAuditor: Immutable blockchain anchoring
    - S3Auditor: Cloud storage with WORM
    - SyslogAuditor: System log integration
    """

    def append(self, entry: AuditEntry) -> str:
        """Append entry to audit trail.

        Args:
            entry: Audit entry to store

        Returns:
            Unique entry ID/reference for later retrieval

        Raises:
            AuditError: If append fails
        """
        ...

    def get(self, entry_id: str) -> AuditEntry | None:
        """Retrieve entry by ID.

        Args:
            entry_id: Entry ID returned by append()

        Returns:
            AuditEntry if found, None otherwise
        """
        ...

    def verify(self) -> bool:
        """Verify integrity of audit trail.

        Returns:
            True if audit trail integrity is intact

        Note:
            Implementation should verify chain of custody,
            detect gaps or tampering, etc.
        """
        ...

    def export(self, format: str = "json") -> bytes:
        """Export audit trail for external analysis.

        Args:
            format: Export format ("json", "csv", "xml", etc.)

        Returns:
            Serialized audit trail data
        """
        ...


@runtime_checkable
class Timestamper(Protocol):
    """Protocol for timestamp authority implementations.

    Implementations must provide:
    - timestamp(): Generate timestamp for data hash
    - verify(): Verify timestamp token is valid

    Example implementations:
    - LocalTimestamper: Default, uses system clock
    - RFCTimestamper: RFC 3161 TSA (e.g., FreeTSA)
    - BlockchainTimestamper: Bitcoin/Ethereum anchoring
    - GoogleRoughtime: Google's Roughtime protocol
    """

    def timestamp(self, data_hash: str) -> TimestampToken:
        """Generate timestamp for data hash.

        Args:
            data_hash: Hex-encoded hash of data to timestamp

        Returns:
            TimestampToken with authority, timestamp, token, algorithm

        Raises:
            TimestampError: If timestamping fails
        """
        ...

    def verify(self, data_hash: str, token: TimestampToken) -> bool:
        """Verify timestamp token is valid.

        Args:
            data_hash: Original data hash that was timestamped
            token: TimestampToken to verify

        Returns:
            True if token is valid for data_hash, False otherwise
        """
        ...


# ============================================================================
# Exceptions
# ============================================================================


class ComplianceError(Exception):
    """Base exception for compliance operations."""

    pass


class SigningError(ComplianceError):
    """Exception raised during signing operations."""

    pass


class AuditError(ComplianceError):
    """Exception raised during audit operations."""

    pass


class TimestampError(ComplianceError):
    """Exception raised during timestamp operations."""

    pass
