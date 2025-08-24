#!/usr/bin/env python3
"""
Test Script for Example Configuration Files
This script demonstrates the enhanced SCPI validation system with the example configurations.
"""

from pathlib import Path
from typing import Any

import yaml

from pytestlab.config.dc_active_load_config import DCActiveLoadConfig
from pytestlab.config.multimeter_config import MultimeterConfig
from pytestlab.config.power_supply_config import PowerSupplyConfig
from pytestlab.config.scpi_validator import SCPIValidator
from pytestlab.config.waveform_generator_config import WaveformGeneratorConfig


def load_yaml_config(file_path: Path) -> dict[str, Any]:
    """Load a YAML configuration file."""
    try:
        with open(file_path) as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"Error loading {file_path}: {e}")
        return {}


def test_waveform_generator_config():
    """Test the Waveform Generator configuration."""
    print("\n=== Testing Waveform Generator Configuration ===")

    config_file = Path("example_waveform_generator_config.yaml")
    if not config_file.exists():
        print(f"Configuration file {config_file} not found. Skipping test.")
        return

    config = load_yaml_config(config_file)
    if not config:
        return

    # Validate using the SCPI validator
    validator = SCPIValidator()
    results = validator.validate_waveform_generator_config(config)

    print(f"Validation completed. Found {len(results)} validation results:")

    for feature, result in results.items():
        if result.is_valid:
            print(f"  ✓ {feature}: Valid")
        else:
            print(f"  ✗ {feature}: Invalid")
            if result.errors:
                for error in result.errors:
                    print(f"    Error: {error}")
            if result.warnings:
                for warning in result.warnings:
                    print(f"    Warning: {warning}")


def test_power_supply_config():
    """Test the Power Supply configuration."""
    print("\n=== Testing Power Supply Configuration ===")

    config_file = Path("example_power_supply_config.yaml")
    if not config_file.exists():
        print(f"Configuration file {config_file} not found. Skipping test.")
        return

    config = load_yaml_config(config_file)
    if not config:
        return

    # Validate using the SCPI validator
    validator = SCPIValidator()
    results = validator.validate_power_supply_config(config)

    print(f"Validation completed. Found {len(results)} validation results:")

    for feature, result in results.items():
        if result.is_valid:
            print(f"  ✓ {feature}: Valid")
        else:
            print(f"  ✗ {feature}: Invalid")
            if result.errors:
                for error in result.errors:
                    print(f"    Error: {error}")
            if result.warnings:
                for warning in result.warnings:
                    print(f"    Warning: {warning}")


def test_dc_active_load_config():
    """Test the DC Active Load configuration."""
    print("\n=== Testing DC Active Load Configuration ===")

    config_file = Path("example_dc_active_load_config.yaml")
    if not config_file.exists():
        print(f"Configuration file {config_file} not found. Skipping test.")
        return

    config = load_yaml_config(config_file)
    if not config:
        return

    # Validate using the SCPI validator
    validator = SCPIValidator()
    results = validator.validate_dc_active_load_config(config)

    print(f"Validation completed. Found {len(results)} validation results:")

    for feature, result in results.items():
        if result.is_valid:
            print(f"  ✓ {feature}: Valid")
        else:
            print(f"  ✗ {feature}: Invalid")
            if result.errors:
                for error in result.errors:
                    print(f"    Error: {error}")
            if result.warnings:
                for warning in result.warnings:
                    print(f"    Warning: {warning}")


def test_multimeter_config():
    """Test the Multimeter configuration."""
    print("\n=== Testing Multimeter Configuration ===")

    config_file = Path("example_multimeter_config.yaml")
    if not config_file.exists():
        print(f"Configuration file {config_file} not found. Skipping test.")
        return

    config = load_yaml_config(config_file)
    if not config:
        return

    # Validate using the SCPI validator
    validator = SCPIValidator()
    results = validator.validate_multimeter_config(config)

    print(f"Validation completed. Found {len(results)} validation results:")

    for feature, result in results.items():
        if result.is_valid:
            print(f"  ✓ {feature}: Valid")
        else:
            print(f"  ✗ {feature}: Invalid")
            if result.errors:
                for error in result.errors:
                    print(f"    Error: {error}")
            if result.warnings:
                for warning in result.warnings:
                    print(f"    Warning: {warning}")


def test_automatic_instrument_detection():
    """Test automatic instrument type detection and validation."""
    print("\n=== Testing Automatic Instrument Detection ===")

    config_files = [
        "example_waveform_generator_config.yaml",
        "example_power_supply_config.yaml",
        "example_dc_active_load_config.yaml",
        "example_multimeter_config.yaml",
    ]

    validator = SCPIValidator()

    for config_file in config_files:
        file_path = Path(config_file)
        if not file_path.exists():
            print(f"Configuration file {config_file} not found. Skipping.")
            continue

        print(f"\nTesting {config_file}:")
        config = load_yaml_config(file_path)
        if not config:
            continue

        # Use automatic detection
        results = validator.validate_instrument_config(config)

        print(f"  Detected instrument type: {config.get('device_type', 'Unknown')}")
        print(f"  Validation results: {len(results)} features checked")

        valid_count = sum(1 for result in results.values() if result.is_valid)
        print(f"  Valid features: {valid_count}/{len(results)}")


def test_pydantic_model_validation():
    """Test Pydantic model validation of the configurations."""
    print("\n=== Testing Pydantic Model Validation ===")

    config_files_and_models = [
        ("example_waveform_generator_config.yaml", WaveformGeneratorConfig),
        ("example_power_supply_config.yaml", PowerSupplyConfig),
        ("example_dc_active_load_config.yaml", DCActiveLoadConfig),
        ("example_multimeter_config.yaml", MultimeterConfig),
    ]

    for config_file, model_class in config_files_and_models:
        file_path = Path(config_file)
        if not file_path.exists():
            print(f"Configuration file {config_file} not found. Skipping.")
            continue

        print(f"\nTesting {config_file} with {model_class.__name__}:")

        try:
            config = load_yaml_config(file_path)
            if not config:
                continue

            # Validate with Pydantic model
            validated_config = model_class(**config)
            print("  ✓ Pydantic validation successful")

            # Check some key attributes
            if hasattr(validated_config, "device_type"):
                print(f"  Device type: {validated_config.device_type}")
            if hasattr(validated_config, "manufacturer"):
                print(f"  Manufacturer: {validated_config.manufacturer}")
            if hasattr(validated_config, "model"):
                print(f"  Model: {validated_config.model}")

        except Exception as e:
            print(f"  ✗ Pydantic validation failed: {e}")


def main():
    """Main test function."""
    print("Enhanced SCPI Validation System - Example Configuration Tests")
    print("=" * 60)

    # Test individual configurations
    test_waveform_generator_config()
    test_power_supply_config()
    test_dc_active_load_config()
    test_multimeter_config()

    # Test automatic detection
    test_automatic_instrument_detection()

    # Test Pydantic model validation
    test_pydantic_model_validation()

    print("\n" + "=" * 60)
    print("All tests completed!")


if __name__ == "__main__":
    main()
