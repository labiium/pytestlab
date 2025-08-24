# Schema Validation Utility for pytestlab

The `SchemaValidator` utility provides comprehensive functionality to output JSON schemas for instrument types and validate YAML profiles against those schemas, while intelligently ignoring connection-specific fields. It is integrated into the main pytestlab CLI under the `profile` section.

## Features

- **Schema Generation**: Output JSON schemas for any supported instrument type
- **YAML Validation**: Validate YAML configuration files against appropriate schemas
- **Connection Field Exclusion**: Automatically ignores `serial_number` and `address` fields during validation
- **Automatic Instrument Detection**: Detects instrument type from YAML content when not specified
- **Comprehensive Error Reporting**: Detailed validation errors and warnings
- **Integrated CLI**: Available through the main pytestlab CLI under `profile` commands

## Supported Instrument Types

The validator supports all major instrument types with common aliases:

| Primary Name | Aliases | Configuration Class |
|--------------|---------|-------------------|
| `oscilloscope` | - | `OscilloscopeConfig` |
| `waveform_generator` | `awg` | `WaveformGeneratorConfig` |
| `power_supply` | `psu` | `PowerSupplyConfig` |
| `dc_active_load` | `electronic_load` | `DCActiveLoadConfig` |
| `multimeter` | `dmm` | `MultimeterConfig` |

## Installation

The `SchemaValidator` is part of the pytestlab package and is available at:

```python
from pytestlab.config.schema_validator import SchemaValidator
```

## Usage

### Integrated CLI (Recommended)

The schema validation functionality is now integrated into the main pytestlab CLI under the `profile` section:

```bash
# List all supported instrument types
pytestlab profile list-schemas

# Get schema information for an instrument type
pytestlab profile schema-info oscilloscope

# Output JSON schema for an instrument type
pytestlab profile schema power_supply
pytestlab profile schema multimeter --output multimeter_schema.json

# Validate a YAML profile
pytestlab profile validate-schema my_instrument.yaml
pytestlab profile validate-schema my_instrument.yaml --instrument-type oscilloscope
```

### Python API

#### Basic Usage

```python
from pytestlab.config.schema_validator import SchemaValidator

# Initialize the validator
validator = SchemaValidator()

# Get a JSON schema for an instrument type
schema = validator.get_instrument_schema("oscilloscope")
print(schema)

# Validate a YAML profile
result = validator.validate_yaml_profile("my_instrument.yaml")
if result.is_valid:
    print("Configuration is valid!")
else:
    print("Validation errors:")
    for error in result.errors:
        print(f"  - {error}")
```

#### Schema Generation

```python
# Get formatted JSON schema
schema = validator.get_instrument_schema("power_supply", format_output=True)

# Get compact JSON schema
schema = validator.get_instrument_schema("power_supply", format_output=False)

# Save schema to file
schema = validator.get_instrument_schema("multimeter")
with open("multimeter_schema.json", "w") as f:
    f.write(schema)
```

#### YAML Validation

```python
# Validate with automatic instrument type detection
result = validator.validate_yaml_profile("instrument_config.yaml")

# Validate with explicit instrument type
result = validator.validate_yaml_profile("instrument_config.yaml", "oscilloscope")

# Check validation results
print(f"Valid: {result.is_valid}")
print(f"Instrument type: {result.instrument_type}")
print(f"Schema used: {result.schema_used}")

if result.errors:
    print("Errors:")
    for error in result.errors:
        print(f"  - {error}")

if result.warnings:
    print("Warnings:")
    for warning in result.warnings:
        print(f"  - {warning}")
```

#### Schema Information

```python
# Get schema metadata without full content
info = validator.get_schema_info("waveform_generator")
print(f"Model class: {info['model_class']}")
print(f"Required fields: {info['required_fields']}")
print(f"Properties count: {info['properties_count']}")
print(f"Excluded fields: {info['excluded_fields']}")

# List all supported instrument types
instruments = validator.list_supported_instruments()
print(f"Supported types: {instruments}")
```



## Connection Field Handling

The validator automatically handles connection-specific fields that are not part of the instrument type specification:

### Excluded Fields

- **`serial_number`**: Instrument instance identifier (for connection)
- **`address`**: Connection address/interface (for connection)

### Why Exclude These Fields?

- **`serial_number`**: Varies per instrument instance, not per instrument type
- **`address`**: Connection-specific, not part of instrument capabilities
- **Runtime vs Schema**: These fields are needed for `AutoInstrument` connection but shouldn't be in validation schemas

### Example

```yaml
# This YAML will validate successfully
manufacturer: "Keysight"
model: "DSOX1204G"
device_type: "oscilloscope"
# serial_number: "MY12345678"  # Ignored during validation
# address: "USB0::0x0957::0x0607::MY12345678::INSTR"  # Ignored during validation

# Instrument capabilities (validated)
channels:
  - description: "Channel 1"
    # ... channel specifications
```

## Automatic Instrument Type Detection

When no instrument type is specified, the validator automatically detects it from YAML content:

### Detection Methods

1. **`device_type` field**: Primary detection method
2. **Model name patterns**: Fallback detection from model names

### Detection Patterns

| Pattern | Detected Type |
|---------|---------------|
| `dso`, `mso`, `scope` | `oscilloscope` |
| `awg`, `waveform`, `func` | `waveform_generator` |
| `psu`, `power`, `supply` | `power_supply` |
| `load`, `electronic` | `dc_active_load` |
| `dmm`, `multimeter`, `3446` | `multimeter` |

### Example

```yaml
# No device_type specified, but model suggests oscilloscope
manufacturer: "Keysight"
model: "DSOX1204G"  # "dso" pattern detected
# ... rest of configuration
```

## Error Handling

The validator provides comprehensive error reporting:

### Validation Errors

- **Field validation errors**: Type mismatches, missing required fields, etc.
- **Schema errors**: Invalid structure, unsupported fields
- **YAML parsing errors**: Malformed YAML syntax

### Error Format

```
field_path: error_message
```

Examples:
```
channels.0.frequency_range.min: field required
measurement.voltage_accuracy.percent_reading: field required
```

## Integration Examples

### CI/CD Pipeline Validation

```bash
#!/bin/bash
# Validate all instrument configurations in a directory

for yaml_file in configs/*.yaml; do
    echo "Validating $yaml_file..."
    if python -m pytestlab.config.schema_validator validate --yaml-file "$yaml_file"; then
        echo "✓ $yaml_file is valid"
    else
        echo "✗ $yaml_file has validation errors"
        exit 1
    fi
done
```

### Schema Generation for Documentation

```bash
#!/bin/bash
# Generate schemas for all instrument types

mkdir -p schemas
for instrument_type in oscilloscope waveform_generator power_supply dc_active_load multimeter; do
    python -m pytestlab.config.schema_validator schema \
        --instrument-type "$instrument_type" \
        --output-file "schemas/${instrument_type}_schema.json"
done
```

### Python Script Integration

```python
import os
from pathlib import Path
from pytestlab.config.schema_validator import SchemaValidator

def validate_config_directory(config_dir: str) -> dict:
    """Validate all YAML files in a directory."""
    validator = SchemaValidator()
    results = {}

    for yaml_file in Path(config_dir).glob("*.yaml"):
        try:
            result = validator.validate_yaml_profile(yaml_file)
            results[yaml_file.name] = {
                "valid": result.is_valid,
                "instrument_type": result.instrument_type,
                "errors": result.errors
            }
        except Exception as e:
            results[yaml_file.name] = {
                "valid": False,
                "error": str(e)
            }

    return results

# Usage
results = validate_config_directory("instrument_configs/")
for filename, result in results.items():
    status = "✓" if result["valid"] else "✗"
    print(f"{status} {filename}: {result.get('instrument_type', 'Unknown')}")
```

## Best Practices

### 1. Use Explicit Instrument Types

```yaml
# Good: Explicit instrument type
device_type: "oscilloscope"

# Avoid: Relying on automatic detection
# (model: "DSOX1204G" will work but is less reliable)
```

### 2. Separate Connection from Configuration

```yaml
# Connection information (ignored during validation)
serial_number: "MY12345678"
address: "USB0::0x0957::0x0607::MY12345678::INSTR"

# Instrument configuration (validated)
device_type: "oscilloscope"
channels:
  - description: "Channel 1"
    # ... specifications
```

### 3. Validate Early and Often

```bash
# Validate during development
python -m pytestlab.config.schema_validator validate --yaml-file my_config.yaml

# Validate before committing
git diff --cached --name-only | grep '\.yaml$' | xargs -I {} \
    python -m pytestlab.config.schema_validator validate --yaml-file {}
```

### 4. Use Schema Information for Documentation

```python
# Generate schema documentation
validator = SchemaValidator()
for instrument_type in validator.list_supported_instruments():
    info = validator.get_schema_info(instrument_type)
    print(f"## {instrument_type.title()}")
    print(f"Required fields: {', '.join(info['required_fields'])}")
    print(f"Total properties: {info['properties_count']}")
```

## Troubleshooting

### Common Issues

1. **Import Errors**: Ensure pytestlab is properly installed and in your Python path
2. **YAML Parsing Errors**: Check YAML syntax with a YAML validator
3. **Validation Errors**: Review the error messages for specific field issues
4. **Instrument Type Detection**: Use explicit `device_type` fields for reliable detection

### Debug Mode

For detailed debugging, you can access the internal methods:

```python
validator = SchemaValidator()

# Check what instrument type would be detected
yaml_content = {"model": "DSOX1204G"}
detected_type = validator._detect_instrument_type(yaml_content)
print(f"Detected type: {detected_type}")

# See what fields are excluded
schema = validator.get_instrument_schema("oscilloscope")
# Connection fields are automatically removed
```

## Contributing

To add support for new instrument types:

1. Create the configuration model in `pytestlab/config/`
2. Add the model to `INSTRUMENT_MODELS` in `SchemaValidator`
3. Update detection patterns if needed
4. Add tests for the new instrument type

## License

This utility is part of the pytestlab project and follows the same license terms.
