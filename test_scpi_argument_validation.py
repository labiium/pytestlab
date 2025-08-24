#!/usr/bin/env python3
"""
Test Script for SCPI Argument Validation

This script demonstrates the enhanced SCPI validation system that now
properly handles command arguments, parameters, and validation rules.
"""

import sys
from pathlib import Path

# Add the project root to the Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

try:
    from pytestlab.config.instrument_config import SCPICommandSpec
    from pytestlab.config.instrument_config import SCPIParameterSpec
    from pytestlab.config.instrument_config import SCPISection
    from pytestlab.config.scpi_validator import SCPIValidator
except ImportError as e:
    print(f"Error importing pytestlab modules: {e}")
    print("Make sure you're running this script from the project root directory.")
    sys.exit(1)


def test_parameter_extraction():
    """Test parameter extraction from SCPI command templates."""
    print("=== Testing Parameter Extraction ===")

    # Test single parameter
    template1 = ":CHANnel{channel}:SCALe {scale}"
    params1 = SCPIValidator.extract_parameters_from_template(template1)
    print(f"Template: {template1}")
    print(f"Parameters: {params1}")
    assert params1 == ["channel", "scale"], f"Expected ['channel', 'scale'], got {params1}"

    # Test multiple parameters in sequence
    sequence1 = [":CHANnel{channel}:SCALe {scale}", ":CHANnel{channel}:OFFSet {offset}"]
    params2 = SCPIValidator.extract_parameters_from_sequence(sequence1)
    print(f"Sequence: {sequence1}")
    print(f"Parameters: {params2}")
    assert params2 == [
        "channel",
        "scale",
        "offset",
    ], f"Expected ['channel', 'scale', 'offset'], got {params2}"

    # Test no parameters
    template2 = ":ACQuire:POINts?"
    params3 = SCPIValidator.extract_parameters_from_template(template2)
    print(f"Template: {template2}")
    print(f"Parameters: {params3}")
    assert params3 == [], f"Expected [], got {params3}"

    print("✅ Parameter extraction tests passed!\n")


def test_parameter_specification_validation():
    """Test parameter specification validation."""
    print("=== Testing Parameter Specification Validation ===")

    # Valid parameter spec
    valid_param = SCPIParameterSpec(
        name="channel",
        type="int",
        required=True,
        description="Channel number",
        min_value=1,
        max_value=4,
        default=1,
        units="channel",
    )

    # Test valid parameter
    errors = SCPIValidator._validate_parameter_spec(valid_param, "channel")
    print(f"Valid parameter 'channel': {errors}")
    assert len(errors) == 0, f"Expected no errors, got {errors}"

    # Invalid parameter spec (min > max)
    invalid_param1 = SCPIParameterSpec(
        name="scale",
        type="float",
        required=True,
        min_value=10.0,
        max_value=5.0,  # Invalid: min > max
        default=7.5,
    )

    errors1 = SCPIValidator._validate_parameter_spec(invalid_param1, "scale")
    print(f"Invalid parameter 'scale' (min > max): {errors1}")
    assert len(errors1) > 0, "Expected errors for invalid min/max values"

    # Invalid parameter spec (default out of range)
    invalid_param2 = SCPIParameterSpec(
        name="offset",
        type="float",
        required=True,
        min_value=0.0,
        max_value=5.0,
        default=10.0,  # Invalid: default > max
    )

    errors2 = SCPIValidator._validate_parameter_spec(invalid_param2, "offset")
    print(f"Invalid parameter 'offset' (default out of range): {errors2}")
    assert len(errors2) > 0, "Expected errors for default out of range"

    # Invalid enum parameter (missing allowed_values)
    invalid_param3 = SCPIParameterSpec(
        name="mode",
        type="enum",
        required=True,
        description="Trigger mode",
        # Missing allowed_values
    )

    errors3 = SCPIValidator._validate_parameter_spec(invalid_param3, "mode")
    print(f"Invalid parameter 'mode' (missing allowed_values): {errors3}")
    assert len(errors3) > 0, "Expected errors for missing allowed_values"

    print("✅ Parameter specification validation tests passed!\n")


def test_command_argument_validation():
    """Test complete command argument validation."""
    print("=== Testing Command Argument Validation ===")

    # Create a command spec with proper parameter documentation
    command_spec1 = SCPICommandSpec(
        template=":CHANnel{channel}:SCALe {scale}",
        description="Set channel scale",
        category="channel",
        feature="channels",
        parameters={
            "channel": SCPIParameterSpec(
                name="channel",
                type="int",
                required=True,
                min_value=1,
                max_value=4,
                default=1,
                units="channel",
            ),
            "scale": SCPIParameterSpec(
                name="scale",
                type="float",
                required=True,
                min_value=0.001,
                max_value=10.0,
                units="V/div",
            ),
        },
    )

    # Test well-documented command
    result1 = SCPIValidator.validate_command_arguments(command_spec1, "set_channel_scale")
    print(f"Command 'set_channel_scale' validation: {result1.is_valid}")
    print(f"  Missing parameters: {result1.missing_parameters}")
    print(f"  Invalid parameters: {result1.invalid_parameters}")
    print(f"  Warnings: {result1.warnings}")
    print(f"  Errors: {result1.errors}")
    assert result1.is_valid, f"Expected valid command, got errors: {result1.errors}"

    # Create a command spec with missing parameter documentation
    command_spec2 = SCPICommandSpec(
        sequence=[":CHANnel{channel}:SCALe {scale}", ":CHANnel{channel}:OFFSet {offset}"],
        description="Set channel axis",
        category="channel",
        feature="channels",
        parameters={
            "channel": SCPIParameterSpec(
                name="channel", type="int", required=True, min_value=1, max_value=4
            )
            # Missing 'scale' and 'offset' parameter specs
        },
    )

    # Test command with missing parameter documentation
    result2 = SCPIValidator.validate_command_arguments(command_spec2, "set_channel_axis")
    print(f"Command 'set_channel_axis' validation: {result2.is_valid}")
    print(f"  Missing parameters: {result2.missing_parameters}")
    print(f"  Invalid parameters: {result2.invalid_parameters}")
    print(f"  Warnings: {result2.warnings}")
    print(f"  Errors: {result2.errors}")
    assert not result2.is_valid, "Expected invalid command due to missing parameter docs"
    assert "scale" in result2.missing_parameters, "Expected 'scale' in missing parameters"
    assert "offset" in result2.missing_parameters, "Expected 'offset' in missing parameters"

    # Create a command spec with legacy fields
    command_spec3 = SCPICommandSpec(
        template=":TRIGger:LEVel {level}, CHANnel{channel}",
        description="Set trigger level",
        category="trigger",
        feature="trigger",
        validators={  # Legacy field
            "channel": {"min": 1, "max": 4}
        },
        enums={  # Legacy field
            "level": ["HIGH", "LOW"]
        },
    )

    # Test command with legacy fields
    result3 = SCPIValidator.validate_command_arguments(command_spec3, "set_trigger_level")
    print(f"Command 'set_trigger_level' validation: {result3.is_valid}")
    print(f"  Missing parameters: {result3.missing_parameters}")
    print(f"  Warnings: {result3.warnings}")
    assert len(result3.warnings) > 0, "Expected warnings about legacy fields"

    print("✅ Command argument validation tests passed!\n")


def test_scpi_section_validation():
    """Test validation of entire SCPI sections."""
    print("=== Testing SCPI Section Validation ===")

    # Create a complete SCPI section
    scpi_section = SCPISection(
        commands={
            "set_channel_scale": SCPICommandSpec(
                template=":CHANnel{channel}:SCALe {scale}",
                parameters={
                    "channel": SCPIParameterSpec(
                        name="channel", type="int", required=True, min_value=1, max_value=4
                    ),
                    "scale": SCPIParameterSpec(
                        name="scale", type="float", required=True, min_value=0.001, max_value=10.0
                    ),
                },
            ),
            "set_channel_offset": SCPICommandSpec(
                template=":CHANnel{channel}:OFFSet {offset}",
                parameters={
                    "channel": SCPIParameterSpec(
                        name="channel", type="int", required=True, min_value=1, max_value=4
                    ),
                    "offset": SCPIParameterSpec(
                        name="offset", type="float", required=True, min_value=-10.0, max_value=10.0
                    ),
                },
            ),
        },
        queries={
            "get_channel_scale": SCPICommandSpec(
                sequence=[":CHANnel{channel}:SCALe?"],
                parameters={
                    "channel": SCPIParameterSpec(
                        name="channel", type="int", required=True, min_value=1, max_value=4
                    )
                },
                response={"type": "float", "units": "V/div"},
            )
        },
    )

    # Validate the entire section
    results = SCPIValidator.validate_scpi_command_specifications(scpi_section)
    print("SCPI section validation results:")
    for cmd_name, result in results.items():
        print(f"  {cmd_name}: {'✅' if result.is_valid else '❌'}")
        if not result.is_valid:
            print(f"    Errors: {result.errors}")
        if result.warnings:
            print(f"    Warnings: {result.warnings}")

    # Check that all commands are valid
    all_valid = all(result.is_valid for result in results.values())
    assert all_valid, "Expected all commands to be valid"

    print("✅ SCPI section validation tests passed!\n")


def test_feature_requirement_validation():
    """Test feature requirement validation against SCPI sections."""
    print("=== Testing Feature Requirement Validation ===")

    # Create a mock config with feature requirements
    class MockConfig:
        def __init__(self):
            self.core_scpi_commands = ["acquire_points", "set_channel_axis", "get_time_axis"]
            self.channel_scpi_commands = ["channel_display", "probe_set"]
            self.trigger_scpi_commands = ["configure_trigger"]

    mock_config = MockConfig()

    # Create a mock SCPI section with some commands
    mock_scpi_section = {
        "commands": {
            "acquire_points": {},
            "set_channel_axis": {},
            "channel_display": {},
            "probe_set": {},
        },
        "queries": {"get_time_axis": {}},
        # Missing "configure_trigger" command
    }

    # Test core functionality validation
    core_result = SCPIValidator.validate_feature_requirements(
        mock_config, "core functionality", mock_config.core_scpi_commands, mock_scpi_section
    )
    print(f"Core functionality validation: {'✅' if core_result.is_valid else '❌'}")
    if not core_result.is_valid:
        print(f"  Missing commands: {core_result.missing_commands}")
    assert core_result.is_valid, "Expected core functionality to be valid"

    # Test channel functionality validation
    channel_result = SCPIValidator.validate_feature_requirements(
        mock_config, "channel operations", mock_config.channel_scpi_commands, mock_scpi_section
    )
    print(f"Channel operations validation: {'✅' if channel_result.is_valid else '❌'}")
    if not channel_result.is_valid:
        print(f"  Missing commands: {channel_result.missing_commands}")
    assert channel_result.is_valid, "Expected channel operations to be valid"

    # Test trigger functionality validation (should fail)
    trigger_result = SCPIValidator.validate_feature_requirements(
        mock_config, "trigger operations", mock_config.trigger_scpi_commands, mock_scpi_section
    )
    print(f"Trigger operations validation: {'✅' if trigger_result.is_valid else '❌'}")
    if not trigger_result.is_valid:
        print(f"  Missing commands: {trigger_result.missing_commands}")
    assert not trigger_result.is_valid, "Expected trigger operations to be invalid"
    assert (
        "configure_trigger" in trigger_result.missing_commands
    ), "Expected 'configure_trigger' to be missing"

    print("✅ Feature requirement validation tests passed!\n")


def test_real_world_example():
    """Test with a realistic SCPI command example."""
    print("=== Testing Real-World SCPI Example ===")

    # Example from DSOX1204G.scpi.json
    real_command_spec = SCPICommandSpec(
        sequence=[
            ":TRIG:SOUR {source}",
            ":TRIGger:LEVel {level}, CHANnel{channel}",
            ":TRIGger:SLOPe {slope}",
            ":TRIGger:MODE {mode}",
        ],
        description="Configure trigger for oscilloscope",
        category="trigger",
        feature="trigger",
        parameters={
            "source": SCPIParameterSpec(
                name="source",
                type="enum",
                required=True,
                description="Trigger source",
                allowed_values=["CHANnel1", "CHANnel2", "CHANnel3", "CHANnel4", "EXTernal", "LINE"],
                default="CHANnel1",
            ),
            "level": SCPIParameterSpec(
                name="level",
                type="float",
                required=True,
                description="Trigger level in volts",
                min_value=-10.0,
                max_value=10.0,
                units="V",
            ),
            "channel": SCPIParameterSpec(
                name="channel",
                type="int",
                required=True,
                description="Channel number for level setting",
                min_value=1,
                max_value=4,
                default=1,
                units="channel",
            ),
            "slope": SCPIParameterSpec(
                name="slope",
                type="enum",
                required=True,
                description="Trigger slope",
                allowed_values=["POSITIVE", "NEGATIVE", "EITHER"],
                default="POSITIVE",
            ),
            "mode": SCPIParameterSpec(
                name="mode",
                type="enum",
                required=True,
                description="Trigger mode",
                allowed_values=["EDGE", "PULSE", "RUNT"],
                default="EDGE",
            ),
        },
    )

    # Validate the real command
    result = SCPIValidator.validate_command_arguments(real_command_spec, "configure_trigger")
    print(f"Real command 'configure_trigger' validation: {'✅' if result.is_valid else '❌'}")

    if result.is_valid:
        print("  All parameters properly documented and validated")
    else:
        print(f"  Errors: {result.errors}")
        print(f"  Warnings: {result.warnings}")

    # Extract and display parameters
    params = SCPIValidator.extract_parameters_from_sequence(real_command_spec.sequence)
    print(f"  Parameters found in command: {params}")

    # Check parameter documentation coverage
    documented_params = (
        set(real_command_spec.parameters.keys()) if real_command_spec.parameters else set()
    )
    coverage = (
        len(documented_params.intersection(set(params))) / len(params) * 100 if params else 100
    )
    print(f"  Parameter documentation coverage: {coverage:.1f}%")

    assert result.is_valid, f"Expected valid real command, got errors: {result.errors}"
    assert coverage == 100.0, f"Expected 100% parameter coverage, got {coverage:.1f}%"

    print("✅ Real-world example tests passed!\n")


def main():
    """Run all tests."""
    print("🧪 SCPI Argument Validation Test Suite")
    print("=" * 50)

    try:
        test_parameter_extraction()
        test_parameter_specification_validation()
        test_command_argument_validation()
        test_scpi_section_validation()
        test_feature_requirement_validation()
        test_real_world_example()

        print("🎉 All tests passed successfully!")
        print("\nThe enhanced SCPI validation system now properly handles:")
        print("✅ Command arguments and parameters")
        print("✅ Parameter type validation")
        print("✅ Required vs optional parameters")
        print("✅ Parameter constraints (min/max values)")
        print("✅ Enum parameter validation")
        print("✅ Default value validation")
        print("✅ Parameter documentation coverage")
        print("✅ Legacy field migration warnings")

    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
