#!/usr/bin/env python
"""
Debug script to test compliance step by step.
"""

print("1. Testing compliance module import...")
try:
    import pytestlab.compliance
    print("✓ Compliance module imported")
except Exception as e:
    print(f"✗ Error importing compliance: {e}")
    exit(1)

print("\n2. Testing MeasurementResult import...")
try:
    from pytestlab.experiments.results import MeasurementResult
    print("✓ MeasurementResult imported")
    print(f"   MeasurementResult class: {MeasurementResult}")
    print(f"   MeasurementResult module: {MeasurementResult.__module__}")
except Exception as e:
    print(f"✗ Error importing MeasurementResult: {e}")
    exit(1)

print("\n3. Testing MeasurementResult creation...")
try:
    import numpy as np
    result = MeasurementResult(
        values=np.array([1.0, 2.0, 3.0]),
        instrument="TestInstrument",
        units="V",
        measurement_type="test"
    )
    print("✓ MeasurementResult created")
    print(f"   Has envelope: {hasattr(result, 'envelope')}")
    print(f"   Has prov: {hasattr(result, 'prov')}")
    if hasattr(result, 'envelope'):
        print(f"   Envelope keys: {list(result.envelope.keys())}")
except Exception as e:
    print(f"✗ Error creating MeasurementResult: {e}")
    import traceback
    traceback.print_exc()
