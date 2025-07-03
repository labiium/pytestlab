#!/usr/bin/env python
"""
Test script to verify the compliance feature is working correctly.
"""
import json
import pathlib
import pytest
from pytestlab import MeasurementResult
from pytestlab.experiments.database import MeasurementDatabase
import numpy as np

@pytest.fixture
def test_values():
    return np.array([1.0, 2.0, 3.0, 4.0, 5.0])

@pytest.fixture
def measurement_result(test_values):
    return MeasurementResult(
        values=test_values,
        instrument="TestInstrument",
        units="V",
        measurement_type="voltage_test"
    )

@pytest.fixture
def db():
    db = MeasurementDatabase("test_compliance")
    yield db
    db.close()

# Envelope attribute

def test_measurement_has_envelope(measurement_result):
    assert hasattr(measurement_result, 'envelope'), "MeasurementResult missing envelope attribute"
    envelope = measurement_result.envelope
    assert 'alg' in envelope
    assert 'sha' in envelope
    assert isinstance(envelope['sha'], str)

# PROV attribute

def test_measurement_has_prov(measurement_result):
    assert hasattr(measurement_result, 'prov'), "MeasurementResult missing PROV attribute"

# Database storage and envelope table

def test_database_stores_measurement_and_envelope(db, measurement_result):
    codename = db.store_measurement(None, measurement_result)
    conn = db._get_connection()
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='measurement_envelopes'")
    assert cursor.fetchone(), "measurement_envelopes table not created"
    cursor = conn.execute("SELECT envelope_json FROM measurement_envelopes WHERE codename = ?", (codename,))
    envelope_row = cursor.fetchone()
    assert envelope_row, "No envelope data found in database"
    envelope_data = json.loads(envelope_row[0])
    assert 'alg' in envelope_data

# Audit trail file

def test_audit_trail_exists():
    audit_path = pathlib.Path.home() / ".pytestlab" / "tsa.json"
    assert audit_path.exists(), "Audit trail file not found"
    with open(audit_path) as f:
        audit_data = json.load(f)
    assert isinstance(audit_data, list)

# HSM directory and private key

def test_hsm_private_key_exists():
    hsm_path = pathlib.Path.home() / ".pytestlab" / "hsm"
    assert hsm_path.exists(), "HSM directory not created"
    private_key_path = hsm_path / "private.pem"
    assert private_key_path.exists(), "Private key not found in HSM directory"
