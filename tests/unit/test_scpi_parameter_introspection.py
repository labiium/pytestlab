import pytest

from pytestlab.config.device_config import DeviceRole
from pytestlab.config.instrument_config import InstrumentConfig
from pytestlab.config.instrument_config import SCPICommandSpec
from pytestlab.config.instrument_config import SCPISection
from pytestlab.config.operation_options import ProfileOperationOptions
from pytestlab.config.scpi_schema import SCPIChoiceSpec
from pytestlab.config.scpi_schema import SCPIParameterSpec
from pytestlab.config.scpi_validator import SCPIValidator
from pytestlab.errors import InstrumentParameterError
from pytestlab.errors import OperationDiscoveryError
from pytestlab.instruments.instrument import Instrument
from pytestlab.instruments.operation_contract import OperationDescriptor
from pytestlab.instruments.scpi_engine import SCPIEngine


class DummyBackend:
    def connect(self):
        pass

    def disconnect(self):
        pass

    def write(self, cmd: str):
        pass

    def query(self, cmd: str, delay: float | None = None) -> str:
        return "OK"

    def query_raw(self, cmd: str, delay: float | None = None) -> bytes:
        return b""

    def close(self):
        pass

    def set_timeout(self, timeout_ms: int):
        pass

    def get_timeout(self) -> int:
        return 1000


def test_engine_describes_and_resolves_profile_backed_enum_tokens():
    engine = SCPIEngine(
        {
            "commands": {
                "set_waveform": {
                    "template": "FUNC {shape}",
                    "parameters": {
                        "shape": {
                            "kind": "enum",
                            "strict": True,
                            "choices": [
                                {"token": "SIN", "label": "Sine", "aliases": ["sine"]},
                                {"token": "SQU", "label": "Square", "aliases": ["square"]},
                            ],
                        }
                    },
                }
            }
        }
    )

    assert engine.list_parameters("set_waveform") == ["shape"]
    assert [choice["token"] for choice in engine.list_options("set_waveform", "shape")] == [
        "SIN",
        "SQU",
    ]
    assert engine.resolve_parameter("set_waveform", "shape", "Sine") == "SIN"
    assert engine.build("set_waveform", shape="square") == ["FUNC SQU"]
    with pytest.raises(Exception, match="allowed set"):
        engine.build("set_waveform", shape="triangle")


def test_legacy_enums_and_validators_desugar_to_parameter_metadata():
    engine = SCPIEngine(
        {
            "commands": {
                "set_mode": {
                    "template": "MODE {mode};LEV {level}",
                    "enums": {"mode": {"cc": "CC", "cv": "CV"}},
                    "validators": {"level": {"min": 0, "max": 10}},
                }
            }
        }
    )
    described = engine.describe("set_mode")
    assert described["parameters"]["mode"]["kind"] == "enum"
    assert described["parameters"]["level"]["kind"] == "range"
    assert engine.build("set_mode", mode="cc", level=5) == ["MODE CC;LEV 5"]
    with pytest.raises(Exception, match="outside allowed range"):
        engine.build("set_mode", mode="cc", level=11)


def test_canonical_schema_and_validator_agree_on_parameter_shape():
    param = SCPIParameterSpec(kind="enum", strict=True, choices=[SCPIChoiceSpec(token="ON")])
    command = SCPICommandSpec(template="OUTP {state}", parameters={"state": param})
    result = SCPIValidator.validate_command_arguments(command, "set_output")
    assert result.is_valid, result.errors


def test_profile_binding_without_semantic_options_is_not_enumerable():
    class DummyInstrument(Instrument[InstrumentConfig]):
        OPERATION_CONTRACT = (OperationDescriptor("ambiguous"),)

    instrument = DummyInstrument(
        config=InstrumentConfig(
            manufacturer="PyTestLab",
            model="Dummy",
            device_type="instrument",
            role=DeviceRole.MEASUREMENT,
            operation_options={
                "ambiguous": {
                    "transport": {"a": "a", "b": "b"},
                    "parameters": {
                        "mode": {
                            "kind": "unresolved",
                            "bindings": [
                                {"alias": "a", "parameter": "mode"},
                                {"alias": "b", "parameter": "mode"},
                            ],
                        }
                    },
                }
            },
            scpi=SCPISection(
                commands={
                    "a": SCPICommandSpec(
                        template="A {mode}",
                        parameters={
                            "mode": SCPIParameterSpec(
                                kind="enum",
                                strict=True,
                                choices=[SCPIChoiceSpec(token="ONE", value="one")],
                            )
                        },
                    ),
                    "b": SCPICommandSpec(
                        template="B {mode}",
                        parameters={
                            "mode": SCPIParameterSpec(
                                kind="enum",
                                strict=True,
                                choices=[SCPIChoiceSpec(token="TWO", value="two")],
                            )
                        },
                    ),
                }
            ),
        ),
        backend=DummyBackend(),
    )

    with pytest.raises(OperationDiscoveryError, match="not an enumerable semantic option"):
        instrument.list_operation_options("ambiguous", "mode")


def test_instrument_config_reexports_canonical_parameter_spec():
    from pytestlab.config import instrument_config as legacy_schema
    from pytestlab.config import scpi_schema as canonical_schema

    assert legacy_schema.SCPIParameterSpec is canonical_schema.SCPIParameterSpec


def test_strict_operation_contract_rejects_inferred_placeholder_metadata():
    class DummyInstrument(Instrument[InstrumentConfig]):
        OPERATION_CONTRACT = (OperationDescriptor("set_level"),)

    instrument = DummyInstrument(
        config=InstrumentConfig(
            manufacturer="PyTestLab",
            model="Dummy",
            device_type="instrument",
            role=DeviceRole.MEASUREMENT,
            operation_options={
                "set_level": {
                    "transport": {"set_level": "set_level"},
                    "parameters": {"level": {"kind": "range"}},
                }
            },
            scpi=SCPISection(commands={"set_level": SCPICommandSpec(template="LEV {level}")}),
        ),
        backend=DummyBackend(),
    )

    with pytest.raises(RuntimeError, match="set_level.*level"):
        instrument.validate_operation_contract(strict=True, check_parameters=True)


def test_strict_operation_contract_accepts_explicit_raw_metadata_with_justification():
    class DummyInstrument(Instrument[InstrumentConfig]):
        OPERATION_CONTRACT = (OperationDescriptor("set_level"),)

    instrument = DummyInstrument(
        config=InstrumentConfig(
            manufacturer="PyTestLab",
            model="Dummy",
            device_type="instrument",
            role=DeviceRole.MEASUREMENT,
            operation_options={
                "set_level": {
                    "transport": {"set_level": "set_level"},
                    "parameters": {
                        "level": {
                            "kind": "open_string",
                            "strict": False,
                            "bindings": [{"alias": "set_level", "parameter": "level"}],
                        }
                    },
                }
            },
            scpi=SCPISection(
                commands={
                    "set_level": SCPICommandSpec(
                        template="LEV {level}",
                        parameters={
                            "level": SCPIParameterSpec(
                                kind="raw",
                                allow_raw=True,
                                description="Instrument accepted numeric level.",
                            )
                        },
                    )
                }
            ),
        ),
        backend=DummyBackend(),
    )

    report = instrument.validate_operation_contract(strict=True, check_parameters=True)
    assert report["set_level"]["supported"] is True


def test_range_binding_to_missing_placeholder_fails_strict_contract():
    class DummyInstrument(Instrument[InstrumentConfig]):
        OPERATION_CONTRACT = (OperationDescriptor("set_level"),)

    instrument = DummyInstrument(
        config=InstrumentConfig(
            manufacturer="PyTestLab",
            model="Dummy",
            device_type="instrument",
            role=DeviceRole.MEASUREMENT,
            operation_options={
                "set_level": {
                    "transport": {"set_level": "set_level"},
                    "parameters": {
                        "channel": {
                            "kind": "range",
                            "min": 0,
                            "max": 10,
                            "bindings": [{"alias": "set_level", "parameter": "channel"}],
                        },
                    },
                }
            },
            scpi=SCPISection(
                commands={
                    "set_level": SCPICommandSpec(
                        template="LEV {level}",
                        parameters={
                            "level": SCPIParameterSpec(
                                kind="raw",
                                allow_raw=True,
                                description="Instrument accepted numeric level.",
                            )
                        },
                    )
                }
            ),
        ),
        backend=DummyBackend(),
    )

    report = instrument._operation_support_report("set_level", check_parameters=True)
    assert report.supported is False
    with pytest.raises(RuntimeError, match="set_level.*channel"):
        instrument.validate_operation_contract(strict=True, check_parameters=True)


def test_profile_operation_options_preserve_semantic_metadata_and_hide_transport():
    class DummyInstrument(Instrument[InstrumentConfig]):
        OPERATION_CONTRACT = (OperationDescriptor("output_state"),)

    instrument = DummyInstrument(
        config=InstrumentConfig(
            manufacturer="PyTestLab",
            model="Dummy",
            device_type="instrument",
            role=DeviceRole.MEASUREMENT,
            operation_options={
                "output_state": {
                    "transport": {"output": "output"},
                    "parameters": {
                        "state": {
                            "kind": "enum",
                            "bindings": [{"alias": "output", "parameter": "state"}],
                            "options": [
                                {
                                    "value": "on",
                                    "label": "On",
                                    "aliases": ["enabled"],
                                    "description": "Output enabled.",
                                    "transport": {"value": "ON"},
                                }
                            ],
                        }
                    },
                }
            },
            scpi=SCPISection(commands={"output": SCPICommandSpec(template="OUT {state}")}),
        ),
        backend=DummyBackend(),
    )

    options = instrument.list_operation_options("output_state", "state")
    assert len(options) == 1
    merged = options[0]
    assert merged["value"] == "on"
    assert merged["label"] == "On"
    assert merged["aliases"] == ["enabled"]
    assert merged["description"] == "Output enabled."
    assert "token" not in merged


def test_operation_profile_rejects_ambiguous_aliases_and_dependency_cycles():
    with pytest.raises(ValueError, match="ambiguous operation option alias"):
        ProfileOperationOptions.model_validate(
            {
                "op": {
                    "mode": {
                        "kind": "enum",
                        "options": [
                            {"value": "first", "aliases": ["same"]},
                            {"value": "second", "aliases": ["same"]},
                        ],
                    }
                }
            }
        )

    with pytest.raises(ValueError, match="dependency cycle"):
        ProfileOperationOptions.model_validate(
            {
                "op": {
                    "first": {"kind": "range", "dependencies": ["second"]},
                    "second": {"kind": "range", "dependencies": ["first"]},
                }
            }
        )

    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        ProfileOperationOptions.model_validate(
            {
                "op": {
                    "mode": {
                        "kind": "enum",
                        "options": [
                            {
                                "value": "first",
                                "transport": {"value": "ONE", "alias": "set_mode"},
                            }
                        ],
                    }
                }
            }
        )


def test_discovery_errors_are_structured_and_context_is_validated():
    class SemanticInstrument(Instrument[InstrumentConfig]):
        OPERATION_CONTRACT = (OperationDescriptor("set_level"),)

    config = InstrumentConfig(
        manufacturer="Test",
        model="Semantic",
        device_type="instrument",
        role=DeviceRole.MEASUREMENT,
        operation_options={
            "set_level": {
                "transport": {"set_level": "set_level"},
                "parameters": {
                    "mode": {
                        "kind": "enum",
                        "options": [
                            {
                                "value": "constant",
                                "aliases": ["cc"],
                                "transport": {"value": "CONST"},
                            }
                        ],
                        "bindings": [{"alias": "set_level", "parameter": "mode"}],
                    },
                    "level": {
                        "kind": "range",
                        "min": 0,
                        "max": 10,
                        "dependencies": ["mode"],
                        "bindings": [{"alias": "set_level", "parameter": "level"}],
                    },
                },
            }
        },
        scpi=SCPISection(commands={"set_level": SCPICommandSpec(template="SET {mode},{level}")}),
    )
    instrument = SemanticInstrument(config, DummyBackend())

    with pytest.raises(OperationDiscoveryError) as missing:
        instrument.list_operation_options("set_level", "level")
    assert missing.value.to_dict()["error"]["code"] == "missing_dependency"

    with pytest.raises(OperationDiscoveryError) as unknown:
        instrument.describe_operation("set_level", context={"unknown": 1})
    assert unknown.value.to_dict()["error"]["code"] == "unknown_context"

    resolved = instrument._resolve_operation_parameter("set_level", "mode", "cc")
    assert resolved.value == "constant"
    assert resolved.transport_value == "CONST"

    with pytest.raises(InstrumentParameterError):
        instrument._resolve_operation_parameter("set_level", "level", 11, context={"mode": "cc"})


def test_public_operation_profile_dump_excludes_private_transport_recursively():
    options = ProfileOperationOptions.model_validate(
        {
            "set_state": {
                "state": {
                    "kind": "enum",
                    "options": [
                        {
                            "value": "enabled",
                            "transport": {
                                "value": "ON",
                            },
                        }
                    ],
                }
            }
        }
    )

    dumped = options.model_dump_public()
    assert dumped["set_state"]["state"]["options"] == [
        {
            "value": "enabled",
            "aliases": [],
            "supported": True,
            "constraints": {},
        }
    ]
    assert "ON" not in str(dumped)
