from __future__ import annotations

import pytest
import yaml
from pydantic import ValidationError

from pytestlab import AutoInstrument
from pytestlab.common.enums import WaveformType
from pytestlab.errors import InstrumentCommunicationError
from pytestlab.errors import InstrumentParameterError
from pytestlab.instruments.WaveformGenerator import WaveformGenerator


@pytest.fixture(autouse=True)
def _voltage_limits_off_by_default(monkeypatch):
    monkeypatch.setattr(WaveformGenerator, "get_voltage_limits_state", lambda self, channel: False)


def _profile_dict() -> dict[str, object]:
    with open("pytestlab/profiles/keysight/EDU33212A.yaml") as stream:
        return yaml.safe_load(stream)


def test_unknown_function_parameter_is_rejected_before_function_write() -> None:
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    sent: list[str] = []
    generator._send_command = sent.append

    with pytest.raises(ValidationError, match="Unexpected keyword argument"):
        generator.set_function(1, "sine", vendor_private_control=1)

    assert sent == []


def test_historical_waveform_enum_remains_an_input_adapter() -> None:
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    sent: list[str] = []
    generator._send_command = sent.append

    generator.set_function(1, WaveformType.SINE)

    assert sent == ["SOUR1:FUNC SIN"]


def test_arbitrary_facade_uses_profile_declared_function() -> None:
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    sent: list[str] = []
    generator._send_command = sent.append

    generator.channel(1).setup_arbitrary("wave", 1_000.0, 1.0)

    assert sent[0] == "SOUR1:FUNC ARB"
    assert sent[-3:] == [
        "SOUR1:VOLTage:OFFSet 0.0",
        "SOUR1:VOLTage:UNIT VPP",
        "SOUR1:VOLTage 1.0",
    ]


def test_awg_profile_passes_strict_operation_contract_audit() -> None:
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)

    report = generator.validate_operation_contract(strict=True, check_parameters=True)

    assert report["set_function"]["supported"] is True


@pytest.mark.parametrize(
    ("method", "value", "command"),
    [
        ("set_frequency", "MIN", "SOUR1:FREQ MINimum"),
        ("set_amplitude", "MAX", "SOUR1:VOLTage MAXimum"),
        ("set_offset", "DEF", "SOUR1:VOLTage:OFFSet DEFault"),
    ],
)
def test_profile_declared_special_values_reach_scpi(method, value, command) -> None:
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    sent: list[str] = []
    generator._send_command = sent.append

    def query(command: str) -> str:
        if "FUNC?" in command:
            return "SIN"
        if "LOAD?" in command:
            return "50"
        if "UNIT?" in command:
            return "VPP"
        if "OFFSet?" in command:
            return "0"
        return "10"

    generator._query = query

    getattr(generator, method)(1, value)

    assert sent == [command]


def test_load_command_comes_from_profile() -> None:
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    sent: list[str] = []
    generator._send_command = sent.append

    generator.set_output_load_impedance(1, 50)

    assert sent == ["OUTPut1:LOAD 50"]


@pytest.mark.parametrize(
    "method,value",
    [
        ("set_frequency", float("nan")),
        ("set_frequency", float("inf")),
        ("set_amplitude", float("nan")),
        ("set_amplitude", float("inf")),
        ("set_offset", float("nan")),
        ("set_offset", float("inf")),
    ],
)
def test_awg_numeric_setters_reject_non_finite_values_before_io(method, value) -> None:
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    sent: list[str] = []
    generator._send_command = sent.append

    with pytest.raises(InstrumentParameterError):
        getattr(generator, method)(1, value)

    assert sent == []


@pytest.mark.parametrize("unit", ["VPP", "VRMS", "DBM"])
def test_voltage_unit_uses_profile_enum(unit) -> None:
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    sent: list[str] = []
    generator._send_command = sent.append

    generator.set_voltage_unit(1, unit.lower())

    assert sent == [f"SOUR1:VOLTage:UNIT {unit}"]


def test_voltage_unit_rejects_unsupported_unit_before_io() -> None:
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    sent: list[str] = []
    generator._send_command = sent.append

    with pytest.raises(InstrumentParameterError):
        generator.set_voltage_unit(1, "WATTS")

    assert sent == []


@pytest.mark.parametrize("value", [float("nan"), float("inf"), "nan", "inf"])
def test_apply_waveform_settings_validates_numeric_values_before_io(value) -> None:
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    sent: list[str] = []
    generator._send_command = sent.append

    with pytest.raises(InstrumentParameterError):
        generator.apply_waveform_settings(1, "sine", frequency=value)

    assert sent == []


def test_live_native_bounds_reject_before_setting_write() -> None:
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    sent: list[str] = []
    queries: list[str] = []

    def query(command: str) -> str:
        queries.append(command)
        return "-5" if "MINimum" in command else "5"

    generator._send_command = sent.append
    generator._query = query

    with pytest.raises(InstrumentParameterError, match="current native limits"):
        generator.set_offset(1, 6)

    assert sent == []
    assert queries == ["SOUR1:VOLTage:OFFSet? MINimum", "SOUR1:VOLTage:OFFSet? MAXimum"]


def test_negative_offset_inside_live_native_bounds_is_preserved() -> None:
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    sent: list[str] = []
    generator._send_command = sent.append

    def query(command: str) -> str:
        if "MINimum" in command:
            return "-5"
        if "MAXimum" in command:
            return "5"
        if "FUNC?" in command:
            return "SIN"
        if "LOAD?" in command:
            return "50"
        if "UNIT?" in command:
            return "VPP"
        return "1"

    generator._query = query

    generator.set_offset(1, -4.5)

    assert sent == ["SOUR1:VOLTage:OFFSet -4.5"]


def test_negative_dbm_amplitude_uses_live_native_bounds() -> None:
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    sent: list[str] = []
    generator._send_command = sent.append

    def query(command: str) -> str:
        if "MINimum" in command:
            return "-56.021"
        if "MAXimum" in command:
            return "23.979"
        if "FUNC?" in command:
            return "SIN"
        if "LOAD?" in command:
            return "50"
        if "UNIT?" in command:
            return "DBM"
        return "0"

    generator._query = query

    generator.set_amplitude(1, -40)

    assert sent == ["SOUR1:VOLTage -40.0"]


@pytest.mark.parametrize(
    ("function", "frequency", "should_pass"),
    [
        ("sine", 20_000_000, True),
        ("square", 10_000_000, True),
        ("ramp", 200_000, True),
        ("ramp", 200_001, False),
    ],
)
def test_compound_frequency_uses_profile_function_limit(function, frequency, should_pass) -> None:
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    sent: list[str] = []
    generator._send_command = sent.append

    def query(command: str) -> str:
        if "FREQ?" in command:
            return "1000"
        if "FUNC?" in command:
            return "SIN"
        if "LOAD" in command:
            return "50"
        if "UNIT" in command:
            return "VPP"
        if "VOLTage?" in command:
            return "1"
        if "OFFSet?" in command:
            return "0"
        return "0"

    generator._query = query
    if should_pass:
        generator.set_function(1, function, frequency=frequency)
        assert sent
    else:
        with pytest.raises(InstrumentParameterError, match="native range"):
            generator.set_function(1, function, frequency=frequency)
        assert sent == []


def test_compound_settings_enforce_joint_peak_budget_before_any_write() -> None:
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    sent: list[str] = []
    generator._send_command = sent.append

    def query(command: str) -> str:
        if "FREQ?" in command:
            return "1000"
        if "FUNC?" in command:
            return "SIN"
        if "LOAD" in command:
            return "50"
        if "UNIT" in command:
            return "VPP"
        if "OFFSet?" in command:
            return "0"
        return "1"

    generator._query = query

    generator.set_function(1, "sine", amplitude=10, offset=0)
    assert sent
    sent.clear()

    with pytest.raises(InstrumentParameterError, match="peak budget"):
        generator.set_function(1, "sine", amplitude=10, offset=0.01)

    assert sent == []


def test_compound_offset_max_is_emitted_as_jointly_valid_numeric_offset() -> None:
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    sent: list[str] = []
    generator._send_command = sent.append

    def query(command: str) -> str:
        if "FREQ?" in command:
            return "1000"
        if "FUNC?" in command:
            return "SIN"
        if "LOAD?" in command:
            return "50"
        if "UNIT?" in command:
            return "VPP"
        if "OFFSet?" in command:
            return "0"
        return "1"

    generator._query = query
    generator.set_function(1, "sine", amplitude=10, offset="MAX")

    assert sent == [
        "SOUR1:FUNC SIN",
        "SOUR1:VOLTage MAXimum",
        "SOUR1:VOLTage:OFFSet 0.0",
    ]


def test_high_impedance_full_twenty_volt_peak_to_peak_is_valid_at_zero_offset() -> None:
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    sent: list[str] = []
    generator._send_command = sent.append

    def query(command: str) -> str:
        if "FREQ?" in command:
            return "1000"
        if "FUNC?" in command:
            return "SIN"
        if "LOAD" in command:
            return "9.9e37"
        if "UNIT" in command:
            return "VPP"
        return "0"

    generator._query = query
    generator.set_function(1, "sine", amplitude=20, offset=0)
    assert sent
    sent.clear()

    with pytest.raises(InstrumentParameterError, match="native VPP range"):
        generator.set_function(1, "sine", amplitude=20.1, offset=0)
    assert sent == []

    with pytest.raises(InstrumentParameterError, match="peak budget"):
        generator.set_function(1, "sine", amplitude=20, offset=0.01)
    assert sent == []


def test_compound_does_not_force_vpp_and_keeps_negative_dbm_valid() -> None:
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    sent: list[str] = []
    generator._send_command = sent.append

    def query(command: str) -> str:
        if "FREQ?" in command:
            return "1000"
        if "FUNC?" in command:
            return "SIN"
        if "LOAD" in command:
            return "50"
        if "UNIT" in command:
            return "DBM"
        if "VOLTage?" in command:
            return "-10"
        return "0"

    generator._query = query
    generator.set_function(1, "sine", amplitude=-10, offset=0)

    assert sent == ["SOUR1:FUNC SIN", "SOUR1:VOLTage -10.0", "SOUR1:VOLTage:OFFSet 0.0"]


def test_dbm_accepts_finite_loads_and_rejects_high_impedance() -> None:
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    sent: list[str] = []
    load = ["50"]
    generator._send_command = sent.append
    generator._query = lambda command: load[0]

    generator.set_voltage_unit(1, "dBm")
    assert sent == ["SOUR1:VOLTage:UNIT DBM"]
    sent.clear()
    load[0] = "100"
    generator.set_voltage_unit(1, "dBm")
    assert sent == ["SOUR1:VOLTage:UNIT DBM"]
    sent.clear()
    load[0] = "9.9e37"

    with pytest.raises(InstrumentParameterError, match="finite positive load"):
        generator.set_voltage_unit(1, "dBm")
    assert sent == []


def test_finite_load_compound_limits_scale_from_the_profile_source_impedance() -> None:
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    sent: list[str] = []
    generator._send_command = sent.append

    def query(command: str) -> str:
        if "FREQ?" in command:
            return "1000"
        if "FUNC?" in command:
            return "SIN"
        if "LOAD" in command:
            return "100"
        if "UNIT" in command:
            return "VPP"
        if "VOLTage?" in command:
            return "1"
        if "OFFSet?" in command:
            return "0"
        return "0"

    generator._query = query
    generator.set_function(1, "sine", amplitude=13.3333333333, offset=0)
    assert sent
    sent.clear()

    with pytest.raises(InstrumentParameterError, match="native VPP range"):
        generator.set_function(1, "sine", amplitude=13.34, offset=0)
    assert sent == []


def test_function_transition_moves_frequency_into_target_range_before_switch() -> None:
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    sent: list[str] = []
    generator._send_command = sent.append

    def query(command: str) -> str:
        if "FUNC?" in command:
            return "SIN"
        if "FREQ?" in command:
            return "20000000"
        if "LOAD?" in command:
            return "50"
        if "UNIT?" in command:
            return "VPP"
        if "OFFSet?" in command:
            return "0"
        return "0.01"

    generator._query = query
    generator.set_function(1, "ramp", frequency=200000)
    assert sent == ["SOUR1:FREQ 200000.0", "SOUR1:FUNC RAMP"]


def test_function_transition_requires_explicit_frequency_if_current_is_out_of_range() -> None:
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    sent: list[str] = []
    generator._send_command = sent.append

    def query(command: str) -> str:
        if "FUNC?" in command:
            return "SIN"
        if "FREQ?" in command:
            return "20000000"
        if "LOAD?" in command:
            return "50"
        if "UNIT?" in command:
            return "VPP"
        if "OFFSet?" in command:
            return "0"
        return "0.01"

    generator._query = query
    with pytest.raises(InstrumentParameterError, match="native range"):
        generator.set_function(1, "ramp")
    assert sent == []


def test_function_transition_moves_reduced_amplitude_before_ramp_switch() -> None:
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    sent: list[str] = []
    generator._send_command = sent.append

    def query(command: str) -> str:
        if "FUNC?" in command:
            return "SIN"
        if "FREQ?" in command:
            return "1000"
        if "LOAD?" in command:
            return "50"
        if "UNIT?" in command:
            return "VRMS"
        if "OFFSet?" in command:
            return "0"
        return "3.5"

    generator._query = query
    generator.set_function(1, "ramp", amplitude=2.0)
    assert sent[:2] == ["SOUR1:VOLTage 2.0", "SOUR1:FUNC RAMP"]


def test_vpp_function_facade_bridges_a_current_rms_amplitude_before_switch() -> None:
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    sent: list[str] = []
    generator._send_command = sent.append

    def query(command: str) -> str:
        if "FUNC?" in command:
            return "SIN"
        if "FREQ?" in command:
            return "1000"
        if "LOAD?" in command:
            return "50"
        if "UNIT?" in command:
            return "VRMS"
        if "OFFSet?" in command:
            return "0"
        if "VOLTage? MINimum" in command:
            return "0.001"
        if "VOLTage? MAXimum" in command:
            return "5"
        if "OFFSet? MINimum" in command:
            return "-5"
        if "OFFSet? MAXimum" in command:
            return "5"
        if "VOLTage?" in command:
            return "3.5"
        raise AssertionError(f"Unexpected query: {command}")

    generator._query = query
    generator.channel(1).setup_ramp(1_000.0, 0.1)

    assert sent[0] == "SOUR1:VOLTage 0.1"
    assert sent[1] == "SOUR1:FUNC RAMP"
    assert sent.index("SOUR1:VOLTage:UNIT VPP") < sent.index("SOUR1:VOLTage 0.1", 2)


@pytest.mark.parametrize("setter", ["amplitude", "offset"])
def test_direct_setter_rejects_signal_outside_enabled_native_voltage_limits(setter):
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    sent: list[str] = []
    generator._send_command = sent.append
    generator.get_voltage_limits_state = lambda channel: True

    def query(command: str) -> str:
        if "LIMit:LOW?" in command:
            return "-0.5"
        if "LIMit:HIGH?" in command:
            return "0.5"
        if "FUNC?" in command:
            return "SIN"
        if "LOAD?" in command:
            return "50"
        if "UNIT?" in command:
            return "VPP"
        if "OFFSet? MINimum" in command:
            return "-5"
        if "OFFSet? MAXimum" in command:
            return "5"
        if "OFFSet?" in command:
            return "0"
        if "VOLTage? MINimum" in command:
            return "0.001"
        if "VOLTage? MAXimum" in command:
            return "10"
        if "OFFSet? MINimum" in command:
            return "-5"
        if "OFFSet? MAXimum" in command:
            return "5"
        if "VOLTage?" in command:
            return "0.2"
        raise AssertionError(f"Unexpected query: {command}")

    generator._query = query
    with pytest.raises(InstrumentParameterError, match="Enabled voltage limits exclude"):
        if setter == "amplitude":
            generator.set_amplitude(1, 2.0)
        else:
            generator.set_offset(1, 1.0)
    assert sent == []


def test_compound_dc_offset_is_checked_against_enabled_voltage_limits():
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    sent: list[str] = []
    generator._send_command = sent.append
    generator.get_voltage_limits_state = lambda channel: True

    def query(command: str) -> str:
        if "LIMit:LOW?" in command:
            return "-2"
        if "LIMit:HIGH?" in command:
            return "2"
        if "FREQ?" in command:
            return "1000"
        if "LOAD?" in command:
            return "50"
        if "UNIT?" in command:
            return "VPP"
        if "OFFSet?" in command:
            return "0"
        if "VOLTage?" in command:
            return "1"
        raise AssertionError(f"Unexpected query: {command}")

    generator._query = query
    with pytest.raises(InstrumentParameterError, match="Enabled voltage limits exclude"):
        generator.set_function(1, "dc", offset=3.0)
    assert sent == []


def test_function_transition_rejects_current_amplitude_outside_target_envelope() -> None:
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    sent: list[str] = []
    generator._send_command = sent.append

    def query(command: str) -> str:
        if "FUNC?" in command:
            return "SIN"
        if "FREQ?" in command:
            return "1000"
        if "LOAD?" in command:
            return "50"
        if "UNIT?" in command:
            return "VRMS"
        if "OFFSet?" in command:
            return "0"
        return "3.5"

    generator._query = query
    with pytest.raises(InstrumentParameterError, match="native VRMS range"):
        generator.set_function(1, "ramp")
    assert sent == []


@pytest.mark.parametrize("setter", ["amplitude", "offset"])
def test_direct_setters_enforce_current_joint_peak_budget(setter: str) -> None:
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    sent: list[str] = []
    generator._send_command = sent.append

    def query(command: str) -> str:
        if "? MINimum" in command:
            return "-5" if "OFFSet" in command else "0.001"
        if "? MAXimum" in command:
            return "5" if "OFFSet" in command else "10"
        if "FUNC?" in command:
            return "SIN"
        if "LOAD?" in command:
            return "50"
        if "UNIT?" in command:
            return "VPP"
        if "VOLTage:OFFSet?" in command:
            return "4.9"
        if "VOLTage?" in command:
            return "10"
        raise AssertionError(f"Unexpected query: {command}")

    generator._query = query
    with pytest.raises(InstrumentParameterError, match="peak budget"):
        if setter == "amplitude":
            generator.set_amplitude(1, 10)
        else:
            generator.set_offset(1, 4.9)
    assert sent == []


def test_direct_amplitude_max_is_resolved_before_joint_peak_check() -> None:
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    sent: list[str] = []
    generator._send_command = sent.append

    def query(command: str) -> str:
        if "FUNC?" in command:
            return "SIN"
        if "LOAD?" in command:
            return "50"
        if "UNIT?" in command:
            return "VPP"
        if "OFFSet?" in command:
            return "4.9"
        return "10"

    generator._query = query
    with pytest.raises(InstrumentParameterError, match="peak budget"):
        generator.set_amplitude(1, "MAX")
    assert sent == []


def test_amplitude_default_uses_documented_value_without_querying_def() -> None:
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    sent: list[str] = []
    queries: list[str] = []
    generator._send_command = sent.append

    def query(command: str) -> str:
        queries.append(command)
        if "FUNC?" in command:
            return "SIN"
        if "LOAD?" in command:
            return "50"
        if "UNIT?" in command:
            return "VPP"
        if "OFFSet?" in command:
            return "4.99"
        return "1"

    generator._query = query
    with pytest.raises(InstrumentParameterError, match="peak budget"):
        generator.set_amplitude(1, "DEF")
    assert sent == []
    assert all("DEF" not in command.upper() for command in queries)


def test_voltage_limit_setting_rejects_inverted_pair_before_write() -> None:
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    sent: list[str] = []
    generator._send_command = sent.append

    def query(command: str) -> str:
        if "MINimum" in command:
            return "-10"
        if "MAXimum" in command:
            return "10"
        if "LIMit:LOW?" in command:
            return "-2"
        return "OFF"

    generator._query = query
    with pytest.raises(InstrumentParameterError, match="Low voltage limit"):
        generator.set_voltage_limit_high(1, -3)
    assert sent == []


@pytest.mark.parametrize(
    ("method", "command", "default"),
    [
        ("set_voltage_limit_high", "SOUR1:VOLTage:LIMit:HIGH DEFault", 5.0),
        ("set_voltage_limit_low", "SOUR1:VOLTage:LIMit:LOW DEFault", -5.0),
    ],
)
def test_voltage_limit_default_matches_documented_profile_default_and_native_bounds(
    method, command, default
) -> None:
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    sent: list[str] = []
    queries: list[str] = []
    generator._send_command = sent.append

    def query(command: str) -> str:
        queries.append(command)
        if "MINimum" in command:
            return "-10"
        if "MAXimum" in command:
            return "10"
        if "HIGH?" in command:
            return "5"
        if "LOW?" in command:
            return "-5"
        raise AssertionError(f"Unexpected query: {command}")

    generator._query = query
    getter = "get_voltage_limit_high" if method.endswith("high") else "get_voltage_limit_low"
    assert generator._awg_voltage_limit_default(getter) == default

    getattr(generator, method)(1, "DEF")

    assert sent == [command]
    assert any("MINimum" in item for item in queries)
    assert any("MAXimum" in item for item in queries)


def test_enabling_voltage_limits_rejects_a_current_output_outside_the_limits() -> None:
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    sent: list[str] = []
    generator._send_command = sent.append

    def query(command: str) -> str:
        if "LIMit:STATe?" in command:
            return "OFF"
        if "LIMit:LOW?" in command:
            return "-5"
        if "LIMit:HIGH?" in command:
            return "3"
        if "FUNC?" in command:
            return "SIN"
        if "UNIT?" in command:
            return "VPP"
        if "LOAD?" in command:
            return "50"
        if "OFFSet?" in command:
            return "0"
        return "10"

    generator._query = query
    with pytest.raises(InstrumentParameterError, match="exclude the current output"):
        generator.set_voltage_limits_state(1, "on")
    assert sent == []


def test_compound_function_preserves_profile_defined_function_values() -> None:
    profile = _profile_dict()
    scpi = profile["scpi"]
    commands = scpi["commands"]
    commands["set_function"]["parameters"]["function"]["choices"].append(
        {"value": "vendor_shape", "token": "VSHAPE", "label": "Vendor shape"}
    )
    profile["operation_options"]["set_function"]["parameters"]["function_type"]["options"].append(
        {"value": "vendor_shape", "transport": {"value": "VSHAPE"}}
    )
    generator = AutoInstrument.from_config(profile, simulate=True)
    sent: list[str] = []
    generator._send_command = sent.append

    generator.set_function(1, "vendor_shape")

    assert sent == ["SOUR1:FUNC VSHAPE"]


def test_apply_waveform_settings_uses_profile_mapping_not_driver_token_table() -> None:
    profile = _profile_dict()
    command = profile["scpi"]["commands"]["apply_waveform_settings"]
    command["template"] = "CUSTOM{channel}:{function} {frequency}|{amplitude}|{offset}"
    command["parameters"]["function"]["choices"][0]["token"] = "CUSTOM_SINE"
    generator = AutoInstrument.from_config(profile, simulate=True)
    sent: list[str] = []
    generator._send_command = sent.append
    generator._query = lambda query: "50" if "LOAD" in query else "VPP"

    generator.apply_waveform_settings(1, "sine", 1000, 2, 0.1)

    assert sent == ["CUSTOM1:CUSTOM_SINE 1000.0|2.0|0.1"]


def test_compound_function_validates_later_kwargs_before_standard_write() -> None:
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    sent: list[str] = []
    generator._send_command = sent.append

    with pytest.raises(ValidationError, match="Unexpected keyword argument"):
        generator.set_function(1, "sine", frequency=1000, not_declared=1)

    assert sent == []


@pytest.mark.parametrize(
    ("parameter", "value"),
    [("frequency", 1e100), ("amplitude", 1e100), ("offset", 1e100)],
)
def test_compound_standard_parameter_uses_profile_range_validation(
    parameter: str, value: float
) -> None:
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    sent: list[str] = []
    generator._send_command = sent.append

    with pytest.raises(InstrumentParameterError):
        generator.set_function(1, "sine", **{parameter: value})

    assert sent == []


def test_function_send_error_is_not_retried_with_guessed_scpi() -> None:
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    sent: list[str] = []

    def fail(command: str) -> None:
        sent.append(command)
        raise RuntimeError("backend failure")

    generator._send_command = fail
    with pytest.raises(RuntimeError, match="backend failure"):
        generator.set_function(1, "sine")

    assert sent == ["SOUR1:FUNC SIN"]


@pytest.mark.parametrize(
    ("method", "query", "response"),
    [
        ("get_function", "SOUR1:FUNC?", "SIN"),
        ("get_frequency", "SOUR1:FREQ?", "1000"),
        ("get_amplitude", "SOUR1:VOLTage?", "1"),
        ("get_offset", "SOUR1:VOLTage:OFFSet?", "0"),
        ("get_output_state", "OUTPut1:STATe?", "1"),
    ],
)
def test_declared_getter_uses_profile_query_once_without_fallback(
    method: str, query: str, response: str
) -> None:
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    queried: list[str] = []

    def fail(command: str) -> str:
        queried.append(command)
        raise RuntimeError("backend failure")

    generator._query = fail
    with pytest.raises(RuntimeError, match="backend failure"):
        getattr(generator, method)(1)

    assert queried == [query]


@pytest.mark.parametrize(
    "method",
    [
        "get_frequency",
        "get_amplitude",
        "get_offset",
        "get_voltage_limit_high",
        "get_voltage_limit_low",
    ],
)
@pytest.mark.parametrize("query_type", ["DEF", "default", "MAXimum-ish"])
def test_native_bound_getters_reject_undocumented_query_type_before_io(
    method: str, query_type: str
) -> None:
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    queried: list[str] = []
    generator._query = lambda command: queried.append(command) or "1"

    with pytest.raises(InstrumentParameterError, match="not declared by the getter's profile"):
        getattr(generator, method)(1, query_type=query_type)

    assert queried == []


@pytest.mark.parametrize(
    ("query_type", "expected"),
    [("min", "MINimum"), ("MAX", "MAXimum"), ("minimum", "MINimum")],
)
def test_native_bound_query_aliases_keep_canonical_scpi_tokens(
    query_type: str, expected: str
) -> None:
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)

    command, _ = generator._profile_limit_query("get_frequency", 1, query_type)

    assert command == f"SOUR1:FREQ? {expected}"


def test_native_bound_getter_uses_profile_declared_query_selector() -> None:
    profile = _profile_dict()
    profile["operation_options"]["get_frequency"]["parameters"]["query_type"]["options"].append(
        {"value": "peak", "aliases": ["pk"], "transport": {"value": "PEAK"}}
    )
    generator = AutoInstrument.from_config(profile, simulate=True)
    queries: list[str] = []
    generator._query = lambda command: queries.append(command) or "1234"

    assert generator.get_frequency(1, "PK") == pytest.approx(1234)
    assert queries == ["SOUR1:FREQ? PEAK"]


@pytest.mark.parametrize(
    ("function", "amplitude", "load", "expected"),
    [
        ("ramp", 2.8868, 50, 5.0),
        ("noise", 1.1364, 50, 5.0),
        ("ramp", 5.7735, "infinity", 10.0),
        ("noise", 2.2727, "infinity", 10.0),
    ],
)
def test_native_rms_peak_factors_use_measured_load_context(
    function, amplitude, load, expected
) -> None:
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    load_key = generator._awg_load_key(load)

    assert load_key == ("infinity" if load == "infinity" else "50")
    assert generator._awg_amplitude_peak(1, amplitude, function, "VRMS", load_key) == pytest.approx(
        expected, abs=0.0002
    )


@pytest.mark.parametrize(
    ("function", "unit", "endpoint", "exact_peak"),
    [
        ("ramp", "VRMS", 2.8868, 5.0),
        ("noise", "VRMS", 1.1364, 5.0),
        ("sine", "VRMS", 3.5355, 5.0),
        ("square", "DBM", 26.99, 5.0),
    ],
)
def test_native_numeric_amplitude_endpoint_is_normalized_to_token(
    function, unit, endpoint, exact_peak
) -> None:
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    sent: list[str] = []
    generator._send_command = sent.append

    def query(command: str) -> str:
        if "FUNC?" in command:
            return {"sine": "SIN", "square": "SQU", "noise": "NOIS"}.get(function, function.upper())
        if "LOAD?" in command:
            return "50"
        if "UNIT?" in command:
            return unit
        if "OFFSet?" in command:
            return "0"
        if "VOLTage? MINimum" in command:
            return "0.0005"
        if "VOLTage? MAXimum" in command:
            return str(endpoint)
        if "OFFSet? MINimum" in command:
            return "-5"
        if "OFFSet? MAXimum" in command:
            return "5"
        if "VOLTage?" in command:
            return "1"
        raise AssertionError(f"Unexpected query: {command}")

    generator._query = query
    generator.set_amplitude(1, endpoint)

    assert sent == ["SOUR1:VOLTage MAXimum"]
    assert exact_peak == 5.0


def test_non_endpoint_amplitude_above_exact_unit_envelope_is_rejected() -> None:
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    sent: list[str] = []
    generator._send_command = sent.append
    generator._query = lambda command: (
        "RAMP"
        if "FUNC?" in command
        else "50"
        if "LOAD?" in command
        else "VRMS"
        if "UNIT?" in command
        else "0"
        if "OFFSet?" in command
        else "0.000289"
        if "VOLTage? MINimum" in command
        else "2.8868"
        if "VOLTage? MAXimum" in command
        else "1"
    )

    with pytest.raises(InstrumentParameterError, match="exact native amplitude envelope"):
        generator.set_amplitude(1, 2.88679)
    assert sent == []


def test_pulse_facade_validates_period_frequency_and_bridges_before_function() -> None:
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    sent: list[str] = []
    generator._send_command = sent.append

    def query(command: str) -> str:
        if "FUNC?" in command:
            return "SIN"
        if "FREQ?" in command:
            return "20000000"
        if "LOAD?" in command:
            return "50"
        if "UNIT?" in command:
            return "VPP"
        if "OFFSet?" in command:
            return "0"
        if "VOLTage?" in command:
            return "1"
        raise AssertionError(f"Unexpected query: {command}")

    generator._query = query
    generator.channel(1).setup_pulse(1_000.0, 0.5)

    assert sent[0] == "SOUR1:FREQ 1000.0"
    assert sent[1] == "SOUR1:FUNC PULS"


def test_compound_amplitude_and_offset_choose_safe_reverse_order() -> None:
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    sent: list[str] = []
    generator._send_command = sent.append

    def query(command: str) -> str:
        if "FUNC?" in command:
            return "SIN"
        if "FREQ?" in command:
            return "1000"
        if "LOAD?" in command:
            return "50"
        if "UNIT?" in command:
            return "VPP"
        if "OFFSet?" in command:
            return "4"
        if "VOLTage?" in command:
            return "0.1"
        return "0"

    generator._query = query
    generator.set_function(1, "sine", amplitude=10.0, offset=0.0)

    assert sent.index("SOUR1:VOLTage:OFFSet 0.0") < sent.index("SOUR1:VOLTage MAXimum")


def test_dc_compound_offset_is_limited_by_profile_peak_envelope() -> None:
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    sent: list[str] = []
    generator._send_command = sent.append
    generator._query = lambda command: (
        "SIN"
        if "FUNC?" in command
        else "50"
        if "LOAD?" in command
        else "VPP"
        if "UNIT?" in command
        else "1000"
        if "FREQ?" in command
        else "1"
    )

    with pytest.raises(InstrumentParameterError, match="peak budget"):
        generator.set_function(1, "dc", amplitude=0.001, offset=5.1)
    assert sent == []


@pytest.mark.parametrize(
    ("unit", "value", "offset", "minimum", "maximum", "command_value"),
    [
        ("VPP", 10.0, 5.0, 0.001, 10.0, "MAXimum"),
        ("DBM", -53.01, 0.0, -53.01, 26.99, "MINimum"),
    ],
)
def test_dc_amplitude_endpoints_do_not_consume_output_peak_budget(
    unit, value, offset, minimum, maximum, command_value
) -> None:
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    sent: list[str] = []
    generator._send_command = sent.append

    def query(command: str) -> str:
        if "FUNC?" in command:
            return "DC"
        if "LOAD?" in command:
            return "50"
        if "UNIT?" in command:
            return unit
        if "OFFSet?" in command:
            return str(offset)
        if "LIMit:STATe?" in command:
            return "OFF"
        if "VOLTage? MINimum" in command:
            return str(minimum)
        if "VOLTage? MAXimum" in command:
            return str(maximum)
        raise AssertionError(f"Unexpected query: {command}")

    generator._query = query
    generator.set_amplitude(1, value)

    assert sent == [f"SOUR1:VOLTage {command_value}"]


def test_ramp_dbm_native_max_uses_exact_peak_budget() -> None:
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    sent: list[str] = []
    generator._send_command = sent.append

    def query(command: str) -> str:
        if "FUNC?" in command:
            return "RAMP"
        if "LOAD?" in command:
            return "50"
        if "UNIT?" in command:
            return "DBM"
        if "OFFSet?" in command:
            return "0"
        if "LIMit:STATe?" in command:
            return "OFF"
        if "VOLTage? MINimum" in command:
            return "-57.782"
        if "VOLTage? MAXimum" in command:
            return "22.218"
        raise AssertionError(f"Unexpected query: {command}")

    generator._query = query
    generator.set_amplitude(1, 22.218)

    assert sent == ["SOUR1:VOLTage MAXimum"]


def test_unchanged_function_compound_uses_live_native_endpoint_at_finite_load() -> None:
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    sent: list[str] = []
    generator._send_command = sent.append

    def query(command: str) -> str:
        if "FUNC?" in command:
            return "SIN"
        if "FREQ?" in command:
            return "1000"
        if "LOAD?" in command:
            return "100"
        if "UNIT?" in command:
            return "DBM"
        if "LIMit:STATe?" in command:
            return "OFF"
        if "OFFSet?" in command:
            return "0"
        if "VOLTage? MAXimum" in command:
            return "23.468"
        if "VOLTage? MINimum" in command:
            return "-56.532"
        if "VOLTage?" in command:
            return "23.468"
        raise AssertionError(f"Unexpected query: {command}")

    generator._query = query
    generator.set_function(1, "sine", frequency=1000, amplitude=23.468, offset=0)

    assert "SOUR1:VOLTage MAXimum" in sent


def test_compound_transition_orders_updates_inside_enabled_output_limits() -> None:
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    sent: list[str] = []
    generator._send_command = sent.append
    generator.get_voltage_limits_state = lambda channel: True

    def query(command: str) -> str:
        if "FUNC?" in command:
            return "SIN"
        if "FREQ?" in command:
            return "1000"
        if "LOAD?" in command:
            return "50"
        if "UNIT?" in command:
            return "VPP"
        if "LIMit:LOW?" in command:
            return "1"
        if "LIMit:HIGH?" in command:
            return "4"
        if "OFFSet?" in command:
            return "2"
        if "VOLTage?" in command:
            return "0.1"
        raise AssertionError(f"Unexpected query: {command}")

    generator._query = query
    generator.set_function(1, "sine", amplitude=3.0, offset=2.5)

    assert sent.index("SOUR1:VOLTage:OFFSet 2.5") < sent.index("SOUR1:VOLTage 3.0")


def test_offset_update_accepts_live_minimum_readback_at_one_ohm() -> None:
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    sent: list[str] = []
    generator._send_command = sent.append

    def query(command: str) -> str:
        if "FUNC?" in command:
            return "SIN"
        if "FREQ?" in command:
            return "1000"
        if "LOAD?" in command:
            return "1"
        if "UNIT?" in command:
            return "VPP"
        if "LIMit:STATe?" in command:
            return "OFF"
        if "OFFSet?" in command:
            return "0"
        if "VOLTage? MINimum" in command:
            return "0.000039"
        if "VOLTage? MAXimum" in command:
            return "0.39216"
        if "VOLTage?" in command:
            return "0.000039"
        raise AssertionError(f"Unexpected query: {command}")

    generator._query = query
    generator.set_function(1, "sine", offset=0)

    assert sent == ["SOUR1:FUNC SIN", "SOUR1:VOLTage:OFFSet 0.0"]


def test_apply_waveform_alias_receives_joint_peak_preflight() -> None:
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    sent: list[str] = []
    generator._send_command = sent.append
    generator._query = lambda command: "50" if "LOAD?" in command else "VPP"

    with pytest.raises(InstrumentParameterError, match="peak budget"):
        generator.apply_waveform_settings("1", "SIN", 1000, 10, 1)

    assert sent == []


@pytest.mark.parametrize(
    ("load", "unit", "current", "minimum", "maximum"),
    [
        (1, "VPP", 0.000039, 0.000039, 0.39216),
        (100, "VPP", 0.001333, 0.001333, 13.333),
        (100, "VRMS", 0.000471, 0.000471, 4.714),
        (10000, "VPP", 0.00199, 0.00199, 19.9),
        (10000, "DBM", -73.054, -73.054, -23.054),
        (1, "VPP", 0.39216, 0.000039, 0.39216),
    ],
)
def test_direct_offset_zero_accepts_native_amplitude_endpoint_readback(
    load, unit, current, minimum, maximum
) -> None:
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    sent: list[str] = []
    generator._send_command = sent.append

    def query(command: str) -> str:
        if "FUNC?" in command:
            return "SIN"
        if "LOAD?" in command:
            return str(load)
        if "UNIT?" in command:
            return unit
        if "LIMit:STATe?" in command:
            return "OFF"
        if "OFFSet? MINimum" in command:
            return "-10"
        if "OFFSet? MAXimum" in command:
            return "10"
        if "OFFSet?" in command:
            return "0"
        if "VOLTage? MINimum" in command:
            return str(minimum)
        if "VOLTage? MAXimum" in command:
            return str(maximum)
        if "VOLTage?" in command:
            return str(current)
        raise AssertionError(f"Unexpected query: {command}")

    generator._query = query
    generator.set_offset(1, 0)

    assert sent == ["SOUR1:VOLTage:OFFSet 0.0"]


@pytest.mark.parametrize(
    ("channel", "load", "unit", "maximum"),
    [
        (1, 1, "VRMS", 0.13865),
        (1, 100, "DBM", 23.468),
        (2, 1, "VRMS", 0.13865),
        (2, 100, "DBM", 23.468),
    ],
)
def test_native_max_readback_uses_live_endpoint_for_offset_and_extents(
    channel, load, unit, maximum
) -> None:
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    sent: list[str] = []
    generator._send_command = sent.append

    def query(command: str) -> str:
        if "FUNC?" in command:
            return "SIN"
        if "LOAD?" in command:
            return str(load)
        if "UNIT?" in command:
            return unit
        if "LIMit:STATe?" in command:
            return "OFF"
        if "OFFSet? MINimum" in command:
            return "-10"
        if "OFFSet? MAXimum" in command:
            return "10"
        if "OFFSet?" in command:
            return "0"
        if "VOLTage? MINimum" in command:
            return "-56.532" if unit == "DBM" else "0.000014"
        if "VOLTage? MAXimum" in command:
            return str(maximum)
        if "VOLTage?" in command:
            return str(maximum)
        raise AssertionError(f"Unexpected query: {command}")

    generator._query = query
    generator.set_amplitude(channel, "MAX")

    extents = generator._awg_active_output_extents(channel)
    assert extents is not None
    peak_limit = generator._awg_load_peak_limit(
        load, generator._awg_native_contract("set_function")
    )
    assert extents == (-peak_limit, peak_limit)

    generator.set_offset(channel, 0)

    assert sent == [
        f"SOUR{channel}:VOLTage MAXimum",
        f"SOUR{channel}:VOLTage:OFFSet 0.0",
    ]


@pytest.mark.parametrize(
    ("response", "expected"),
    [("1", "ON"), ("ON", "ON"), ("TRUE", "ON"), ("0", "OFF"), ("OFF", "OFF")],
)
def test_output_state_accepts_declared_boolean_response_forms(response, expected) -> None:
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    generator._query = lambda _: response

    assert generator.get_output_state(1) is (expected == "ON")


def test_output_state_rejects_unknown_response() -> None:
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    generator._query = lambda _: "MAYBE"

    with pytest.raises(InstrumentCommunicationError, match="Unexpected response"):
        generator.get_output_state(1)


def test_awg_simulator_readbacks_follow_writes() -> None:
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)

    generator.set_frequency(1, 1234.0)
    generator.set_amplitude(1, 2.5)
    generator.set_offset(1, 0.25)
    generator.set_output_state(1, "on")

    assert generator.get_frequency(1) == pytest.approx(1234.0)
    assert generator.get_amplitude(1) == pytest.approx(2.5)
    assert generator.get_offset(1) == pytest.approx(0.25)
    assert generator.get_output_state(1) is True


def test_malformed_profile_template_fails_before_any_write() -> None:
    profile = _profile_dict()
    profile["scpi"]["commands"]["set_function"]["template"] = (
        "SOUR{channel}:FUNC {function} {missing}"
    )
    generator = AutoInstrument.from_config(profile, simulate=True)
    sent: list[str] = []
    generator._send_command = sent.append
    with pytest.raises(Exception, match="missing"):
        generator.set_function(1, "sine")

    assert sent == []


@pytest.mark.parametrize(
    "parameter,value", [("frequency", 1000.0), ("amplitude", 1.0), ("offset", 0.1)]
)
@pytest.mark.parametrize("compound", [False, True])
def test_numeric_scpi_constraints_receive_numeric_transport_values(parameter, value, compound):
    profile = _profile_dict()
    alias = f"set_{parameter}"
    profile["scpi"]["commands"][alias]["parameters"][parameter] = {
        "kind": "range",
        "min": 0,
        "max": 20_000_000,
    }
    generator = AutoInstrument.from_config(profile, simulate=True)
    sent = []
    generator._send_command = sent.append
    generator._query = lambda query: (
        "-10"
        if "MINimum" in query and "OFFSet" in query
        else "0"
        if "MINimum" in query
        else "10"
        if "MAXimum" in query and "OFFSet" in query
        else "20000000"
        if "MAXimum" in query and "FREQ" in query
        else "20"
        if "MAXimum" in query
        else "50"
        if "LOAD" in query
        else "SIN"
        if "FUNC?" in query
        else "VPP"
        if "UNIT" in query
        else "1"
        if query.endswith("?")
        else "0"
    )
    if compound:
        generator.set_function(1, "sine", **{parameter: value})
    else:
        getattr(generator, alias)(1, value)
    expected = generator._scpi_engine.build(alias, channel=1, **{parameter: value})
    if compound:
        expected = ["SOUR1:FUNC SIN"] + expected
    assert sent == expected


@pytest.mark.parametrize(
    "method,settings,shape,function",
    [
        ("setup_square", {}, "SOUR1:FUNC:SQUare:DCYCle 50.0", "SQU"),
        ("setup_square", {"duty_cycle": 25.0}, "SOUR1:FUNC:SQUare:DCYCle 25.0", "SQU"),
        ("setup_ramp", {}, "SOUR1:FUNC:RAMP:SYMMetry 50.0", "RAMP"),
        ("setup_ramp", {"symmetry": 30.0}, "SOUR1:FUNC:RAMP:SYMMetry 30.0", "RAMP"),
    ],
)
def test_shape_facades_transmit_explicit_defaults_and_selected_values(
    method, settings, shape, function
):
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    sent = []
    generator._send_command = sent.append
    getattr(generator.channel(1), method)(1000.0, 1.0, **settings)
    assert sent == [
        f"SOUR1:FUNC {function}",
        "SOUR1:FREQ 1000.0",
        "SOUR1:VOLTage:OFFSet 0.0",
        "SOUR1:VOLTage:UNIT VPP",
        "SOUR1:VOLTage 1.0",
        shape,
    ]


def test_pulse_facade_transmits_explicit_width_through_profile():
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    sent = []
    generator._send_command = sent.append
    generator.channel(1).setup_pulse(1000.0, 1.0, width=0.0001)
    assert sent == [
        "SOUR1:FUNC PULS",
        "SOUR1:VOLTage:OFFSet 0.0",
        "SOUR1:VOLTage:UNIT VPP",
        "SOUR1:VOLTage 1.0",
        "SOUR1:FUNC:PULS:PERiod 0.001",
        "SOUR1:FUNC:PULS:WIDTh 0.0001",
    ]


@pytest.mark.parametrize("method", ["setup_sine", "setup_square", "setup_ramp", "setup_pulse"])
def test_facades_validate_later_amplitude_before_writing(method):
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    sent = []
    generator._send_command = sent.append
    with pytest.raises(InstrumentParameterError):
        getattr(generator.channel(1), method)(1000.0, 1e100)
    assert sent == []


@pytest.mark.parametrize("method", ["setup_sine", "setup_square", "setup_ramp", "setup_pulse"])
def test_facades_validate_phase_before_writing(method):
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    sent = []
    generator._send_command = sent.append
    with pytest.raises(InstrumentParameterError, match="finite"):
        getattr(generator.channel(1), method)(1000.0, 1.0, phase=float("nan"))
    assert sent == []
