import math

import pytest
from pydantic import ValidationError

from pytestlab import AutoInstrument
from pytestlab.config.power_supply_config import ChannelSpec


def test_edu36311a_simulation_profile_round_trips_channel_state() -> None:
    psu = AutoInstrument.from_config("keysight/EDU36311A", simulate=True)

    assert "EDU36311A-SIM" in psu.id()
    assert psu.channel(1).get_output_state() is False

    psu.set_voltage(1, 2.5)
    psu.set_current(1, 0.25)
    voltage = psu.read_voltage(1)
    current = psu.read_current(1)
    assert voltage.n == 2.5
    assert current.n == 0.25
    assert set(psu.config.measurement_accuracy) == {
        "read_voltage_ch1",
        "read_current_ch1",
        "read_voltage_ch2",
        "read_current_ch2",
        "read_voltage_ch3",
        "read_current_ch3",
    }
    assert voltage.u == pytest.approx(math.hypot(0.001 * 2.5, 0.005) / math.sqrt(3))
    assert current.u == pytest.approx(math.hypot(0.001 * 0.25, 0.010) / math.sqrt(3))
    with pytest.raises(ValidationError):
        ChannelSpec.model_validate(psu.config.channels[0].model_dump() | {"accuracy": 0.1})

    psu.output(1, True)
    assert psu.channel(1).get_output_state() is True
    psu.output(1, False)
    assert psu.channel(1).get_output_state() is False

    recorded = AutoInstrument.from_config("keysight/EDU36311A_recorded", simulate=True)
    recorded.set_voltage(1, 1.0)
    assert recorded.read_voltage(1).n == 1.0
    assert recorded.read_voltage(1).u > 0
