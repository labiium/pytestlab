from __future__ import annotations

from pytestlab.config.scpi_schema import CommandSpec
from pytestlab.config.scpi_schema import ResponseSpec
from pytestlab.config.scpi_schema import SCPISection


def test_json_schema_generation_includes_commands_and_queries():
    scpi = SCPISection(
        commands={
            "foo": CommandSpec(template=":FOO {x}")
        },
        queries={
            "bar": CommandSpec(template=":BAR?", response=ResponseSpec(type="str"))
        },
        feature_mappings={
            "feature1": {"required_scpi": ["foo"], "optional_scpi": ["bar"]}
        }
    )
    schema = scpi.model_json_schema()
    assert "properties" in schema
    # Ensure feature_mappings present in schema
    props = schema.get("properties", {})
    assert "feature_mappings" in props



