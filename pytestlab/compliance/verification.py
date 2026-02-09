"""Compliance verification utilities.

This module is intentionally lightweight and graceful:
- It never raises for missing optional dependencies.
- It returns a VerificationResult with issues when verification is not possible.

Verification in a real non-repudiation system requires a trusted public key
source (trust anchor). If you verify against the local pytestlab state dir key,
that is convenient but not tamper-resistant.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from .decorators import CompliantResult, VerificationResult
from .paths import public_key_path


def verify_experiment(exp: Any, trust_anchor: Path | str | None = None) -> dict[str, Any]:
    """Verify an experiment object.

    This is a best-effort helper intended to keep the API ergonomic.
    It walks trials/measurements if those attributes exist.

    Returns:
        Dict with totals and per-measurement results.
    """
    results: list[VerificationResult] = []
    issues: list[str] = []

    trials = getattr(exp, "trials", None)
    if trials is None:
        return {"valid": False, "issues": ["Object has no 'trials' attribute"]}

    for trial in trials:
        measurements = getattr(trial, "measurements", None)
        if measurements is None:
            # Some representations store raw frames; skip silently
            continue
        for m in measurements:
            if hasattr(m, "verify"):
                vr = m.verify(trust_anchor=trust_anchor)
                results.append(vr)
                if vr.issues:
                    issues.extend(vr.issues)

    valid = all(r.valid for r in results) if results else False
    return {
        "valid": valid,
        "count": len(results),
        "issues": issues or None,
        "results": results,
    }


def verify_result(
    result: CompliantResult, trust_anchor: Path | str | None = None
) -> VerificationResult:
    """Verify a single CompliantResult.

    Args:
        result: CompliantResult to verify
        trust_anchor: Optional path to a PEM-encoded public key to use as a trust anchor.

    Returns:
        VerificationResult with booleans and issues.
    """
    issues: list[str] = []

    # Signature verification
    signature_valid: bool | None
    if result.signature is None:
        signature_valid = None
    else:
        signature_valid = _verify_signature(result, trust_anchor, issues)

    # Timestamp verification (placeholder - token format depends on timestamper)
    timestamp_valid: bool | None
    if result.timestamp_token is None:
        timestamp_valid = None
    else:
        # If a custom timestamper is used, verification should be done by that timestamper.
        timestamp_valid = True

    # Audit verification (placeholder - depends on auditor backend)
    audit_valid: bool | None
    if result.audit_record is None:
        audit_valid = None
    else:
        audit_valid = True

    valid = True
    for flag in (signature_valid, timestamp_valid, audit_valid):
        if flag is False:
            valid = False

    if result.signature is not None and signature_valid is None:
        valid = False

    return VerificationResult(
        valid=valid,
        signature_valid=signature_valid,
        timestamp_valid=timestamp_valid,
        audit_valid=audit_valid,
        issues=issues or None,
    )


def _verify_signature(
    result: CompliantResult, trust_anchor: Path | str | None, issues: list[str]
) -> bool:
    """Verify ECDSA signature for the signed decorator."""
    sig = result.signature
    if sig is None:
        return False

    # Canonicalization must match decorators.signed
    import json
    import hashlib

    canonical = json.dumps(result.data, sort_keys=True, separators=(",", ":")).encode()

    # Determine public key source
    pub_key_path: Path | None = None
    if trust_anchor is not None:
        pub_key_path = Path(trust_anchor).expanduser()
    else:
        # Best-effort local key (NOT tamper-resistant)
        pub_key_path = public_key_path()
        issues.append(
            "No trust_anchor provided; verifying against local state dir key (not tamper-resistant)."
        )

    if not pub_key_path.exists():
        issues.append(f"Public key not found: {pub_key_path}")
        return False

    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
    except ImportError:
        issues.append("cryptography is not installed; cannot verify signatures")
        return False

    try:
        # cryptography typing for load_pem_public_key is broad; we only support
        # ECDSA verification here. Treat as Any to keep type-checkers quiet.
        from typing import Any

        public_key: Any = serialization.load_pem_public_key(pub_key_path.read_bytes())
        signature_bytes = base64.b64decode(sig.value)
        # Verify signature over canonical JSON bytes
        public_key.verify(signature_bytes, canonical, ec.ECDSA(hashes.SHA256()))  # type: ignore
        return True
    except Exception as e:  # noqa: BLE001
        issues.append(f"Signature verification failed: {e}")
        return False
