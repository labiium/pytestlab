from __future__ import annotations

import json

import pytest
import yaml
from pydantic import ValidationError
from typer.testing import CliRunner

from pytestlab import AutoInstrument
from pytestlab.cli import _semantic_operation_rows
from pytestlab.cli import app
from pytestlab.config.instrument_config import InstrumentConfig
from pytestlab.config.operation_options import ProfileOperationOptions
from pytestlab.config.schema_validator import SchemaValidator
from pytestlab.config.virtual_instrument_config import VirtualInstrumentConfig
from pytestlab.devices.base import _BackendFactory
from pytestlab.devices.factory import AutoDevice
from pytestlab.errors import InstrumentConfigurationError
from pytestlab.instruments.instrument import Instrument
from pytestlab.instruments.operation_contract import OperationDescriptor
from pytestlab.instruments.operation_contract import OperationPythonArgument
from pytestlab.instruments.profile_instrument import ProfileInstrument
from pytestlab.instruments.VirtualInstrument import VirtualInstrument


def _forbid_io(*args, **kwargs):
    pytest.fail("operation catalog must not allocate a backend or execute an operation")


class _TypedInstrument(VirtualInstrument):
    OPERATION_CONTRACT = (
        OperationDescriptor("acquire", group="measurement", scope="family"),
        OperationDescriptor("model_trace", group="measurement", scope="model"),
        OperationDescriptor("measure_vendor_option", group="measurement", scope="model"),
        OperationDescriptor("unclassified"),
    )

    acquire = model_trace = measure_vendor_option = unclassified = _forbid_io


def test_typed_catalog_reuses_descriptions_and_filters_static_support():
    instrument = _TypedInstrument(
        backend=_BackendFactory(_forbid_io),
        config=VirtualInstrumentConfig(
            manufacturer="Test",
            model="Grouped",
            device_type="virtual_instrument",
            role="measurement",
            operation_options={
                "acquire": {"parameters": {}},
                "model_trace": {"group": "trace", "parameters": {}},
            },
        ),
    )

    catalog = instrument.describe_operations()
    assert list(catalog) == ["general", "measurement", "trace"]
    unclassified = catalog["general"][-1]
    assert unclassified["operation_id"] == "unclassified"
    assert "scope" not in unclassified and "group" not in unclassified
    assert catalog["trace"] == [instrument.describe_operation("model_trace")]
    unavailable = catalog["measurement"][1]
    assert unavailable["operation_id"] == "measure_vendor_option"
    assert unavailable["support"]["supported"] is False
    assert unavailable["support"]["reason"] == "profile does not implement this operation"
    assert instrument.describe_operations(group="measurement", scope="model") == {
        "measurement": [unavailable]
    }
    assert (
        instrument.describe_operations(
            group="measurement", scope="model", include_unsupported=False
        )
        == {}
    )
    expected = {
        item["operation_id"]
        for items in instrument.describe_operations(include_unsupported=False).values()
        for item in items
    }
    assert expected == set(instrument.list_operations(include_unsupported=False))
    assert instrument.describe_operations(scope="family") == {
        "measurement": [instrument.describe_operation("acquire")]
    }


@pytest.mark.parametrize(
    "profile, operation",
    [("keysight/HD304MSO", "configure_trigger"), ("keysight/EDU33212A", "set_function")],
)
def test_legacy_typed_profiles_can_be_browsed_without_allocating_backend(
    monkeypatch, profile, operation
):
    monkeypatch.setattr(AutoDevice, "_build_backend", _forbid_io)
    instrument = AutoInstrument.from_config(profile)
    catalog = instrument.describe_operations()
    if profile == "keysight/HD304MSO":
        assert set(catalog) == {"general", "diagnostics"}
        assert [item["operation_id"] for item in catalog["diagnostics"]] == ["run_self_test"]
        assert catalog["diagnostics"][0]["python_only"] is True
    else:
        assert set(catalog) == {"general"}
    assert {item["operation_id"] for group in catalog.values() for item in group} == set(
        instrument.list_operations()
    )
    description = instrument.describe_operation(operation, include_unsupported=True)
    assert (
        next(item for item in catalog["general"] if item["operation_id"] == operation)
        == description
    )
    assert "scope" not in description and "group" not in description


def _generic_profile():
    return {
        "manufacturer": "Test",
        "model": "ProfileDevice",
        "device_type": "instrument",
        "role": "measurement",
        "scpi": {"queries": {"private_trace_alias": {"template": "PRIVATE:TRACE?"}}},
        "operation_options": {
            "read_trace": {
                "mode": "query",
                "transport": {"query": "private_trace_alias"},
                "group": "trace",
                "description": "Read the configured trace.",
                "references": ["Fixture manual, Trace page"],
            },
        },
    }


def test_cli_grouped_view_and_legacy_output_match_python_without_allocating_backend(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(AutoDevice, "_build_backend", _forbid_io)
    path = tmp_path / "catalog.yaml"
    path.write_text(yaml.safe_dump(_generic_profile()))
    instrument = AutoInstrument.from_file(path)
    runner = CliRunner()
    args = ["instrument", "list-operations", str(path)]
    legacy = runner.invoke(app, args)
    assert legacy.exit_code == 0, legacy.output
    assert json.loads(legacy.stdout) == instrument.list_operations()

    result = runner.invoke(app, [*args, "--group", "trace", "--scope", "model", "--supported-only"])
    assert result.exit_code == 0, result.output
    catalog = json.loads(result.stdout)
    assert catalog == instrument.describe_operations(
        group="trace", scope="model", include_unsupported=False
    )
    description = instrument.describe_operation("read_trace")
    assert catalog == {"trace": [{**description, "scope": "model"}]}
    assert "scope" not in description
    assert description["description"] == "Read the configured trace."
    assert description["references"] == ["Fixture manual, Trace page"]
    assert description["method"] == "execute_profile_operation"
    assert "PRIVATE:TRACE?" not in result.stdout
    assert "private_trace_alias" not in result.stdout

    result = runner.invoke(app, [*args, "--grouped"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == instrument.describe_operations()

    bad_scope = runner.invoke(app, [*args, "--scope", "bogus"])
    assert bad_scope.exit_code == 1
    assert json.loads(bad_scope.stdout)["error"]["code"] == "operation_error"


def test_profile_catalog_metadata_survives_internal_round_trip():
    options = ProfileOperationOptions.model_validate(_generic_profile()["operation_options"])
    rebuilt = ProfileOperationOptions.model_validate(options.model_dump_internal())
    assert rebuilt == options
    assert rebuilt.model_dump_public()["read_trace"]["group"] == "trace"
    assert "transport" not in rebuilt.model_dump_public()["read_trace"]


def test_concise_parameter_names_remain_valid_and_invalid_group_is_rejected():
    options = ProfileOperationOptions.model_validate(
        {"configure": {"group": {"kind": "open_string"}, "description": {"kind": "open_string"}}}
    )
    assert set(options.operation("configure").parameters) == {"group", "description"}
    assert options.operation("configure").discovery_metadata() == {}
    with pytest.raises(ValidationError, match="group"):
        ProfileOperationOptions.model_validate({"read_trace": {"group": "invalid group"}})


def test_generated_profile_schema_includes_optional_catalog_metadata():
    schema = json.loads(SchemaValidator().get_device_schema("vector_network_analyzer"))
    spec = schema["$defs"]["ProfileOperationSpec"]
    assert {"group", "description", "references"} <= spec["properties"].keys()
    assert not {"group", "description", "references"} & set(spec.get("required", []))


class _CallerRecord:
    pass


class _PythonOnlyInstrument(Instrument[VirtualInstrumentConfig]):
    OPERATION_CONTRACT = (
        OperationDescriptor(
            "acquire_commissioned",
            group="acquisition",
            scope="model",
            python_arguments=(
                OperationPythonArgument(
                    "record", "CommissioningRecord", description="Current fixture commissioning."
                ),
            ),
        ),
    )

    def acquire_commissioned(self, record: _CallerRecord) -> str:
        if not isinstance(record, _CallerRecord):
            raise TypeError("A caller-supplied commissioning record is required")
        return "sample"


@pytest.fixture
def python_only_instrument():
    return _PythonOnlyInstrument(
        backend=_BackendFactory(_forbid_io),
        config=VirtualInstrumentConfig(
            manufacturer="Test",
            model="Grouped",
            device_type="virtual_instrument",
            role="measurement",
            operation_options={"acquire_commissioned": {"parameters": {}}},
        ),
    )


def test_catalog_names_required_python_type_without_enabling_generic_arguments(
    python_only_instrument,
):
    instrument = python_only_instrument
    expected = instrument.describe_operation("acquire_commissioned")
    assert instrument.describe_operations(include_unsupported=False) == {"acquisition": [expected]}
    assert expected["support"]["supported"] is True
    assert expected["python_only"] is True
    assert expected["python_arguments"] == [
        {
            "name": "record",
            "type_name": "CommissioningRecord",
            "description": "Current fixture commissioning.",
            "required": True,
        }
    ]
    assert expected["parameters"] == {}
    assert "python_only" not in instrument.describe_operation("reset")
    assert "python_arguments" not in instrument.describe_operation("reset")
    assert instrument.acquire_commissioned(_CallerRecord()) == "sample"


def test_generic_execution_and_full_test_reject_opaque_context_before_call(
    monkeypatch, python_only_instrument
):
    instrument = python_only_instrument
    monkeypatch.setattr("pytestlab.cli_typer._operation_instrument", lambda *a, **kw: instrument)
    monkeypatch.setattr("pytestlab.cli_typer._load_instrument_profile", lambda path: instrument)
    monkeypatch.setattr(instrument, "acquire_commissioned", _forbid_io)
    monkeypatch.setattr(instrument, "_resolve_operation_arguments", _forbid_io)
    runner = CliRunner()
    catalog = runner.invoke(app, ["instrument", "list-operations", "fixture", "--grouped"])
    assert catalog.exit_code == 0, catalog.output
    assert json.loads(catalog.stdout)["acquisition"][0]["python_only"] is True

    result = runner.invoke(
        app,
        [
            "instrument",
            "execute-operation",
            "fixture",
            "acquire_commissioned",
            "--params",
            '{"record": {"provided": true}}',
        ],
    )
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error"]["code"] == "python_only_operation"

    rows, failures, warnings, _ = _semantic_operation_rows(instrument, include_writes=True)
    assert failures == warnings == 0
    row = next(row for row in rows if row["alias"] == "acquire_commissioned")
    assert row["status"] == "skip"
    assert "Python objects" in row["detail"]


def test_profile_cannot_declare_python_object_arguments():
    with pytest.raises(ValidationError, match="python_arguments"):
        ProfileOperationOptions.model_validate(
            {"acquire": {"parameters": {}, "python_arguments": [{"type_name": "example.Type"}]}}
        )


def test_profile_driver_cannot_use_a_generic_alias_for_a_python_only_descriptor():
    class Driver(ProfileInstrument):
        OPERATION_CONTRACT = (
            OperationDescriptor(
                "read_trace",
                python_arguments=(OperationPythonArgument("record", "CommissioningRecord"),),
            ),
        )

    instrument = Driver(
        backend=_BackendFactory(_forbid_io),
        config=InstrumentConfig.model_validate(_generic_profile()),
    )
    with pytest.raises(InstrumentConfigurationError, match="caller-provided Python objects"):
        instrument.execute_profile_operation("read_trace")
