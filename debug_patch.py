#!/usr/bin/env python
"""Debug script to check monkey patching."""

import pytestlab
import numpy as np

print("1. Checking MeasurementResult class...")
print(f"   Class: {pytestlab.MeasurementResult}")
print(f"   Module: {pytestlab.MeasurementResult.__module__}")

print("\n2. Creating MeasurementResult instance...")
result = pytestlab.MeasurementResult(
    values=np.array([1.0, 2.0, 3.0]),
    instrument="Test",
    units="V",
    measurement_type="test"
)

print(f"   Instance type: {type(result)}")
print(f"   Has envelope: {hasattr(result, 'envelope')}")
print(f"   Has prov: {hasattr(result, 'prov')}")

if hasattr(result, 'envelope'):
    print(f"   Envelope keys: {list(result.envelope.keys())}")
