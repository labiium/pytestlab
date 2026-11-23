from __future__ import annotations

import pytest

from pytestlab import AutoInstrument
from pytestlab.errors import InstrumentParameterError


@pytest.mark.parametrize(
    ("value", "expected_command", "readback", "expected_mode"),
    [
        ("normal", ":ACQuire:AVERage OFF", "0", "NORMAL"),
        ("norm", ":ACQuire:AVERage OFF", "0", "NORMAL"),
        ("average", ":ACQuire:AVERage ON", "1", "AVERAGE"),
        ("aver", ":ACQuire:AVERage ON", "1", "AVERAGE"),
    ],
)
@pytest.mark.parametrize("facade", [False, True])
def test_mxr_acquisition_type_uses_averaging_state(
    monkeypatch, value, expected_command, readback, expected_mode, facade
):
    scope = AutoInstrument.from_config("keysight/MXR404A", simulate=True)
    commands = []
    monkeypatch.setattr(scope, "_send_command", commands.append)
    monkeypatch.setattr(scope, "_wait", lambda: None)
    monkeypatch.setattr(scope, "_query", lambda _query: readback)

    control = scope.acquisition if facade else scope
    control.set_acquisition_type(value)

    assert commands == [expected_command]
    assert scope.acquisition.get_acquisition_type() == expected_mode


@pytest.mark.parametrize("mode", ["peak_detect", "peak", "pdet"])
def test_mxr_peak_detection_uses_acquisition_mode(monkeypatch, mode):
    scope = AutoInstrument.from_config("keysight/MXR404A", simulate=True)
    commands = []
    monkeypatch.setattr(scope, "_send_command", commands.append)
    monkeypatch.setattr(scope, "_wait", lambda: None)
    monkeypatch.setattr(scope, "_query", lambda _: "PDETect")

    scope.acquisition.set_acquisition_type("normal")
    scope.acquisition.set_acquisition_mode(mode)

    assert commands == [":ACQuire:AVERage OFF", ":ACQuire:MODE PDETect"]
    assert scope.acquisition.get_acquisition_mode() == "peak_detect"


@pytest.mark.parametrize(("profile", "response"), [("MXR404A", "1"), ("DSOX1204G", "AVERage")])
def test_average_count_accepts_the_profile_averaging_state(monkeypatch, profile, response):
    scope = AutoInstrument.from_config(f"keysight/{profile}", simulate=True)
    commands = []
    monkeypatch.setattr(scope, "_send_command", commands.append)
    monkeypatch.setattr(scope, "_wait", lambda: None)
    monkeypatch.setattr(scope, "_query", lambda _: response)

    scope.acquisition.set_acquisition_average_count(16)

    assert commands == [":ACQuire:COUNt 16"]


def test_average_count_rejects_normal_acquisition_before_write(monkeypatch):
    scope = AutoInstrument.from_config("keysight/MXR404A", simulate=True)
    commands = []
    monkeypatch.setattr(scope, "_send_command", commands.append)
    monkeypatch.setattr(scope, "_query", lambda _: "0")

    with pytest.raises(InstrumentParameterError):
        scope.acquisition.set_acquisition_average_count(16)

    assert commands == []
