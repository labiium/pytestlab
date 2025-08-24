#!/usr/bin/env python3
"""
Schema Generation Script for pytestlab

This script automatically generates JSON/YAML schemas from Pydantic models
to ensure schemas stay in sync with code changes.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Add the project root to the Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

try:
    from pytestlab.config.dc_active_load_config import DCActiveLoadConfig
    from pytestlab.config.instrument_config import InstrumentConfig
    from pytestlab.config.instrument_config import SCPICommandSpec
    from pytestlab.config.instrument_config import SCPICommandsQueries
    from pytestlab.config.instrument_config import SCPIParameterSpec
    from pytestlab.config.instrument_config import SCPISection
    from pytestlab.config.multimeter_config import MultimeterConfig
    from pytestlab.config.oscilloscope_config import OscilloscopeConfig
    from pytestlab.config.power_supply_config import PowerSupplyConfig
    from pytestlab.config.waveform_generator_config import WaveformGeneratorConfig
except ImportError as e:
    print(f"Error importing pytestlab modules: {e}")
    print("Make sure you're running this script from the project root directory.")
    sys.exit(1)


def generate_schema(model_class: Any, output_path: Path, format_type: str = "json") -> None:
    """
    Generate a schema for a Pydantic model and save it to a file.

    Args:
        model_class: The Pydantic model class to generate schema for
        output_path: Path where to save the schema file
        format_type: Output format ('json' or 'yaml')
    """
    try:
        # Generate the JSON schema
        schema = model_class.model_json_schema()

        # Remove serial_number from properties if it exists (for schema validation)
        # This field is needed for runtime but shouldn't be in validation schemas
        if "properties" in schema and "serial_number" in schema["properties"]:
            del schema["properties"]["serial_number"]
            # Also remove from required fields if it was there
            if "required" in schema and "serial_number" in schema["required"]:
                schema["required"].remove("serial_number")

        # Save in the specified format
        if format_type.lower() == "json":
            with open(output_path, "w") as f:
                json.dump(schema, f, indent=2)
        elif format_type.lower() == "yaml":
            import yaml

            with open(output_path, "w") as f:
                yaml.dump(schema, f, default_flow_style=False, indent=2)
        else:
            raise ValueError(f"Unsupported format: {format_type}")

        print(f"Generated {format_type.upper()} schema: {output_path}")

    except Exception as e:
        print(f"Error generating schema for {model_class.__name__}: {e}")


def generate_all_schemas(output_dir: Path, format_type: str = "json") -> None:
    """
    Generate schemas for all key Pydantic models.

    Args:
        output_dir: Directory where to save the schema files
        format_type: Output format ('json' or 'yaml')
    """
    # Ensure output directory exists
    output_dir.mkdir(parents=True, exist_ok=True)

    # Define the models to generate schemas for
    models = [
        (InstrumentConfig, "instrument_config"),
        (SCPISection, "scpi_section"),
        (SCPICommandSpec, "scpi_command_spec"),
        (SCPIParameterSpec, "scpi_parameter_spec"),
        (SCPICommandsQueries, "scpi_commands_queries"),
        (OscilloscopeConfig, "oscilloscope"),
        (WaveformGeneratorConfig, "waveform_generator"),
        (PowerSupplyConfig, "power_supply"),
        (DCActiveLoadConfig, "dc_active_load"),
        (MultimeterConfig, "multimeter"),
    ]

    # Generate schemas for each model
    for model_class, filename in models:
        output_path = output_dir / f"{filename}.{format_type}"
        generate_schema(model_class, output_path, format_type)

    print("\nSchema generation complete!")


def main():
    """Main function to parse arguments and generate schemas."""
    parser = argparse.ArgumentParser(description="Generate JSON/YAML schemas from Pydantic models")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("schemas"),
        help="Output directory for generated schemas (default: schemas/)",
    )
    parser.add_argument(
        "--format", choices=["json", "yaml"], default="json", help="Output format (default: json)"
    )

    args = parser.parse_args()

    print(f"Generating schemas in {args.format.upper()} format...")
    print(f"Output directory: {args.output_dir}")
    print("-" * 50)

    generate_all_schemas(args.output_dir, args.format)


if __name__ == "__main__":
    main()
