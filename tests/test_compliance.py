"""Compliance tests for the current compliance implementation.

These tests validate the decorator-based compliance system:
- cryptographic signing via `pytestlab.compliance.signed`
- audit trail recording via `pytestlab.compliance.audited`
- verification via `pytestlab.compliance.verification`

Note: These tests require `cryptography`.
"""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from pytestlab.compliance.auto_config import ensure_key_pair
from pytestlab.compliance.decorators import CompliantResult
from pytestlab.compliance.decorators import audited
from pytestlab.compliance.decorators import signed
from pytestlab.compliance.verification import verify_result


class MockInstrument:
    """Mock instrument for testing compliance features."""

    def __init__(self, name):
        self.name = name
        self.settings = {"range": "auto", "resolution": 5}

    def get_settings(self):
        return self.settings

    def to_dict(self):
        """Convert instrument state to dictionary for signing."""
        return {"name": self.name, "settings": self.settings, "type": "mock_instrument"}


@pytest.fixture
def mock_instrument():
    """Provides a mock instrument for testing."""
    return MockInstrument("TestScope")


@pytest.fixture
def temp_signer_dir():
    """Create a temporary directory for test keys."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield Path(temp_dir)


def test_key_pair_generation(temp_signer_dir):
    """Key generation should create a private and public key."""
    pytest.importorskip("cryptography")

    ensure_key_pair(temp_signer_dir)
    assert (temp_signer_dir / "auto_generated.pem").exists()
    assert (temp_signer_dir / "auto_generated.pub").exists()


def test_signed_decorator_produces_signature(mock_instrument, temp_signer_dir):
    """`@signed` should produce a CompliantResult with a Signature."""
    pytest.importorskip("cryptography")

    ensure_key_pair(temp_signer_dir)
    priv = temp_signer_dir / "auto_generated.pem"
    pub = temp_signer_dir / "auto_generated.pub"

    @signed(key_file=priv)
    def measure():
        return {
            "instrument": mock_instrument.to_dict(),
            "measurement": "voltage_dc",
            "value": 5.23,
            "units": "V",
            "timestamp": "2024-01-15T10:30:00Z",
        }

    result = measure()
    assert isinstance(result, CompliantResult)
    assert result.signature is not None
    assert result.signature.algorithm.endswith("SHA256")
    assert result.signature.key_fingerprint

    vr = verify_result(result, trust_anchor=pub)
    assert vr.signature_valid is True


def test_tampering_is_detected(temp_signer_dir):
    """Mutating signed data should invalidate signature verification."""
    pytest.importorskip("cryptography")

    ensure_key_pair(temp_signer_dir)
    priv = temp_signer_dir / "auto_generated.pem"
    pub = temp_signer_dir / "auto_generated.pub"

    @signed(key_file=priv)
    def measure():
        return {
            "measurement": "current_dc",
            "value": 0.025,
            "units": "A",
            "provenance": {
                "operator": "test_user",
                "environment": {"temperature": 23.5, "humidity": 45},
                "calibration_date": "2024-01-01",
            },
        }

    result = measure()
    assert verify_result(result, trust_anchor=pub).signature_valid is True

    # Tamper
    result.data["value"] = 0.030
    assert verify_result(result, trust_anchor=pub).signature_valid is False


def test_result_can_be_stored_and_verified(temp_signer_dir):
    """A stored result+signature remains verifiable."""
    pytest.importorskip("cryptography")

    ensure_key_pair(temp_signer_dir)
    priv = temp_signer_dir / "auto_generated.pem"
    pub = temp_signer_dir / "auto_generated.pub"

    @signed(key_file=priv)
    def measure():
        return {"measurement": "resistance", "value": 1000.0, "units": "ohm"}

    result = measure()
    assert verify_result(result, trust_anchor=pub).signature_valid is True

    # Simulate storage (JSON-like)
    stored = {
        "data": result.data,
        "signature": result.signature.to_dict() if result.signature else None,
    }

    # Reload
    from pytestlab.compliance.interfaces import Signature

    reloaded = CompliantResult(
        data=stored["data"],
        signature=Signature.from_dict(stored["signature"]),
    )
    assert verify_result(reloaded, trust_anchor=pub).signature_valid is True


def test_audited_decorator_writes_sqlite(temp_signer_dir):
    """`@audited` should create an sqlite file and record an entry."""
    audit_db = temp_signer_dir / "audit.sqlite"

    @audited(audit_db=audit_db)
    def measure():
        return {"x": 1}

    result = measure()
    assert isinstance(result, CompliantResult)
    assert audit_db.exists()

    with sqlite3.connect(audit_db) as conn:
        n = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
        assert n >= 1


def test_private_key_file_is_pem(temp_signer_dir):
    """Generated private key should be a PEM file."""
    pytest.importorskip("cryptography")

    ensure_key_pair(temp_signer_dir)
    private_key_path = temp_signer_dir / "auto_generated.pem"
    content = private_key_path.read_text()
    assert content.startswith("-----BEGIN PRIVATE KEY-----")
    assert content.strip().endswith("-----END PRIVATE KEY-----")


def test_signatures_from_different_keys_are_distinct(temp_signer_dir):
    """Different keys should yield different key fingerprints."""
    pytest.importorskip("cryptography")

    d1 = temp_signer_dir / "k1"
    d2 = temp_signer_dir / "k2"
    d1.mkdir()
    d2.mkdir()

    ensure_key_pair(d1)
    ensure_key_pair(d2)

    priv1 = d1 / "auto_generated.pem"
    pub1 = d1 / "auto_generated.pub"
    priv2 = d2 / "auto_generated.pem"
    pub2 = d2 / "auto_generated.pub"

    payload = {"measurement": "test", "value": 42}

    @signed(key_file=priv1)
    def m1():
        return dict(payload)

    @signed(key_file=priv2)
    def m2():
        return dict(payload)

    r1 = m1()
    r2 = m2()
    assert r1.signature is not None and r2.signature is not None
    assert r1.signature.key_fingerprint != r2.signature.key_fingerprint
    assert verify_result(r1, trust_anchor=pub1).signature_valid is True
    assert verify_result(r2, trust_anchor=pub2).signature_valid is True


@pytest.mark.skip(reason="Complex timestamping authority integration requires network access.")
def test_timestamping_authority_integration():
    """Placeholder for testing integration with a timestamping authority.

    This test is intentionally skipped because it requires:
    1. Network access to external RFC 3161 timestamping authorities
    2. Complex certificate validation infrastructure
    3. Handling of network timeouts and failures
    4. Integration with third-party timestamping services

    Implementation would involve:
    - Connecting to trusted timestamping authorities
    - Sending timestamp requests for measurement signatures
    - Validating timestamp responses and certificates
    - Embedding timestamps in compliance envelopes
    """
    # This would test RFC 3161 timestamping integration
    # when that feature is implemented
    pass


@pytest.mark.skip(reason="Complex compliance reporting not yet implemented.")
def test_compliance_report_generation():
    """Placeholder for testing compliance report generation.

    This test is intentionally skipped because it requires:
    1. Comprehensive report generation infrastructure
    2. Template system for various compliance standards
    3. Integration with database for historical data
    4. PDF/document generation capabilities
    5. Audit trail aggregation and formatting

    Implementation would involve:
    - Aggregating all measurements, signatures, and audit events
    - Generating standardized compliance reports (ISO, FDA, etc.)
    - Including verification of all digital signatures
    - Formatting for regulatory submission requirements
    """
    # This would test generation of compliance reports
    # that include all measurements, signatures, and audit trails
    pass
