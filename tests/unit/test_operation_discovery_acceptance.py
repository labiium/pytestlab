from __future__ import annotations

import struct
from unittest.mock import MagicMock

import pytest

from pytestlab import AutoInstrument
from pytestlab.config.device_config import DeviceRole
from pytestlab.config.virtual_instrument_config import VirtualInstrumentConfig


def _virtual_profile(model: str, states: list[str]) -> VirtualInstrumentConfig:
    return VirtualInstrumentConfig(
        manufacturer="PyTestLab",
        model=model,
        device_type="virtual_instrument",
        role=DeviceRole.MEASUREMENT,
        operation_options={
            "trigger_state": {
                "state": {
                    "kind": "enum",
                    "options": [
                        {
                            "value": state.lower(),
                            "label": state.title(),
                            "transport": {"value": state.upper()},
                        }
                        for state in states
                    ],
                }
            }
        },
        scpi={
            "commands": {
                "set_trigger_state": {"template": "TRIG:STATE {state}"},
            },
            "queries": {
                "get_trigger_state": {"template": "TRIG:STATE?"},
            },
        },
    )


def test_two_profiles_for_one_driver_return_their_declared_options() -> None:
    first = AutoInstrument.from_config(_virtual_profile("First", ["armed", "idle"]))
    second = AutoInstrument.from_config(_virtual_profile("Second", ["running", "stopped"]))

    assert [item["value"] for item in first.list_operation_options("trigger_state", "state")] == [
        "armed",
        "idle",
    ]
    assert [item["value"] for item in second.list_operation_options("trigger_state", "state")] == [
        "running",
        "stopped",
    ]


def test_dmm_discovered_functions_execute_through_measure() -> None:
    """Every advertised DMM function is accepted directly by measure()."""

    meter = AutoInstrument.from_config("keysight/EDU34450A", simulate=True)
    queries: list[str] = []
    meter._query = lambda command: queries.append(command) or "0.0"

    for option in meter.list_operation_options("measure", "function"):
        result = meter.measure(option["value"], uncertainty=False)
        assert result.values == 0.0

    assert len(queries) == len(meter.list_operation_options("measure", "function"))


def test_awg_discovered_functions_execute_through_set_function() -> None:
    """Every advertised AWG function is accepted directly by set_function()."""

    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    sent: list[str] = []
    generator._send_command = sent.append

    for option in generator.list_operation_options("set_function", "function_type"):
        generator.set_function(1, option["value"])

    assert len(sent) == len(generator.list_operation_options("set_function", "function_type"))


def test_scope_discovered_trigger_values_execute_through_configure_trigger() -> None:
    """Every advertised scope trigger choice is accepted by configure_trigger()."""

    scope = AutoInstrument.from_config("keysight/HD304MSO", backend_override=MagicMock())
    sent: list[str] = []
    scope._send_command = sent.append
    scope._query = lambda command: "1"

    defaults = {"source": "channel_1", "mode": "edge", "slope": "positive"}
    for parameter in defaults:
        for option in scope.list_operation_options("configure_trigger", parameter):
            arguments = dict(defaults)
            arguments[parameter] = option["value"]
            scope.configure_trigger(channel=1, level=0.0, **arguments)

    assert sent


@pytest.mark.parametrize("profile", ["keysight/EDU36311A", "rohdeschwarz/NGE102B"])
def test_power_supply_discovered_values_execute(profile: str) -> None:
    """Every supported PSU option is usable by the ordinary public methods."""

    supply = AutoInstrument.from_config(profile, simulate=True)
    sent: list[str] = []
    supply._send_command = sent.append
    supply._query = lambda command: "ON" if "OUTP" in command else "0.0"

    for operation in ("set_voltage", "set_current"):
        parameter = "voltage" if operation == "set_voltage" else "current"
        method = supply.set_voltage if operation == "set_voltage" else supply.set_current
        for channel_option in supply.list_operation_options(operation, "channel"):
            channel = channel_option["value"]
            description = supply.describe_operation(operation, context={"channel": channel})
            limit = description["parameters"][parameter]["constraints"]["max"]
            method(channel, min(1.0, limit))

    for state_option in supply.list_operation_options("set_output", "state"):
        supply.output(1, state_option["value"])
    for channel_option in supply.list_operation_options("set_output", "channel"):
        supply.output(channel_option["value"], "on")

    if supply.supports_operation("set_display"):
        for state_option in supply.list_operation_options("set_display", "state"):
            supply.display(state_option["value"])

    for operation, method in (
        ("measure_voltage", supply.read_voltage),
        ("measure_current", supply.read_current),
        ("get_output_state", supply.get_output_state),
    ):
        for channel_option in supply.list_operation_options(operation, "channel"):
            assert method(channel_option["value"]) is not None

    if supply.supports_operation("set_slew_rate"):
        for channel_option in supply.list_operation_options("set_slew_rate", "channel"):
            channel = channel_option["value"]
            constraints = supply.describe_operation("set_slew_rate", context={"channel": channel})[
                "parameters"
            ]["duration_s"]["constraints"]
            supply.set_slew_rate(channel, constraints["min"])

    assert sent


def test_dc_active_load_discovered_values_execute() -> None:
    """Exercise all finite EL33133A options through their public methods."""

    load = AutoInstrument.from_config("keysight/EL33133A", simulate=True)
    sent: list[str] = []
    load._send_command = sent.append
    load._query = lambda command: "0.0"
    load._query_raw = lambda command: b"#18" + struct.pack("<2f", 1.0, 2.0)

    for mode_option in load.list_operation_options("set_load", "mode"):
        mode = mode_option["value"]
        value_constraints = load.describe_operation("set_load", context={"mode": mode})[
            "parameters"
        ]["value"]["constraints"]
        value = min(1.0, value_constraints["max"])
        load.set_load(value, mode=mode)
        load.set_range(value, mode=mode)
        load.set_transient_level(value, mode=mode)
        slew_constraints = load.describe_operation("set_slew_rate", context={"mode": mode})[
            "parameters"
        ]["rate"]["constraints"]
        load.set_slew_rate(1.0, mode=mode)
        assert slew_constraints["max"] >= 1.0

    for operation, method in (
        ("enable_input", load.enable_input),
        ("short_input", load.short_input),
    ):
        for option in load.list_operation_options(operation, "state"):
            method(option["value"])

    for option in load.list_operation_options("configure_transient_mode", "mode"):
        load.configure_transient_mode(option["value"])
    for option in load.list_operation_options("start_transient", "continuous"):
        load.start_transient(option["value"])

    for operation, method in (("enable_battery_test", load.enable_battery_test),):
        for option in load.list_operation_options(operation, "state"):
            method(option["value"])
    for option in load.list_operation_options("get_battery_test_measurement", "metric"):
        assert load.get_battery_test_measurement(option["value"]) == 0.0

    for option in load.list_operation_options("fetch_scope_data", "measurement"):
        assert load.fetch_scope_data(option["value"]).size == 2
    point_limit = load.describe_operation("fetch_datalogger_data")["parameters"]["num_points"][
        "constraints"
    ]["max"]
    assert load.fetch_datalogger_data(min(2, point_limit)) == [0.0]

    for operation, _parameter, method, value in (
        ("set_battery_cutoff_voltage", "voltage", load.set_battery_cutoff_voltage, 1.0),
        ("set_battery_cutoff_capacity", "capacity", load.set_battery_cutoff_capacity, 1.0),
        ("set_battery_cutoff_timer", "time_s", load.set_battery_cutoff_timer, 1.0),
    ):
        for state_option in load.list_operation_options(operation, "state"):
            method(value, state=state_option["value"])

    assert sent
