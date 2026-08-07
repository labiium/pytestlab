from __future__ import annotations

import pytest

from pytestlab import AutoInstrument
from pytestlab.config.scpi_schema import ResponseSpec
from pytestlab.instruments.operation_contract import OperationDescriptor
from pytestlab.instruments.scpi_engine import _PARSER_REGISTRY


def test_operation_introspection_reports_profile_support() -> None:
    scope = AutoInstrument.from_config("keysight/DSOX1204G", simulate=True)

    operations = scope.list_operations()
    assert "configure_trigger" in operations
    assert scope.supports_operation("configure_trigger") is True

    descriptor = scope.describe_operation("configure_trigger")
    assert descriptor["required_aliases"] == ["configure_trigger"]
    assert descriptor["support"]["supported"] is True


def test_hd304_profile_exposes_direct_voltage_measurements() -> None:
    scope = AutoInstrument.from_config("keysight/HD304MSO", simulate=True)

    assert scope.scpi_engine.build("measure_vpp", channel=1) == [":MEASure:VPP? CHANnel1"]
    assert scope.scpi_engine.build("measure_vrms", channel=2) == [
        ":MEASure:VRMS? CYCLe,AC,CHANnel2"
    ]


def test_operation_contract_reports_missing_aliases_without_hardcoding_vendor_logic() -> None:
    scope = AutoInstrument.from_config("keysight/HD304MSO", simulate=True)

    report = scope.operation_support_report("wave_generator_basic")

    assert report.capability_enabled is True
    assert report.supported is False
    assert {"wgen_set_freq", "wgen_set_volt"}.issubset(report.missing_required_aliases)


def test_operation_contract_strict_mode_only_raises_on_required_missing_aliases() -> None:
    scope = AutoInstrument.from_config("keysight/HD304MSO", simulate=True)

    scope.validate_operation_contract(strict=True)

    scope_type = type(scope)
    original_contract = scope_type.OPERATION_CONTRACT
    try:
        scope_type.OPERATION_CONTRACT = original_contract + (
            OperationDescriptor("required_missing", required_aliases=("definitely_missing",)),
        )
        scope.validate_operation_contract(strict=True)
    except RuntimeError as exc:
        assert "required_missing" in str(exc)
    else:
        pytest.fail("strict operation contract should fail for required missing aliases")
    finally:
        scope_type.OPERATION_CONTRACT = original_contract


def test_scpi_schema_parser_literals_include_engine_parsers() -> None:
    response_type_field = ResponseSpec.model_fields["type"]
    literal_values = set(response_type_field.annotation.__args__)

    assert set(_PARSER_REGISTRY).issubset(literal_values)
