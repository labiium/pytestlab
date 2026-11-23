from __future__ import annotations

from types import SimpleNamespace

import pytest

from pytestlab.config.operation_options import ProfileOperationOptions
from pytestlab.errors import OperationDiscoveryError
from pytestlab.instruments.operation_contract import OperationDescriptor
from pytestlab.instruments.operation_resolver import OperationResolver


def test_profile_operation_keeps_transport_private_and_bindings_explicit() -> None:
    options = ProfileOperationOptions.model_validate(
        {
            "measure": {
                "transport": {"read": "measure_read"},
                "parameters": {
                    "function": {
                        "kind": "enum",
                        "options": [{"value": "dc_voltage", "transport": {"value": "VOLT"}}],
                        "bindings": [{"alias": "read", "parameter": "function"}],
                    }
                },
            }
        }
    )

    public = options.model_dump_public()
    assert public["measure"]["function"]["options"][0] == {
        "value": "dc_voltage",
        "aliases": [],
        "supported": True,
        "constraints": {},
    }
    assert "transport" not in public["measure"]
    assert "bindings" not in public["measure"]["function"]
    assert options.operation("measure").transport == {"read": "measure_read"}


def test_python_only_parameter_may_explicitly_omit_transport_binding() -> None:
    options = ProfileOperationOptions.model_validate(
        {
            "measure": {
                "parameters": {
                    "uncertainty": {
                        "kind": "bool",
                        "transport_parameter": False,
                        "options": [{"value": True}, {"value": False}],
                    }
                }
            }
        }
    )
    assert "transport_parameter" not in options.model_dump_public()["measure"]["uncertainty"]
    assert options.parameter("measure", "uncertainty").transport_parameter is False


def test_dynamic_source_may_declare_default_without_static_options() -> None:
    options = ProfileOperationOptions.model_validate(
        {
            "measure": {
                "parameters": {
                    "range_val": {
                        "kind": "enum",
                        "source": "measurement_functions.ranges",
                        "default": "AUTO",
                    }
                }
            }
        }
    )
    assert options.parameter("measure", "range_val").default == "AUTO"


def test_descriptor_has_only_semantic_shape_and_safety() -> None:
    descriptor = OperationDescriptor(
        "measure",
        safety_class="read",
    )
    dumped = descriptor.to_dict()
    assert dumped["method"] == "measure"
    assert "required_aliases" not in dumped
    assert "optional_aliases" not in dumped
    assert "parameter_exemptions" not in dumped


class _NoInferenceEngine:
    def validate_presence(self, aliases: list[str]) -> dict[str, bool]:
        return {alias: True for alias in aliases}

    def list_options(self, *_args: object, **_kwargs: object) -> list[dict[str, object]]:
        pytest.fail("public operation discovery must not infer choices from SCPI")


def test_resolver_does_not_infer_semantic_choices_from_scpi() -> None:
    config = SimpleNamespace(
        manufacturer="test",
        model="model",
        device_type="virtual",
        operation_options=ProfileOperationOptions(),
    )
    resolver = OperationResolver(
        config,
        (OperationDescriptor("measure"),),
        _NoInferenceEngine(),
    )

    with pytest.raises(OperationDiscoveryError, match="not declared"):
        resolver.list_options("measure", "function")
