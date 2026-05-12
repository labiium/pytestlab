"""
Auto-configuration for compliance features.

This module provides automatic setup of compliance infrastructure:
- Generates cryptographic keys if they don't exist
- Creates default audit database
- Sets up local timestamping

This enables "invisible" compliance where users don't need to
configure anything - it just works out of the box.
"""

from __future__ import annotations

import os
from importlib.util import find_spec
from pathlib import Path
from typing import Any

from .._log import get_logger
from .paths import audit_db_path
from .paths import key_dir as default_key_dir
from .paths import private_key_path
from .paths import public_key_path

_LOG = get_logger("compliance.auto_config")

# Default names
DEFAULT_PRIVATE_KEY_NAME = "auto_generated.pem"
DEFAULT_PUBLIC_KEY_NAME = "auto_generated.pub"

# Environment variable overrides
ENV_KEY_FILE = "PYTESTLAB_KEY_FILE"
ENV_AUDIT_DB = "PYTESTLAB_AUDIT_DB"
ENV_COMPLIANCE_DISABLED = "PYTESTLAB_COMPLIANCE_DISABLED"


def ensure_compliance_config() -> dict[str, Any]:
    """Ensure compliance infrastructure exists and return default config.

    This function:
    1. Checks if compliance is disabled via environment
    2. Creates a platform-appropriate state directory if needed
    3. Generates ECDSA key pair if keys don't exist
    4. Returns default configuration using auto-generated resources

    Returns:
        Dictionary with signing, audit, and timestamp configuration

    Example:
        >>> config = ensure_compliance_config()
        >>> print(config)
        {
            'signing': {'key_file': '<resolved state dir>/keys/auto_generated.pem'},
            'audit': {'audit_db': '<resolved state dir>/audit.sqlite'},
            'timestamp': {'authority': None, 'local_fallback': True}
        }
    """
    # Check if compliance is explicitly disabled
    if os.getenv(ENV_COMPLIANCE_DISABLED, "").lower() in ("true", "1", "yes"):
        _LOG.debug("Compliance disabled via environment variable")
        raise ComplianceDisabledError(f"Compliance disabled via {ENV_COMPLIANCE_DISABLED}=true")

    # Ensure directory structure exists
    base_dir = default_key_dir().parent
    base_dir.mkdir(parents=True, exist_ok=True)
    keys_dir = default_key_dir()
    keys_dir.mkdir(parents=True, exist_ok=True)

    # Check for environment variable overrides
    key_file = os.getenv(ENV_KEY_FILE)
    audit_db = os.getenv(ENV_AUDIT_DB)

    # Generate keys if they don't exist and no override provided.
    # Be graceful: if cryptography isn't installed, skip signing.
    signing_cfg: dict[str, Any] | None = None
    if key_file is None:
        try:
            key_file = ensure_key_pair(keys_dir)
        except ImportError as e:
            _LOG.warning(f"Signing disabled (missing dependency): {e}")
            key_file = None

    if audit_db is None:
        audit_db = str(audit_db_path())

    if key_file is not None:
        signing_cfg = {"key_file": key_file, "algorithm": "ECDSA_P256"}

    config = {
        "signing": signing_cfg,
        "audit": {"audit_db": audit_db, "include_params": False},
        "timestamp": {"authority": None, "local_fallback": True},
    }

    _LOG.debug(f"Auto-configured compliance with key: {key_file}")
    return config


def ensure_key_pair(key_dir: Path) -> str:
    """Generate or locate cryptographic key pair.

    If keys already exist in key_dir, return path to private key.
    Otherwise, generate new ECDSA P-256 key pair.

    Args:
        key_dir: Directory to store keys

    Returns:
        Path to private key file

    Raises:
        ImportError: If cryptography library not available
    """
    private_key_path = key_dir / DEFAULT_PRIVATE_KEY_NAME
    public_key_path = key_dir / DEFAULT_PUBLIC_KEY_NAME

    if private_key_path.exists() and public_key_path.exists():
        _LOG.debug(f"Using existing keys from {key_dir}")
        return str(private_key_path)

    # Generate new key pair
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec
    except ImportError as e:
        raise ImportError(
            "cryptography library required for compliance. "
            "Install with: pip install pytestlab[secure]"
        ) from e

    _LOG.info(f"Generating new ECDSA key pair in {key_dir}")

    # Generate private key
    private_key = ec.generate_private_key(ec.SECP256R1())

    # Serialize and save private key
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    private_key_path.write_bytes(private_pem)

    # Set restrictive permissions (owner read/write only)
    private_key_path.chmod(0o600)

    # Serialize and save public key
    public_key = private_key.public_key()
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM, format=serialization.PublicFormat.SubjectPublicKeyInfo
    )
    public_key_path.write_bytes(public_pem)
    public_key_path.chmod(0o644)  # Public key can be readable

    _LOG.info("✓ Generated compliance keys:")
    _LOG.info(f"  Private: {private_key_path} (restricted)")
    _LOG.info(f"  Public:  {public_key_path}")
    _LOG.info(f"  Fingerprint: {_compute_fingerprint(public_key)}")

    return str(private_key_path)


def _compute_fingerprint(public_key) -> str:
    """Compute SHA-256 fingerprint of public key."""
    import hashlib

    from cryptography.hazmat.primitives import serialization

    public_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.PEM, format=serialization.PublicFormat.SubjectPublicKeyInfo
    )
    fingerprint = hashlib.sha256(public_bytes).hexdigest()[:16]
    return f"SHA256:{fingerprint}"


def get_key_info() -> dict[str, Any]:
    """Get information about current compliance keys.

    Returns:
        Dictionary with key status and metadata
    """
    private_key = private_key_path(DEFAULT_PRIVATE_KEY_NAME)
    public_key = public_key_path(DEFAULT_PUBLIC_KEY_NAME)

    result = {
        "key_dir": str(default_key_dir()),
        "private_key_exists": private_key.exists(),
        "public_key_exists": public_key.exists(),
        "fingerprint": None,
    }

    if result["public_key_exists"]:
        try:
            import hashlib

            public_bytes = public_key.read_bytes()
            fingerprint = hashlib.sha256(public_bytes).hexdigest()[:16]
            result["fingerprint"] = f"SHA256:{fingerprint}"
        except Exception as e:
            _LOG.warning(f"Could not read public key: {e}")

    return result


def reset_keys() -> None:
    """Reset compliance keys (generates new key pair).

    WARNING: This will invalidate all previous signatures!
    Only use for testing or if keys are compromised.
    """
    import shutil

    keys_dir = default_key_dir()
    if keys_dir.exists():
        _LOG.warning("Removing existing compliance keys")
        shutil.rmtree(keys_dir)

    # Regenerate
    ensure_key_pair(keys_dir)
    _LOG.info("Generated new compliance key pair")


class ComplianceDisabledError(Exception):
    """Raised when compliance is disabled via environment variable."""

    pass


def is_compliance_available() -> bool:
    """Check if compliance infrastructure is available.

    Returns True if:
    - cryptography library is installed
    - Keys exist or can be generated
    - Not disabled via environment
    """
    # Check if disabled
    if os.getenv(ENV_COMPLIANCE_DISABLED, "").lower() in ("true", "1", "yes"):
        return False

    return find_spec("cryptography") is not None


def show_compliance_status() -> None:
    """Print compliance status to console."""
    print("=" * 60)
    print("Pytestlab Compliance Status")
    print("=" * 60)

    # Check if disabled
    if os.getenv(ENV_COMPLIANCE_DISABLED, "").lower() in ("true", "1", "yes"):
        print("Status: DISABLED via environment variable")
        print(f"  {ENV_COMPLIANCE_DISABLED}=true")
        return

    if find_spec("cryptography") is not None:
        print("Status: AVAILABLE")
    else:
        print("Status: UNAVAILABLE")
        print("  Install: pip install pytestlab[secure]")
        return

    # Show key info
    info = get_key_info()
    print(f"Key Directory: {info['key_dir']}")

    if info["private_key_exists"] and info["public_key_exists"]:
        print("Keys: ✓ Present")
        if info["fingerprint"]:
            print(f"Fingerprint: {info['fingerprint']}")
    else:
        print("Keys: ✗ Not generated (will auto-generate on first use)")

    # Show environment overrides
    if os.getenv(ENV_KEY_FILE):
        print(f"Custom Key: {os.getenv(ENV_KEY_FILE)}")
    if os.getenv(ENV_AUDIT_DB):
        print(f"Custom Audit DB: {os.getenv(ENV_AUDIT_DB)}")

    print("=" * 60)
