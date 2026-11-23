import pytest

from pytestlab import Bench
from pytestlab.bench import SafetyLimitError
from pytestlab.errors import InstrumentParameterError


@pytest.fixture
def guarded_psu_with_command_log():
    bench = Bench.open(
        {
            "bench_name": "PSU atomic validation",
            "simulate": True,
            "instruments": {
                "psu": {
                    "profile": "keysight/EDU36311A",
                    "safety_limits": {
                        "channels": {
                            1: {"voltage": {"max": 5.0}, "current": {"max": 0.8}},
                            2: {"voltage": {"max": 30.9}, "current": {"max": 2.0}},
                            3: {"voltage": {"max": 5.0}, "current": {"max": 0.8}},
                        }
                    },
                }
            },
        }
    )
    commands = []
    bench._device_instances["psu"]._send_command = commands.append
    try:
        yield bench.psu, commands
    finally:
        bench.close_all()


def test_guarded_channel_preflights_native_channel_range(guarded_psu_with_command_log):
    psu, commands = guarded_psu_with_command_log

    with pytest.raises(InstrumentParameterError):
        psu.channel(2).set(voltage=5.0, current_limit=1.04)

    assert commands == []


@pytest.mark.parametrize(
    ("channel", "below_min"), [(1, 0.0), (1, 0.001), (2, 0.0), (2, 0.0005), (3, 0.0), (3, 0.0005)]
)
def test_guarded_channel_preflights_channel_specific_current_minimum(
    guarded_psu_with_command_log, channel, below_min
):
    psu, commands = guarded_psu_with_command_log
    voltage = 1.0

    with pytest.raises(InstrumentParameterError):
        psu.channel(channel).set(voltage=voltage, current_limit=below_min)

    assert commands == []


def test_guarded_channel_preflights_descriptor_cap(guarded_psu_with_command_log):
    psu, commands = guarded_psu_with_command_log

    with pytest.raises(SafetyLimitError):
        psu.channel(1).set(voltage=4.0, current_limit=0.9)

    assert commands == []


def test_guarded_channel_preflights_nonfinite_second_setpoint(guarded_psu_with_command_log):
    psu, commands = guarded_psu_with_command_log

    with pytest.raises(InstrumentParameterError):
        psu.channel(1).set(voltage=4.0, current_limit=float("nan"))

    assert commands == []


def test_guarded_channel_writes_valid_pair_in_voltage_current_order(
    guarded_psu_with_command_log,
):
    psu, commands = guarded_psu_with_command_log

    psu.channel(3).set(voltage=2.0, current_limit=0.25)

    assert commands == ["VOLT 2.0, (@3)", "CURR 0.25, (@3)"]


@pytest.mark.parametrize("channel,current", [(1, 0.002), (2, 0.001), (3, 0.001)])
def test_guarded_channel_accepts_channel_specific_current_minimum(
    guarded_psu_with_command_log, channel, current
):
    psu, commands = guarded_psu_with_command_log

    psu.channel(channel).set(voltage=1.0, current_limit=current)

    assert commands == [f"VOLT 1.0, (@{channel})", f"CURR {current}, (@{channel})"]
