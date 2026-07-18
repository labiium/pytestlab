"""Compliance tests for the current compliance implementation.

These tests validate the decorator-based compliance system:
- cryptographic signing via `pytestlab.compliance.signed`
- audit trail recording via `pytestlab.compliance.audited`
- verification via `pytestlab.compliance.verification`

Note: These tests require `cryptography`.
"""

import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

import pytest

from pytestlab.compliance.auto_config import ensure_key_pair
from pytestlab.compliance.decorators import CompliantResult
from pytestlab.compliance.decorators import _TSAClient
from pytestlab.compliance.decorators import audited
from pytestlab.compliance.decorators import signed
from pytestlab.compliance.decorators import timestamped
from pytestlab.compliance.interfaces import TimestampError
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
    ensure_key_pair(temp_signer_dir)
    assert (temp_signer_dir / "auto_generated.pem").exists()
    assert (temp_signer_dir / "auto_generated.pub").exists()


def test_signed_decorator_produces_signature(mock_instrument, temp_signer_dir):
    """`@signed` should produce a CompliantResult with a Signature."""
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
    ensure_key_pair(temp_signer_dir)
    priv = temp_signer_dir / "auto_generated.pem"
    pub = temp_signer_dir / "auto_generated.pub"

    @signed(key_file=priv)
    def measure():
        return {"measurement": "resistance", "value": 1000.0, "units": "ohm"}

    result = measure()
    assert verify_result(result, trust_anchor=pub).signature_valid is True

    # Simulate storage (JSON-like)
    assert result.signature is not None
    stored_data = result.data
    stored_signature = result.signature.to_dict()

    # Reload
    from pytestlab.compliance.interfaces import Signature

    reloaded = CompliantResult(
        data=stored_data,
        signature=Signature.from_dict(stored_signature),
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

    with closing(sqlite3.connect(audit_db)) as conn:
        n = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
        assert n >= 1


def test_private_key_file_is_pem(temp_signer_dir):
    """Generated private key should be a PEM file."""
    ensure_key_pair(temp_signer_dir)
    private_key_path = temp_signer_dir / "auto_generated.pem"
    content = private_key_path.read_text()
    assert content.startswith("-----BEGIN PRIVATE KEY-----")
    assert content.strip().endswith("-----END PRIVATE KEY-----")


def test_signatures_from_different_keys_are_distinct(temp_signer_dir):
    """Different keys should yield different key fingerprints."""
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


def test_tsa_client_rejects_unimplemented_authority():
    """Configured TSA authorities must not produce fabricated RFC 3161 evidence."""
    client = _TSAClient("https://tsa.example.test/tsr", local_fallback=True)

    with pytest.raises(TimestampError, match="RFC 3161 timestamping is not implemented"):
        client.timestamp("a" * 64)


def test_tsa_client_returns_local_token_only_when_fallback_enabled():
    """Local fallback should be explicit and unavailable when disabled."""
    client = _TSAClient(None, local_fallback=True)

    token = client.timestamp("b" * 64)

    assert token.startswith("local:"), token


def test_tsa_client_rejects_local_timestamp_without_fallback():
    """No TSA authority and no local fallback is a timestamping error."""
    client = _TSAClient(None, local_fallback=False)

    with pytest.raises(TimestampError, match="local timestamp fallback is disabled"):
        client.timestamp("c" * 64)


def test_timestamped_decorator_propagates_configured_authority_error():
    """Configured TSA authority failures must not fall back to local timestamps."""

    @timestamped(authority="https://tsa.example.test/tsr", local_fallback=True)
    def measure():
        return {"measurement": "voltage", "value": 1.23}

    with pytest.raises(TimestampError, match="RFC 3161 timestamping is not implemented"):
        measure()
