import pytest

from pytestlab.config.device_config import DeviceRole
from pytestlab.config.instrument_config import InstrumentConfig
from pytestlab.config.instrument_config import SCPICommandSpec
from pytestlab.config.instrument_config import SCPISection
from pytestlab.config.scpi_schema import SCPIChoiceSpec
from pytestlab.config.scpi_schema import SCPIParameterSpec
from pytestlab.config.scpi_validator import SCPIValidator
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


def test_operation_option_binding_rejects_ambiguous_divergent_aliases():
    class DummyInstrument(Instrument[InstrumentConfig]):
        OPERATION_CONTRACT = (
            OperationDescriptor(
                "ambiguous",
                required_aliases=("a", "b"),
                parameters={"mode": {}},
            ),
        )

    instrument = DummyInstrument(
        config=InstrumentConfig(
            manufacturer="PyTestLab",
            model="Dummy",
            device_type="instrument",
            role=DeviceRole.MEASUREMENT,
            scpi=SCPISection(
                commands={
                    "a": SCPICommandSpec(
                        template="A {mode}",
                        parameters={
                            "mode": SCPIParameterSpec(
                                kind="enum",
                                strict=True,
                                choices=[SCPIChoiceSpec(token="ONE")],
                            )
                        },
                    ),
                    "b": SCPICommandSpec(
                        template="B {mode}",
                        parameters={
                            "mode": SCPIParameterSpec(
                                kind="enum",
                                strict=True,
                                choices=[SCPIChoiceSpec(token="TWO")],
                            )
                        },
                    ),
                }
            ),
        ),
        backend=DummyBackend(),
    )

    with pytest.raises(ValueError, match="Ambiguous operation parameter"):
        instrument.list_operation_options("ambiguous", "mode")


def test_instrument_config_reexports_canonical_parameter_spec():
    from pytestlab.config import instrument_config as legacy_schema
    from pytestlab.config import scpi_schema as canonical_schema

    assert legacy_schema.SCPIParameterSpec is canonical_schema.SCPIParameterSpec


def test_strict_operation_contract_rejects_inferred_placeholder_metadata():
    class DummyInstrument(Instrument[InstrumentConfig]):
        OPERATION_CONTRACT = (OperationDescriptor("set_level", required_aliases=("set_level",)),)

    instrument = DummyInstrument(
        config=InstrumentConfig(
            manufacturer="PyTestLab",
            model="Dummy",
            device_type="instrument",
            role=DeviceRole.MEASUREMENT,
            scpi=SCPISection(commands={"set_level": SCPICommandSpec(template="LEV {level}")}),
        ),
        backend=DummyBackend(),
    )

    with pytest.raises(RuntimeError, match="set_level.level:inferred"):
        instrument.validate_operation_contract(strict=True, check_parameters=True)


def test_strict_operation_contract_accepts_explicit_raw_metadata_with_justification():
    class DummyInstrument(Instrument[InstrumentConfig]):
        OPERATION_CONTRACT = (OperationDescriptor("set_level", required_aliases=("set_level",)),)

    instrument = DummyInstrument(
        config=InstrumentConfig(
            manufacturer="PyTestLab",
            model="Dummy",
            device_type="instrument",
            role=DeviceRole.MEASUREMENT,
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


def test_strict_operation_contract_rejects_binding_that_is_not_template_placeholder():
    class DummyInstrument(Instrument[InstrumentConfig]):
        OPERATION_CONTRACT = (
            OperationDescriptor(
                "set_level",
                required_aliases=("set_level",),
                parameters={
                    "channel": {"bindings": [{"alias": "set_level", "parameter": "channel"}]}
                },
            ),
        )

    instrument = DummyInstrument(
        config=InstrumentConfig(
            manufacturer="PyTestLab",
            model="Dummy",
            device_type="instrument",
            role=DeviceRole.MEASUREMENT,
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

    with pytest.raises(RuntimeError, match="set_level.channel:binding-not-placeholder"):
        instrument.validate_operation_contract(strict=True, check_parameters=True)


def test_operation_option_merge_preserves_labels_descriptions_and_evidence():
    class DummyInstrument(Instrument[InstrumentConfig]):
        OPERATION_CONTRACT = (
            OperationDescriptor(
                "output_state",
                required_aliases=("a", "b"),
                parameters={"state": {}},
            ),
        )

    instrument = DummyInstrument(
        config=InstrumentConfig(
            manufacturer="PyTestLab",
            model="Dummy",
            device_type="instrument",
            role=DeviceRole.MEASUREMENT,
            scpi=SCPISection(
                commands={
                    "a": SCPICommandSpec(
                        template="A {state}",
                        parameters={
                            "state": SCPIParameterSpec(
                                kind="enum",
                                strict=True,
                                choices=[
                                    SCPIChoiceSpec(
                                        token="ON",
                                        label="On",
                                        aliases=["on"],
                                        description="Alias A enables output.",
                                        evidence={"source": "a"},
                                    )
                                ],
                            )
                        },
                    ),
                    "b": SCPICommandSpec(
                        template="B {state}",
                        parameters={
                            "state": SCPIParameterSpec(
                                kind="enum",
                                strict=True,
                                choices=[
                                    SCPIChoiceSpec(
                                        token="ON",
                                        label="Enabled",
                                        aliases=["enabled"],
                                        description="Alias B enables output.",
                                        evidence={"source": "b"},
                                    )
                                ],
                            )
                        },
                    ),
                }
            ),
        ),
        backend=DummyBackend(),
    )

    options = instrument.list_operation_options("output_state", "state")
    assert len(options) == 1
    merged = options[0]
    assert merged["token"] == "ON"
    assert merged["aliases"] == ["enabled", "on"]
    assert merged["labels"] == ["On", "Enabled"]
    assert merged["descriptions"] == ["Alias A enables output.", "Alias B enables output."]
    assert merged["evidence"] == [{"source": "a"}, {"source": "b"}]
