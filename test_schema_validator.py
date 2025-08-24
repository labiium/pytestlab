#!/usr/bin/env python3
"""
Test script for the Schema Validator utility.

This script demonstrates how to use the SchemaValidator class to:
1. Get JSON schemas for instrument types
2. Validate YAML profiles against schemas
3. Ignore connection-specific fields during validation
"""

from pathlib import Path

from pytestlab.config.schema_validator import SchemaValidator


def test_schema_output():
    """Test schema output functionality."""
    print("=== Testing Schema Output ===")

    validator = SchemaValidator()

    # Test getting schema for oscilloscope
    try:
        schema = validator.get_instrument_schema("oscilloscope")
        print("✓ Successfully generated oscilloscope schema")
        print(f"  Schema length: {len(schema)} characters")

        # Verify connection fields are excluded
        if "serial_number" not in schema and "address" not in schema:
            print("✓ Connection fields (serial_number, address) properly excluded")
        else:
            print("✗ Connection fields still present in schema")

    except Exception as e:
        print(f"✗ Error generating schema: {e}")


def test_yaml_validation():
    """Test YAML validation functionality."""
    print("\n=== Testing YAML Validation ===")

    validator = SchemaValidator()

    # Test validation of example configurations
    example_files = [
        "example_oscilloscope_config.yaml",
        "example_power_supply_config.yaml",
        "example_waveform_generator_config.yaml",
        "example_dc_active_load_config.yaml",
        "example_multimeter_config.yaml",
    ]

    for yaml_file in example_files:
        file_path = Path(yaml_file)
        if not file_path.exists():
            print(f"  Skipping {yaml_file} (file not found)")
            continue

        try:
            result = validator.validate_yaml_profile(yaml_file)
            status = "✓" if result.is_valid else "✗"
            print(f"  {status} {yaml_file}: {result.instrument_type} ({result.schema_used})")

            if not result.is_valid and result.errors:
                for error in result.errors[:3]:  # Show first 3 errors
                    print(f"    Error: {error}")

        except Exception as e:
            print(f"  ✗ {yaml_file}: Error during validation - {e}")


def test_instrument_detection():
    """Test automatic instrument type detection."""
    print("\n=== Testing Instrument Type Detection ===")

    validator = SchemaValidator()

    # Test with different YAML content patterns
    test_cases = [
        {
            "content": {"device_type": "oscilloscope", "model": "DSOX1204G"},
            "expected": "oscilloscope",
        },
        {
            "content": {"model": "EDU33210"},  # No device_type, should detect from model
            "expected": "waveform_generator",
        },
        {
            "content": {"model": "E36313A"},  # Power supply model
            "expected": "power_supply",
        },
    ]

    for i, test_case in enumerate(test_cases, 1):
        try:
            detected_type = validator._detect_instrument_type(test_case["content"])
            expected = test_case["expected"]

            if detected_type == detected_type:
                print(f"  ✓ Test {i}: Correctly detected {detected_type}")
            else:
                print(f"  ✗ Test {i}: Expected {expected}, got {detected_type}")

        except Exception as e:
            print(f"  ✗ Test {i}: Error during detection - {e}")


def test_schema_info():
    """Test schema information functionality."""
    print("\n=== Testing Schema Information ===")

    validator = SchemaValidator()

    # Test getting info for different instrument types
    instrument_types = ["oscilloscope", "power_supply", "multimeter"]

    for instrument_type in instrument_types:
        try:
            info = validator.get_schema_info(instrument_type)
            print(f"  ✓ {instrument_type}:")
            print(f"    Model class: {info['model_class']}")
            print(f"  Required fields: {len(info['required_fields'])}")
            print(f"    Properties: {info['properties_count']}")
            print(f"    Excluded: {', '.join(info['excluded_fields'])}")

        except Exception as e:
            print(f"  ✗ {instrument_type}: Error getting info - {e}")


def main():
    """Main test function."""
    print("Schema Validator Test Suite")
    print("=" * 50)

    # Run all tests
    test_schema_output()
    test_yaml_validation()
    test_instrument_detection()
    test_schema_info()

    print("\n" + "=" * 50)
    print("All tests completed!")


if __name__ == "__main__":
    main()
