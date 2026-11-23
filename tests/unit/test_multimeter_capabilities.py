from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from pytestlab.config.multimeter_config import FunctionSpec
from pytestlab.config.multimeter_config import MeasurementFunctionsSpec
from pytestlab.config.multimeter_config import MultimeterConfig
from pytestlab.errors import InstrumentDataError
from pytestlab.instruments.Multimeter import Multimeter
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
        return "0"

    def query_raw(self, cmd: str, delay: float | None = None) -> bytes:
        return b"0"

    def close(self):
        pass

    def set_timeout(self, timeout_ms: int):
        pass

    def get_timeout(self) -> int:
        return 1000


def make_config(functions: MeasurementFunctionsSpec) -> MultimeterConfig:
    return MultimeterConfig(
        manufacturer="test",
        model="profile-dmm",
        device_type="multimeter",
        role="measurement",
        measurement_functions=functions,
        scpi={
            "commands": {"set_trigger_source": {"template": "TRIG:SOUR {source}"}},
            "queries": {
                "measure": {"template": "MEASURE:{function}? {range},{resolution}"},
                "get_config": {"template": "CONFigure?"},
            },
        },
        operation_options={
            "measure": {
                "transport": {"measure": "measure"},
                "parameters": {
                    "function": {
                        "kind": "enum",
                        "source": "measurement_functions",
                    },
                    "range_val": {
                        "kind": "enum",
                        "source": "measurement_functions.ranges",
                        "dependencies": ["function"],
                        "default": "AUTO",
                        "strict": False,
                    },
                    "resolution": {
                        "kind": "open_string",
                        "source": "measurement_functions.resolution",
                        "dependencies": ["function"],
                        "default": "DEF",
                        "strict": False,
                    },
                    "uncertainty": {
                        "kind": "bool",
                        "options": [
                            {"value": True, "transport": {"value": True}},
                            {"value": False, "transport": {"value": False}},
                        ],
                        "default": True,
                        "transport_parameter": False,
                    },
                },
            },
            "get_config": {"transport": {"query": "get_config"}},
        },
    )


def make_dmm(functions: MeasurementFunctionsSpec) -> Multimeter:
    return Multimeter(config=make_config(functions), backend=DummyBackend())


def test_profile_options_are_semantic_and_do_not_expose_transport():
    functions = MeasurementFunctionsSpec(
        dc_voltage=FunctionSpec(
            label="DC voltage",
            aliases=["voltage", "vdc"],
            unit="V",
            transport={"function_token": "MEAS:VOLT:DC", "measure_alias": "measure"},
        ),
        capacitance=FunctionSpec(
            label="Capacitance",
            unit="F",
            transport={"function_token": "MEAS:CAP", "measure_alias": "measure"},
        ),
    )

    options = make_dmm(functions).list_operation_options(
        "measure", "function", include_unsupported=True
    )

    assert [option["value"] for option in options] == ["dc_voltage", "capacitance"]
    assert not any("token" in key for key in options[0])
    assert options[0]["value"] == "dc_voltage"
    assert "voltage" in options[0]["aliases"]
    assert options[1]["unit"] == "F"


def test_profile_options_are_the_authority_and_accept_safe_aliases():
    dmm = make_dmm(
        MeasurementFunctionsSpec(
            dc_voltage=FunctionSpec(
                aliases=["voltage"],
                transport={"function_token": "VOLT:DC", "measure_alias": "measure"},
            )
        )
    )

    options = dmm.list_operation_options("measure", "function", include_unsupported=True)
    assert options[0]["value"] == "dc_voltage"
    assert "voltage" in options[0]["aliases"]
    with pytest.raises(ValueError, match="Unsupported semantic option"):
        dmm._resolve_operation_parameter("measure", "function", "resistance")


def test_missing_transport_mapping_is_reported_not_executed():
    dmm = make_dmm(MeasurementFunctionsSpec(dc_voltage=FunctionSpec()))

    option = dmm.list_operation_options("measure", "function", include_unsupported=True)[0]
    assert option["supported"] is False
    assert "no transport mapping" in option["reason"]
    with pytest.raises(ValueError, match="no transport mapping"):
        dmm.measure("dc_voltage", uncertainty=False)


def test_custom_profile_function_keys_are_discoverable():
    functions = MeasurementFunctionsSpec(
        custom_temperature={
            "label": "Chamber temperature",
            "aliases": ["chamber_temp"],
            "unit": "°C",
            "transport": {"function_token": "TEMP:CHAN2", "measure_alias": "measure"},
        }
    )

    options = make_dmm(functions).list_operation_options(
        "measure", "function", include_unsupported=True
    )
    assert len(options) == 1
    assert options[0]["value"] == "custom_temperature"
    assert not any("token" in key for key in options[0])
    assert options[0]["supported"] is True


def test_measure_uses_the_profile_transport_mapping():
    dmm = make_dmm(
        MeasurementFunctionsSpec(
            dc_voltage=FunctionSpec(
                transport={"function_token": "VOLT:DC", "measure_alias": "measure"}
            )
        )
    )
    dmm._scpi_engine = SCPIEngine(
        {"queries": {"measure": {"template": "MEASURE:{function}? {range},{resolution}"}}}
    )
    dmm._query = Mock(return_value="0")

    dmm.measure("dc_voltage", uncertainty=False)

    dmm._query.assert_called_once_with("MEASURE:VOLT:DC? AUTO,DEF")


def test_operation_description_includes_profile_function_options():
    dmm = make_dmm(
        MeasurementFunctionsSpec(
            dc_voltage=FunctionSpec(
                transport={"function_token": "VOLT:DC", "measure_alias": "measure"}
            ),
            diode=FunctionSpec(transport={"function_token": "DIOD", "measure_alias": "measure"}),
        )
    )

    description = dmm.describe_operation("measure", include_unsupported=True)
    options = description["parameters"]["function"]["options"]
    assert [option["value"] for option in options] == ["dc_voltage", "diode"]
    assert "choices_ref" not in description["parameters"]["function"]


def test_get_config_reverse_maps_profile_token_without_vendor_prefix_heuristics():
    dmm = make_dmm(
        MeasurementFunctionsSpec(
            chamber_temperature=FunctionSpec(
                label="Chamber temperature",
                unit="K",
                transport={"function_token": "TEMP:CHAN2", "measure_alias": "measure"},
            )
        )
    )
    dmm._scpi_engine = SCPIEngine({"queries": {"get_config": {"template": "CONF?"}}})
    dmm._query = Mock(return_value="TEMP:CHAN2 300,MIN")

    config = dmm.get_config()

    assert config.measurement_mode == "Chamber temperature"
    assert config.units == "K"
    assert config.range_value == 300.0
    assert config.resolution == "MIN"


def test_get_config_rejects_undeclared_profile_token():
    dmm = make_dmm(
        MeasurementFunctionsSpec(
            dc_voltage=FunctionSpec(
                transport={"function_token": "VOLT:DC", "measure_alias": "measure"}
            )
        )
    )
    dmm._scpi_engine = SCPIEngine({"queries": {"get_config": {"template": "CONF?"}}})
    dmm._query = Mock(return_value="VENDOR:UNKNOWN 10,DEF")

    with pytest.raises(InstrumentDataError, match="not declared by its profile"):
        dmm.get_config()


def test_measurement_is_the_single_high_level_dmm_operation():
    descriptors = {descriptor.operation_id for descriptor in Multimeter.operation_descriptors()}
    assert "measure" in descriptors
    assert not {"configure", "set_function"} & descriptors
    assert all(
        isinstance(descriptor, OperationDescriptor)
        for descriptor in Multimeter.operation_descriptors()
    )


@pytest.mark.parametrize("profile", ["keysight/EDU34450A", "keysight/34460A", "keysight/34470A"])
def test_shipped_dmm_profiles_pass_strict_operation_contract(profile: str) -> None:
    from pytestlab import AutoInstrument

    meter = AutoInstrument.from_config(profile, simulate=True)

    report = meter.validate_operation_contract(strict=True, check_parameters=True)

    assert report["measure"]["supported"] is True


def test_measurement_function_aliases_must_be_unambiguous() -> None:
    with pytest.raises(ValidationError, match="ambiguous measurement function alias"):
        MeasurementFunctionsSpec(
            dc_voltage=FunctionSpec(
                aliases=["same"],
                transport={"function_token": "VOLT:DC", "measure_alias": "measure"},
            ),
            dc_current=FunctionSpec(
                aliases=["same"],
                transport={"function_token": "CURR:DC", "measure_alias": "measure"},
            ),
        )


@pytest.mark.parametrize("profile", ["keysight/34460A", "keysight/34470A"])
def test_shipped_profiles_expose_declared_voltage_ranges(profile: str) -> None:
    from pytestlab import AutoInstrument

    meter = AutoInstrument.from_config(profile, simulate=True)
    ranges = meter.list_operation_options(
        "measure", "range_val", context={"function": "dc_voltage"}
    )
    resolutions = meter.list_operation_options(
        "measure", "resolution", context={"function": "dc_voltage"}
    )

    assert [option["value"] for option in ranges] == ["AUTO", 0.1, 1.0, 10.0, 100.0, 1000.0]
    assert [option["value"] for option in resolutions] == ["DEF", "MIN", "MAX"]
