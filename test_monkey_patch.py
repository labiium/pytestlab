#!/usr/bin/env python
"""
Simple test to verify the monkey patching is working
"""
import pytestlab  # This should trigger compliance loading

# Check what class we get when importing from different places
from pytestlab.experiments.results import MeasurementResult as DirectMR
from pytestlab.experiments import MeasurementResult as ExperimentsMR
from pytestlab import MeasurementResult as MainMR

print(f"Direct import: {DirectMR}")
print(f"From experiments: {ExperimentsMR}")  
print(f"From main: {MainMR}")

# Test creating an instance
import numpy as np
test_values = np.array([1.0, 2.0, 3.0])

print("\nTesting direct import:")
result1 = DirectMR(test_values, "test", "V", "test")
print(f"Has envelope: {hasattr(result1, 'envelope')}")

print("\nTesting experiments import:")
result2 = ExperimentsMR(test_values, "test", "V", "test") 
print(f"Has envelope: {hasattr(result2, 'envelope')}")

print("\nTesting main import:")
result3 = MainMR(test_values, "test", "V", "test")
print(f"Has envelope: {hasattr(result3, 'envelope')}")
