"""
Default implementations for compliance interfaces.

These are reference implementations that work out of the box:
- FileSystemSigner: Keys stored in the local pytestlab state directory (NOT for production)
- SQLiteAuditor: Local SQLite database
- LocalTimestamper: System clock timestamps

For production security, users should provide their own implementations
using hardware security modules (HSM), blockchain, etc.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .._log import get_logger
from .paths import audit_db_path
from .paths import key_dir
from .interfaces import (
    AuditEntry,
    AuditError,
    Auditor,
    Signature,
    Signer,
    SigningError,
    TimestampError,
    TimestampToken,
    Timestamper,
)

_LOG = get_logger("compliance.defaults")

# Default paths
DEFAULT_KEY_DIR = key_dir()
DEFAULT_AUDIT_DB = audit_db_path()


class FileSystemSigner:
    """Reference Signer implementation using filesystem-stored keys.

    WARNING: This is NOT for production use! Private keys are stored
    unencrypted on the filesystem. For production, use HSM or external
    signing service.

    This implementation exists for:
    - Development and testing
    - Demonstrations
    - When no other signer is configured
    """

    def __init__(
        self,
        key_file: str | Path | None = None,
        key_env_var: str | None = None,
        algorithm: str = "ECDSA_P256",
    ):
        """Initialize FileSystemSigner.

        Args:
            key_file: Path to private key PEM file
            key_env_var: Environment variable containing private key
            algorithm: Algorithm identifier
        """
        self._algorithm = algorithm
        self._key_file = key_file
        self._key_env_var = key_env_var
        self._private_key: Any = None
        self._public_key: Any = None
        self._key_fingerprint: str | None = None

        self._load_key()

    def _load_key(self) -> None:
        """Load or generate private key."""
        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric import ec
        except ImportError as e:
            raise ImportError(
                "cryptography library required. Install: pip install pytestlab[secure]"
            ) from e

        key_data = None

        if self._key_file:
            key_path = Path(self._key_file).expanduser()
            if key_path.exists():
                key_data = key_path.read_bytes()
        elif self._key_env_var:
            key_data = os.environ.get(self._key_env_var, "").encode()

        if key_data:
            # Load existing key
            self._private_key = serialization.load_pem_private_key(key_data, password=None)
        else:
            # Generate new key
            _LOG.info("Generating new ECDSA key pair")
            self._private_key = ec.generate_private_key(ec.SECP256R1())
            self._save_key()

        # Compute key fingerprint
        self._public_key = self._private_key.public_key()
        public_bytes = self._public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        self._key_fingerprint = hashlib.sha256(public_bytes).hexdigest()[:16]

    def _save_key(self) -> None:
        """Save key to filesystem."""
        from cryptography.hazmat.primitives import serialization

        key_dir = DEFAULT_KEY_DIR
        key_dir.mkdir(parents=True, exist_ok=True)

        private_path = key_dir / "auto_generated.pem"
        public_path = key_dir / "auto_generated.pub"

        # Save private key
        private_pem = self._private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        private_path.write_bytes(private_pem)
        private_path.chmod(0o600)

        # Save public key
        public_key = self._private_key.public_key()
        public_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        public_path.write_bytes(public_pem)
        public_path.chmod(0o644)

        self._key_file = str(private_path)
        _LOG.info(f"Saved keys to {key_dir}")

    @property
    def key_fingerprint(self) -> str:
        """Return key fingerprint."""
        if self._key_fingerprint is None:
            raise SigningError("Key not loaded")
        return self._key_fingerprint

    @property
    def algorithm(self) -> str:
        """Return algorithm."""
        return f"{self._algorithm}_SHA256"

    def sign(self, data: bytes) -> Signature:
        """Sign data."""
        if self._private_key is None:
            raise SigningError("Private key not loaded")

        try:
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.asymmetric import ec

            signature_bytes = self._private_key.sign(data, ec.ECDSA(hashes.SHA256()))

            return Signature(
                value=base64.b64encode(signature_bytes).decode(),
                algorithm=self.algorithm,
                key_fingerprint=self.key_fingerprint,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
        except Exception as e:
            raise SigningError(f"Signing failed: {e}") from e

    def verify(self, data: bytes, signature: Signature) -> bool:
        """Verify signature."""
        if self._public_key is None:
            raise SigningError("Public key not available")

        try:
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.asymmetric import ec
            import base64

            signature_bytes = base64.b64decode(signature.value)
            self._public_key.verify(signature_bytes, data, ec.ECDSA(hashes.SHA256()))
            return True
        except Exception:
            return False

    def export_public_key(self) -> bytes:
        """Export public key."""
        if self._public_key is None:
            raise SigningError("Public key not available")

        from cryptography.hazmat.primitives import serialization

        return self._public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )


class SQLiteAuditor:
    """Reference Auditor implementation using SQLite.

    Stores audit trail in local SQLite database. This is suitable for
    development and small-scale use. For production, consider:
    - Append-only storage (S3 with WORM)
    - Blockchain anchoring
    - External audit service
    """

    def __init__(
        self,
        audit_db: str | Path | None = None,
        include_params: bool | None = None,
        include_args: bool | None = None,
        **_: Any,
    ):
        """Initialize SQLiteAuditor.

        Args:
            audit_db: Path to SQLite database file
        """
        self.db_path = Path(audit_db) if audit_db else DEFAULT_AUDIT_DB
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    function_name TEXT NOT NULL DEFAULT '',
                    timestamp TEXT NOT NULL,
                    data_hash TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    metadata TEXT,
                    error_message TEXT
                )
            """
            )
            # Best-effort migration for older databases missing function_name
            try:
                conn.execute(
                    "ALTER TABLE audit_log ADD COLUMN function_name TEXT NOT NULL DEFAULT ''"
                )
            except Exception:
                pass
            conn.commit()

    def append(self, entry: AuditEntry) -> str:
        """Append entry to audit log."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO audit_log
                    (event_type, function_name, timestamp, data_hash, success, metadata, error_message)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        entry.event_type,
                        entry.function_name,
                        entry.timestamp,
                        entry.result_hash,
                        1 if entry.success else 0,
                        json.dumps(entry.metadata),
                        entry.error_message,
                    ),
                )
                conn.commit()
                return str(cursor.lastrowid)
        except Exception as e:
            raise AuditError(f"Failed to append to audit log: {e}") from e

    def get(self, entry_id: str) -> AuditEntry | None:
        """Retrieve entry by ID."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute("SELECT * FROM audit_log WHERE id = ?", (entry_id,)).fetchone()

                if row is None:
                    return None

                return AuditEntry(
                    event_type=row[1],
                    function_name=row[2],
                    timestamp=row[3],
                    result_hash=row[4],
                    success=bool(row[5]),
                    metadata=json.loads(row[6]) if row[6] else {},
                    error_message=row[7],
                )
        except Exception as e:
            raise AuditError(f"Failed to retrieve audit entry: {e}") from e

    def verify(self) -> bool:
        """Verify audit trail integrity."""
        # For SQLite, we just check the database is readable
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()
            return True
        except Exception:
            return False

    def export(self, format: str = "json") -> bytes:
        """Export audit trail."""
        if format != "json":
            raise ValueError(f"Unsupported format: {format}")

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM audit_log").fetchall()
            data = [dict(row) for row in rows]
            return json.dumps(data, indent=2).encode()


class LocalTimestamper:
    """Reference Timestamper using local system clock.

    This provides timestamps but not cryptographic proof of time.
    For production non-repudiation, use:
    - RFC 3161 TSA (e.g., FreeTSA)
    - Blockchain anchoring
    - GPS time source
    """

    def __init__(self, authority: str | None = None, local_fallback: bool = True):
        """Initialize LocalTimestamper.

        Args:
            authority: Ignored (for interface compatibility)
            local_fallback: Ignored (always uses local time)
        """
        self.authority = "local"
        self.algorithm = "LOCAL_TIMESTAMP"

    def timestamp(self, data_hash: str) -> TimestampToken:
        """Create local timestamp."""
        timestamp = datetime.now(timezone.utc).isoformat()

        # Create simple token (not cryptographically secure!)
        token_data = f"{data_hash}:{timestamp}".encode()
        token = base64.b64encode(token_data).decode()

        return TimestampToken(
            value=token,
            authority=self.authority,
            algorithm=self.algorithm,
        )

    def verify(self, data_hash: str, token: TimestampToken) -> bool:
        """Verify local timestamp (always returns True for local)."""
        # Local timestamps can't really be verified
        # In production, this would verify against TSA
        return token.authority == "local"


# ============================================================================
# Utility Functions
# ============================================================================


def ensure_default_infrastructure() -> dict[str, Any]:
    """Ensure default compliance infrastructure exists.

    Returns:
        Configuration dict for default implementations
    """
    return {
        "signing": {"key_file": str(DEFAULT_KEY_DIR / "auto_generated.pem")},
        "audit": {"audit_db": str(DEFAULT_AUDIT_DB)},
        "timestamp": {"authority": None, "local_fallback": True},
    }
