#!/usr/bin/env python
"""
Test script to verify the compliance feature is working correctly.
"""
import json
import pathlib
from pytestlab import MeasurementResult
from pytestlab.experiments.database import MeasurementDatabase
import numpy as np

def test_compliance():
    print("Testing PyTestLab compliance feature...")
    print("Importing pytestlab...")
    
    # Create a test measurement result
    print("Creating test measurement result...")
    test_values = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    result = MeasurementResult(
        values=test_values,
        instrument="TestInstrument",
        units="V",
        measurement_type="voltage_test"
    )
    print("MeasurementResult created successfully")
    
    # Check if envelope was created
    if hasattr(result, 'envelope'):
        print("✓ MeasurementResult has envelope attribute")
        print(f"  Algorithm: {result.envelope.get('alg', 'Not found')}")
        print(f"  SHA: {result.envelope.get('sha', 'Not found')[:16]}...")
    else:
        print("✗ MeasurementResult missing envelope attribute")
    
    # Check if PROV data was created
    if hasattr(result, 'prov'):
        print("✓ MeasurementResult has PROV attribute")
    else:
        print("✗ MeasurementResult missing PROV attribute")
    
    # Test database storage
    try:
        db = MeasurementDatabase("test_compliance")
        codename = db.store_measurement(None, result)
        print(f"✓ Measurement stored with codename: {codename}")
        
        # Check if envelope was stored in database
        conn = db._get_connection()
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='measurement_envelopes'")
        if cursor.fetchone():
            print("✓ measurement_envelopes table created")
            
            # Check if envelope data was stored
            cursor = conn.execute("SELECT envelope_json FROM measurement_envelopes WHERE codename = ?", (codename,))
            envelope_row = cursor.fetchone()
            if envelope_row:
                envelope_data = json.loads(envelope_row[0])
                print(f"✓ Envelope stored in database with algorithm: {envelope_data.get('alg', 'Not found')}")
            else:
                print("✗ No envelope data found in database")
        else:
            print("✗ measurement_envelopes table not created")
            
        db.close()
    except Exception as e:
        print(f"✗ Database test failed: {e}")
    
    # Check audit trail
    audit_path = pathlib.Path.home() / ".pytestlab" / "tsa.json"
    if audit_path.exists():
        try:
            with open(audit_path) as f:
                audit_data = json.load(f)
            print(f"✓ Audit trail exists with {len(audit_data)} entries")
        except Exception as e:
            print(f"✗ Error reading audit trail: {e}")
    else:
        print("✗ Audit trail file not found")
    
    # Check HSM directory
    hsm_path = pathlib.Path.home() / ".pytestlab" / "hsm"
    if hsm_path.exists():
        private_key_path = hsm_path / "private.pem"
        if private_key_path.exists():
            print("✓ Private key generated in HSM directory")
        else:
            print("✗ Private key not found in HSM directory")
    else:
        print("✗ HSM directory not created")

if __name__ == "__main__":
    test_compliance()
