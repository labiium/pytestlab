# SCPI Schema System for pytestlab

This document explains the enhanced SCPI schema system that enables automated validation and schema generation for instrument configurations.

## Overview

The new system addresses the issue where the oscilloscope schema couldn't properly capture SCPI command structure and aliases from SCPI JSON files. It provides:

1. **Automated Schema Generation**: JSON schemas are automatically generated from Pydantic models
2. **SCPI Command Validation**: Ensures required SCPI commands exist for specific functionality
3. **Feature Mapping**: Declarative mapping between features and required SCPI commands
4. **Configuration Templates**: Example configurations that demonstrate proper usage

## Key Components

### 1. Enhanced Pydantic Models

#### `InstrumentConfig` (Base)
- `scpi: SCPISection` - Structured SCPI section instead of raw dict
- `SCPICommandSpec` - Individual command specifications
- `SCPICommandsQueries` - Commands and queries grouping
- `SCPISection` - Complete SCPI section with variants and feature mappings

#### `OscilloscopeConfig` (Extended)
- Feature-specific SCPI command requirements
- Core, channel, trigger, acquisition, and waveform SCPI requirements
- Integration with optional features (FFT, function generator, FRA)

### 2. SCPI Validation System

#### `SCPIValidator` Class
- Validates feature requirements against configuration
- Checks SCPI command availability
- Generates feature mapping templates
- Validates against SCPI JSON files

#### Validation Features
- **Feature-level validation**: Ensures required commands exist for specific functionality
- **Configuration validation**: Checks entire configuration against SCPI requirements
- **SCPI file validation**: Validates against actual SCPI JSON files

### 3. Automated Schema Generation

#### `generate_schemas.py` Script
- Automatically generates JSON schemas from Pydantic models
- Supports both JSON and YAML output formats
- Ensures schemas stay in sync with code changes

## Usage Examples

### 1. Generating Schemas

```bash
# Generate JSON schemas
python generate_schemas.py --output-dir schemas/ --format json

# Generate YAML schemas
python generate_schemas.py --output-dir schemas/ --format yaml
```

### 2. Validating Configurations

```python
from pytestlab.config.scpi_validator import SCPIValidator
from pytestlab.config.oscilloscope_config import OscilloscopeConfig

# Load configuration
config = OscilloscopeConfig.from_yaml("my_oscilloscope.yaml")

# Validate all SCPI requirements
results = SCPIValidator.validate_oscilloscope_config(config)

# Check specific feature
if results['fft'].is_valid:
    print("FFT functionality is properly configured")
else:
    print(f"Missing FFT commands: {results['fft'].missing_commands}")

# Validate against SCPI file
scpi_result = SCPIValidator.validate_against_scpi_file(
    config, "schemas/scpi/keysight/DSOX1204G.scpi.json"
)
```

### 3. Creating New Instrument Configurations

Use the `example_oscilloscope_config.yaml` as a template:

```yaml
# Core functionality
core_scpi_commands:
  - "acquire_points"
  - "set_channel_axis"
  - "get_time_axis"

# Feature-specific requirements
fft:
  window_types: ["HANNing", "FLATtop"]
  units: ["DECibel", "VRMS"]
  required_scpi_commands:
    - "fft_display"
    - "fft_source"
    - "fft_window"

# SCPI section with command specifications
scpi:
  commands:
    acquire_points:
      sequence: [":ACQuire:POINts?"]
      response:
        type: "int"
        units: null
  feature_mappings:
    core_oscilloscope:
      required_scpi: ["acquire_points", "set_channel_axis"]
      optional_scpi: ["acquire_set_rate"]
```

## Feature Mapping System

The system provides declarative feature mapping that groups SCPI commands by functionality:

### Core Features
- **core_oscilloscope**: Basic oscilloscope operations
- **channels**: Channel-specific operations
- **trigger**: Trigger system operations
- **acquisition**: Data acquisition operations
- **waveform**: Waveform data operations

### Optional Features
- **fft**: Fast Fourier Transform capabilities
- **function_generator**: Built-in waveform generator
- **frequency_response_analysis**: Frequency response analysis

### Mapping Structure
```yaml
feature_mappings:
  feature_name:
    required_scpi: ["command1", "command2"]  # Must exist
    optional_scpi: ["command3", "command4"]  # Nice to have
```

## Benefits

### 1. **Automated Validation**
- Prevents misconfigurations at load time
- Ensures required SCPI commands exist
- Validates feature dependencies

### 2. **Schema Consistency**
- Schemas automatically generated from code
- No manual schema maintenance
- Always up-to-date with model changes

### 3. **Configuration Templates**
- Clear examples of proper configuration
- Reusable templates for new instruments
- Documentation through examples

### 4. **Feature Discovery**
- Easy to see what SCPI commands are needed
- Clear feature dependencies
- Simplified instrument setup

## Migration Guide

### From Old System
1. **Update YAML files**: Add SCPI command requirements
2. **Add feature mappings**: Use declarative feature grouping
3. **Validate configurations**: Use new validation system

### Example Migration
```yaml
# Old: No SCPI requirements specified
fft:
  window_types: ["HANNing"]
  units: ["DECibel"]

# New: With SCPI requirements
fft:
  window_types: ["HANNing"]
  units: ["DECibel"]
  required_scpi_commands:
    - "fft_display"
    - "fft_source"
    - "fft_window"
```

## Best Practices

### 1. **Command Naming**
- Use descriptive alias names
- Follow consistent naming conventions
- Document command purposes

### 2. **Feature Grouping**
- Group related commands logically
- Separate required from optional
- Use clear feature names

### 3. **Validation**
- Always validate configurations
- Check against SCPI files
- Test feature functionality

### 4. **Documentation**
- Document command requirements
- Provide usage examples
- Keep schemas updated

## Troubleshooting

### Common Issues

1. **Missing SCPI Commands**
   - Check command aliases in SCPI JSON
   - Verify feature requirements
   - Use validation tools

2. **Schema Generation Errors**
   - Check Pydantic model syntax
   - Verify imports and dependencies
   - Run from project root

3. **Validation Failures**
   - Review required command lists
   - Check SCPI file compatibility
   - Verify feature configurations

### Debug Tools

- **SCPIValidator**: Comprehensive validation
- **Schema generation**: Automated schema updates
- **Example configs**: Working templates

## Future Enhancements

### Planned Features
- **Command dependency graphs**: Visualize command relationships
- **Automatic requirement detection**: Infer requirements from code
- **Cross-instrument validation**: Compare configurations
- **Performance optimization**: Cached validation results

### Extension Points
- **Custom validators**: User-defined validation rules
- **Plugin system**: Third-party validation modules
- **Integration APIs**: External tool integration

## Conclusion

The new SCPI schema system provides a robust foundation for instrument configuration management. It ensures consistency, enables validation, and simplifies the creation of new instrument configurations while maintaining backward compatibility.

For questions or contributions, please refer to the project documentation or create an issue in the repository.
