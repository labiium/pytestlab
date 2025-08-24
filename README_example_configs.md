# Enhanced SCPI Validation System - Example Configurations

This directory contains comprehensive example configuration files that demonstrate the enhanced SCPI validation system for various instrument types. These examples show how to properly structure instrument configurations with detailed SCPI command requirements and argument specifications.

## Overview

The enhanced SCPI validation system provides:

1. **Structured SCPI Command Requirements**: Clear lists of required SCPI commands for different instrument features
2. **Detailed Argument Specifications**: Complete parameter definitions with types, ranges, and validation rules
3. **Feature-Based Validation**: Validation of SCPI commands based on specific instrument capabilities
4. **Automated Schema Generation**: JSON schemas generated from Pydantic models for validation
5. **Comprehensive Testing**: Test scripts to verify the validation system works correctly

## Example Configuration Files

### 1. Waveform Generator (`example_waveform_generator_config.yaml`)

**Instrument Type**: Arbitrary Waveform Generator (AWG)
**Example Model**: Keysight EDU33210
**Key Features**:
- Multiple output channels with frequency, amplitude, and phase control
- Built-in waveform types (SIN, SQU, RAMP, PULS, NOIS, ARB, DC)
- Arbitrary waveform support with configurable sampling rates
- Modulation capabilities (AM, FM)
- Frequency sweep and burst modes
- Trigger and synchronization features

**SCPI Command Categories**:
- `core_scpi_commands`: Basic functionality (output state, voltage units, limits)
- `output_scpi_commands`: Output control (polarity, sync output)
- `sync_scpi_commands`: Phase synchronization and reference
- `memory_scpi_commands`: File and memory management

### 2. Power Supply (`example_power_supply_config.yaml`)

**Instrument Type**: Programmable Power Supply
**Example Model**: Keysight E36313A
**Key Features**:
- Multiple output channels with different voltage/current ranges
- Comprehensive protection features (voltage, current, power, temperature)
- High-accuracy measurement capabilities
- Multiple interface support (USB, LAN, GPIB)

**SCPI Command Categories**:
- `core_scpi_commands`: Basic functionality (output state, units, autorange)
- `output_scpi_commands`: Output control and protection
- `safety_scpi_commands`: Protection level settings and delays

### 3. DC Active Load (`example_dc_active_load_config.yaml`)

**Instrument Type**: Electronic Load
**Example Model**: Keysight N3300A
**Key Features**:
- Multiple operating modes (CC, CV, CP, CR)
- Transient testing capabilities
- Battery testing with configurable discharge curves
- High-speed data acquisition
- Comprehensive protection features

**SCPI Command Categories**:
- `core_scpi_commands`: Basic functionality (input state, units, autorange)
- `input_scpi_commands`: Input control and protection
- `slew_rate_scpi_commands`: Slew rate control for smooth transitions
- `measurement_scpi_commands`: Input measurement capabilities

### 4. Multimeter (`example_multimeter_config.yaml`)

**Instrument Type**: Digital Multimeter (DMM)
**Example Model**: Keysight 34465A
**Key Features**:
- Multiple measurement functions (DC/AC voltage/current, resistance, frequency, etc.)
- High-accuracy measurements with configurable ranges and resolution
- Advanced triggering and sampling capabilities
- Comprehensive calibration management

**SCPI Command Categories**:
- `core_scpi_commands`: Basic functionality (measurement function, range, resolution)
- `measurement_scpi_commands`: Measurement control and statistics
- `configuration_scpi_commands`: Calibration and configuration settings
- `status_scpi_commands`: Status queries and error handling

## Key Components of Each Configuration

### 1. Instrument Identification
```yaml
manufacturer: "Keysight"
model: "MODEL_NAME"
device_type: "instrument_type"
serial_number: "SERIAL_NUMBER"
address: "INTERFACE_ADDRESS"
```

### 2. SCPI Command Requirements
Each configuration includes categorized lists of required SCPI commands:
```yaml
core_scpi_commands:
  - "command_alias_1"
  - "command_alias_2"

feature_specific_scpi_commands:
  - "feature_command_1"
  - "feature_command_2"
```

### 3. Feature Specifications
Detailed specifications for each instrument capability:
```yaml
feature_name:
  parameter_ranges:
    min: value
    max: value
    units: "unit"
  required_scpi_commands:
    - "required_command_1"
    - "required_command_2"
```

### 4. SCPI Command Definitions
Detailed SCPI command specifications with parameter definitions:
```yaml
scpi:
  commands:
    command_alias:
      template: "SCPI_COMMAND {parameter}"
      description: "Command description"
      category: "command_category"
      feature: "feature_name"
      parameters:
        parameter:
          name: "parameter_name"
          type: "parameter_type"
          required: true
          min_value: min_val
          max_value: max_val
          description: "Parameter description"
          units: "parameter_units"
```

## Using the Example Configurations

### 1. As Templates for New Instruments
Use these examples as starting points for configuring new instruments:

1. Copy the appropriate example file
2. Modify the instrument identification details
3. Adjust the SCPI command requirements based on your instrument's capabilities
4. Update the feature specifications to match your instrument
5. Modify the SCPI command definitions to use your instrument's actual SCPI commands

### 2. For Validation Testing
Use these configurations to test the SCPI validation system:

```python
from pytestlab.config.scpi_validator import SCPIValidator
import yaml

# Load configuration
with open('example_waveform_generator_config.yaml', 'r') as f:
    config = yaml.safe_load(f)

# Validate the configuration
validator = SCPIValidator()
results = validator.validate_instrument_config(config)

# Check results
for feature, result in results.items():
    if result.is_valid:
        print(f"{feature}: Valid ✓")
    else:
        print(f"{feature}: Invalid ✗")
        for error in result.errors:
            print(f"  Error: {error}")
```

### 3. For Schema Generation
Generate JSON schemas from these configurations:

```bash
python generate_schemas.py --output-dir schemas --format json
```

This will create validation schemas that can be used to validate YAML configuration files.

## Validation Features

### 1. SCPI Command Validation
- Ensures all required SCPI commands are defined
- Validates command aliases against SCPI definition files
- Checks for missing or undefined commands

### 2. Argument Validation
- Extracts parameters from SCPI command templates
- Validates parameter specifications (types, ranges, required status)
- Ensures parameter documentation matches command usage

### 3. Feature Requirement Validation
- Validates that required SCPI commands exist for each feature
- Checks feature dependencies and requirements
- Ensures consistent command usage across features

### 4. Configuration Completeness
- Validates that all required fields are present
- Checks for proper data types and value ranges
- Ensures configuration consistency

## Best Practices

### 1. Command Naming
- Use descriptive, consistent command aliases
- Group related commands logically
- Maintain clear naming conventions

### 2. Parameter Documentation
- Document all command parameters thoroughly
- Include units, ranges, and validation rules
- Provide clear descriptions for each parameter

### 3. Feature Organization
- Group related features logically
- Maintain clear feature hierarchies
- Document feature dependencies

### 4. SCPI Command Mapping
- Map command aliases to actual SCPI commands
- Include both simple commands and command sequences
- Document command responses and expected formats

## Troubleshooting

### Common Issues

1. **Missing SCPI Commands**: Ensure all required commands are defined in the SCPI section
2. **Parameter Mismatches**: Check that parameter names in templates match parameter definitions
3. **Feature Dependencies**: Verify that required SCPI commands exist for each feature
4. **Validation Errors**: Use the test scripts to identify and fix validation issues

### Debugging Tips

1. **Use the Test Scripts**: Run `simple_test_scpi.py` to test basic functionality
2. **Check Validation Results**: Examine validation output for specific error messages
3. **Verify SCPI Definitions**: Ensure SCPI command aliases match your instrument's capabilities
4. **Test Incrementally**: Validate individual features before testing the complete configuration

## Integration with Existing Systems

### 1. Pydantic Models
These configurations are based on Pydantic models that provide:
- Type validation and conversion
- Automatic schema generation
- Runtime validation of configuration data

### 2. JSON Schema Validation
Generated schemas can be used with:
- YAML validation tools
- Configuration management systems
- CI/CD pipelines for configuration validation

### 3. Instrument Drivers
These configurations integrate with:
- Python instrument drivers
- Test automation frameworks
- Configuration management systems

## Future Enhancements

### 1. Additional Instrument Types
- Spectrum analyzers
- Network analyzers
- Logic analyzers
- Protocol analyzers

### 2. Enhanced Validation
- Cross-instrument compatibility checking
- Performance validation
- Security validation

### 3. Automation Features
- Automatic configuration generation from instrument manuals
- Configuration migration tools
- Validation rule customization

## Support and Contributing

For questions, issues, or contributions:

1. **Documentation**: Refer to the main project documentation
2. **Issues**: Report bugs or request features through the project issue tracker
3. **Contributions**: Submit pull requests for improvements or new instrument types
4. **Testing**: Help test configurations with different instruments

## Conclusion

These example configurations demonstrate the power and flexibility of the enhanced SCPI validation system. They provide a solid foundation for creating robust, validated instrument configurations that ensure proper functionality and maintainability.

By following these examples and best practices, you can create comprehensive instrument configurations that:
- Clearly define SCPI command requirements
- Provide detailed parameter specifications
- Enable automated validation
- Support multiple instrument types
- Facilitate configuration management and maintenance

The system is designed to be extensible, allowing you to add new instrument types and validation rules as needed for your specific use cases.
