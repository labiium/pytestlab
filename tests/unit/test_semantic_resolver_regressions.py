from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import yaml
from pydantic import ValidationError

from pytestlab import AutoInstrument
from pytestlab.config.operation_options import ProfileOperationOptions
from pytestlab.config.virtual_instrument_config import VirtualInstrumentConfig
from pytestlab.errors import InstrumentConfigurationError
from pytestlab.errors import InstrumentParameterError
from pytestlab.errors import OperationDiscoveryError
from pytestlab.instruments.operation_contract import OperationDescriptor
from pytestlab.instruments.operation_resolver import OperationResolver
from pytestlab.instruments.VirtualInstrument import VirtualInstrument


def test_no_argument_dmm_function_does_not_advertise_generic_settings() -> None:
    meter = AutoInstrument.from_config("keysight/34460A", simulate=True)
    with pytest.raises(OperationDiscoveryError, match="does not accept"):
        meter.list_operation_options("measure", "range_val", context={"function": "diode"})
    with pytest.raises(OperationDiscoveryError, match="does not accept"):
        meter.list_operation_options("measure", "resolution", context={"function": "diode"})
    queries: list[str] = []
    meter._query = lambda command: queries.append(command) or "0.7"
    meter.measure("diode", uncertainty=False)
    assert queries[-1] == "MEASURE:DIOD?"


@pytest.mark.parametrize("function", ["temperature", "diode", "continuity"])
def test_34460a_simulator_executes_every_no_argument_function(function: str) -> None:
    meter = AutoInstrument.from_config("keysight/34460A", simulate=True)

    result = meter.measure(function, uncertainty=False)

    assert float(result.values) == 0.0


def test_disabled_profile_parameter_disables_its_options() -> None:
    config = AutoInstrument.from_config("keysight/34460A", simulate=True).config
    config.operation_options = ProfileOperationOptions.model_validate(
        {
            "set_trigger_source": {
                "source": {
                    "kind": "enum",
                    "supported": False,
                    "reason": "not installed",
                    "options": [{"value": "on", "transport": {"value": "ON"}}],
                }
            }
        }
    )
    meter = AutoInstrument.from_config(config, simulate=True)
    assert meter.describe_operation("set_trigger_source")["support"]["supported"] is False
    with pytest.raises(OperationDiscoveryError, match="not installed"):
        meter.list_operation_options("set_trigger_source", "source")
    disabled = meter.list_operation_options(
        "set_trigger_source", "source", include_unsupported=True
    )
    assert disabled and all(not item["supported"] for item in disabled)
    with pytest.raises(InstrumentParameterError):
        meter.set_trigger_source("on")


@pytest.mark.parametrize("generic_arguments", [False, True])
def test_dmm_uses_selected_alias_shape_without_requiring_measure(generic_arguments):
    path = Path(__file__).parents[2] / "pytestlab" / "profiles" / "keysight" / "34460A.yaml"
    profile = yaml.safe_load(path.read_text())
    function = "dc_voltage" if generic_arguments else "diode"
    spec = profile["measurement_functions"][function]
    spec["transport"]["measure_alias"] = "vendor_reading"
    profile["measurement_functions"] = {function: spec}
    # The canonical operation registry owns the operation alias once present;
    # keep the synthetic profile mutation consistent with that private mapping.
    profile["operation_options"]["measure"]["transport"]["measure"] = "vendor_reading"
    profile["scpi"]["queries"].pop("measure")
    profile["scpi"]["queries"]["vendor_reading"] = {
        "template": "READ:{function}? {range},{resolution}"
        if generic_arguments
        else "READ:{function}?"
    }
    meter = AutoInstrument.from_config(profile, simulate=True)
    assert meter.supports_operation("measure")
    assert meter.list_operation_options("measure", "function")[0]["value"] == function
    queries = []
    meter._query = lambda command: queries.append(command) or "0.7"
    meter.measure(function, uncertainty=False)
    expected = "READ:VOLT:DC? AUTO,DEF" if generic_arguments else "READ:DIOD?"
    assert queries == [expected]


def test_disabled_operation_capability_blocks_discovery_and_execution() -> None:
    class Disabled(VirtualInstrument):
        OPERATION_CONTRACT = (
            OperationDescriptor(
                "trigger_state",
                public_method="set_trigger_state",
                capability="missing_feature",
            ),
        )

    instrument = Disabled(
        backend=Mock(),
        config=VirtualInstrumentConfig(
            manufacturer="Test",
            model="Disabled",
            device_type="virtual_instrument",
            role="measurement",
            operation_options={
                "trigger_state": {
                    "transport": {"command": "set_trigger_state"},
                    "parameters": {
                        "state": {
                            "kind": "enum",
                            "options": [{"value": "armed", "transport": {"value": "ARM"}}],
                            "bindings": [{"alias": "command", "parameter": "state"}],
                        }
                    },
                }
            },
            scpi={"commands": {"set_trigger_state": {"template": "STATE {state}"}}},
        ),
    )
    with pytest.raises(OperationDiscoveryError, match="not enabled"):
        instrument.list_operation_options("trigger_state", "state")
    options = instrument.list_operation_options("trigger_state", "state", include_unsupported=True)
    assert options[0]["supported"] is False
    with pytest.raises(InstrumentParameterError, match="not enabled"):
        instrument.set_trigger_state("armed")


def test_scpi_variant_is_identical_before_backend_activation() -> None:
    profile = VirtualInstrumentConfig(
        manufacturer="Test",
        model="Variant",
        device_type="virtual_instrument",
        role="measurement",
        scpi_variant="alternate",
        scpi={
            "variants": {
                "default": {"commands": {"set_trigger_state": {"template": "DEF {state}"}}},
                "alternate": {"commands": {"set_trigger_state": {"template": "ALT {state}"}}},
            }
        },
    )
    instrument = AutoInstrument.from_config(profile)
    simulated = AutoInstrument.from_config(profile, simulate=True)
    assert instrument._scpi_engine.build("set_trigger_state", state="ON") == ["ALT ON"]
    assert simulated._scpi_engine.build("set_trigger_state", state="ON") == ["ALT ON"]


@pytest.mark.parametrize("default", ["garbage", float("inf"), float("nan")])
def test_range_defaults_must_be_finite_numeric(default: object) -> None:
    with pytest.raises(ValidationError):
        ProfileOperationOptions.model_validate(
            {"op": {"value": {"kind": "range", "default": default}}}
        )


def test_malformed_explicit_operation_metadata_does_not_fall_through_to_scpi() -> None:
    resolver = OperationResolver(
        SimpleNamespace(
            operation_options={
                "op": {"value": {"kind": "enum", "options": [{"value": "x", "unknown": 1}]}}
            }
        ),
        (),
        None,
    )
    with pytest.raises(InstrumentConfigurationError, match="Invalid operation_options metadata"):
        resolver._generic_profile_spec("op", "value")


def test_operation_option_has_no_provenance_in_public_contract() -> None:
    option = ProfileOperationOptions.model_validate(
        {"op": {"value": {"kind": "enum", "options": [{"value": "x"}]}}}
    )
    public = option.parameter("op", "value").options[0]
    assert not hasattr(public, "source")


def test_explicit_profile_operation_does_not_infer_omitted_parameter_from_scpi() -> None:
    class Engine:
        def validate_presence(self, aliases):
            return {alias: True for alias in aliases}

        def list_parameters(self, alias):
            return ["level"]

        def validate_placeholders(self, alias):
            return {"placeholders": ["level"]}

    resolver = OperationResolver(
        SimpleNamespace(
            operation_options={
                "op": {
                    "transport": {"main": "set_level"},
                    "parameters": {
                        "mode": {
                            "kind": "enum",
                            "options": [{"value": "cc"}],
                            "bindings": [{"alias": "main", "parameter": "mode"}],
                        }
                    },
                }
            }
        ),
        (
            OperationDescriptor(
                "op",
            ),
        ),
        Engine(),
    )
    data = resolver._parameter_data(resolver.descriptors[0], "level", {})
    assert data.kind == "unresolved"
    assert data.reason == "Profile metadata omits 'op.level'."


def test_unknown_operation_transport_binding_is_rejected_at_profile_load():
    with pytest.raises(ValidationError, match="unknown transport alias"):
        ProfileOperationOptions.model_validate(
            {
                "trigger_state": {
                    "state": {
                        "kind": "enum",
                        "options": [
                            {
                                "value": "a",
                                "transport": {"value": "A"},
                            },
                            {
                                "value": "b",
                                "transport": {"value": "B"},
                            },
                        ],
                        "bindings": [{"alias": "missing", "parameter": "state"}],
                    },
                    "transport": {},
                }
            }
        )
