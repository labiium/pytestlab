from pathlib import Path

import pytest
import yaml

from pytestlab import AutoInstrument
from pytestlab.errors import InstrumentParameterError


@pytest.mark.parametrize("impedance", [0, 0.5, 10000.1, 1e6, "1e6", float("nan"), -float("inf")])
@pytest.mark.parametrize("facade", [False, True])
def test_edu_load_rejects_invalid_numeric_values_before_io(monkeypatch, impedance, facade):
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    commands = []
    monkeypatch.setattr(generator, "_send_command", commands.append)

    with pytest.raises(InstrumentParameterError):
        if facade:
            generator.channel(1).set_load_impedance(impedance)
        else:
            generator.set_output_load_impedance(1, impedance)

    assert commands == []


@pytest.mark.parametrize(
    ("impedance", "token"),
    [
        (1, "1"),
        (50, "50"),
        (10000, "10000"),
        ("INF", "INFinity"),
        ("INFinity", "INFinity"),
        (float("inf"), "INFinity"),
        ("MIN", "MINimum"),
        ("MAX", "MAXimum"),
        ("DEF", "DEFault"),
    ],
)
def test_edu_load_preserves_valid_numbers_and_special_values(monkeypatch, impedance, token):
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    commands = []
    monkeypatch.setattr(generator, "_send_command", commands.append)
    if str(impedance).casefold() in {"inf", "infinity"} or impedance == float("inf"):
        monkeypatch.setattr(generator, "_query", lambda command: "VPP")

    generator.set_output_load_impedance(1, impedance)

    assert commands == [f"OUTPut1:LOAD {token}"]


def test_load_limits_come_from_the_selected_profile(monkeypatch):
    path = Path(__file__).parents[2] / "pytestlab/profiles/keysight/EDU33212A.yaml"
    profile = yaml.safe_load(path.read_text())
    spec = profile["operation_options"]["set_output_load_impedance"]["parameters"]["impedance"]
    spec.update(kind="range", min=1, max=2e6)
    generator = AutoInstrument.from_config(profile, simulate=True)
    commands = []
    monkeypatch.setattr(generator, "_send_command", commands.append)

    generator.set_output_load_impedance(1, 1e6)

    assert commands == ["OUTPut1:LOAD 1000000"]


def test_dbm_load_cannot_be_changed_to_high_impedance(monkeypatch):
    generator = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    commands = []
    monkeypatch.setattr(generator, "_send_command", commands.append)
    monkeypatch.setattr(generator, "_query", lambda command: "DBM")

    with pytest.raises(InstrumentParameterError, match="while the amplitude unit is dBm"):
        generator.set_output_load_impedance(1, "INF")

    assert commands == []
