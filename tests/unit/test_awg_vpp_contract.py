from __future__ import annotations

import pytest

from pytestlab import AutoInstrument
from pytestlab.instruments.WaveformGenerator import WaveformGenerator


@pytest.fixture(autouse=True)
def _voltage_limits_off_by_default(monkeypatch):
    monkeypatch.setattr(WaveformGenerator, "get_voltage_limits_state", lambda self, channel: False)


@pytest.mark.parametrize(
    ("method", "args", "kwargs"),
    [
        ("setup_sine", (1_000.0, 0.4), {}),
        ("setup_square", (1_000.0, 0.4), {}),
        ("setup_ramp", (1_000.0, 0.4), {}),
        ("setup_pulse", (1_000.0, 0.4), {}),
        ("setup_arbitrary", ("wave", 1_000.0, 0.4), {}),
    ],
)
def test_vpp_facade_sets_offset_then_vpp_before_amplitude(method, args, kwargs):
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    sent: list[str] = []
    generator._send_command = sent.append

    generator.set_voltage_unit(1, "VRMS")
    assert sent == ["SOUR1:VOLTage:UNIT VRMS"]
    sent.clear()

    getattr(generator.channel(1), method)(*args, **kwargs)

    unit_command = "SOUR1:VOLTage:UNIT VPP"
    amplitude_command = "SOUR1:VOLTage 0.4"
    offset_command = "SOUR1:VOLTage:OFFSet 0.0"
    assert unit_command in sent
    assert offset_command in sent
    assert sent.index(offset_command) < sent.index(unit_command)
    assert sent.index(unit_command) < sent.index(amplitude_command)
    if method == "setup_sine":
        assert sent == [
            "SOUR1:FUNC SIN",
            "SOUR1:FREQ 1000.0",
            "SOUR1:VOLTage:OFFSet 0.0",
            "SOUR1:VOLTage:UNIT VPP",
            "SOUR1:VOLTage 0.4",
        ]


def test_generic_amplitude_setter_keeps_current_unit_contract():
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    sent: list[str] = []
    generator._send_command = sent.append

    generator.set_voltage_unit(1, "VRMS")
    sent.clear()
    generator.set_amplitude(1, 0.4)

    assert sent == ["SOUR1:VOLTage 0.4"]
    sent.clear()
    generator.set_function(1, "sine", frequency=1_000.0, amplitude=0.4)

    assert sent == [
        "SOUR1:FUNC SIN",
        "SOUR1:FREQ 1000.0",
        "SOUR1:VOLTage 0.4",
    ]
