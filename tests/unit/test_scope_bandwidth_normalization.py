from __future__ import annotations

from types import SimpleNamespace

import pytest

from pytestlab import AutoInstrument
from pytestlab.errors import InstrumentDataError
from pytestlab.errors import InstrumentParameterError


def _mock_mxr_bandwidth_context(monkeypatch, scope, *, scale=0.003, impedance=50, probe=1.0):
    monkeypatch.setattr(
        scope,
        "_channel_axis_context",
        lambda channel, operation: {
            "probe_attenuation": probe,
            "input_impedance": impedance,
        },
    )
    monkeypatch.setattr(scope, "get_channel_axis", lambda channel: [scale, 0.0])


def test_legacy_profile_without_operation_options_keeps_bandwidth_fallback(monkeypatch):
    scope = AutoInstrument.from_config("keysight/DSOX1204G", simulate=True)
    scope.config = SimpleNamespace(channels=scope.config.channels, operation_options=None)
    commands: list[str] = []
    monkeypatch.setattr(scope, "_send_command", commands.append)

    scope.set_bandwidth_limit(1, "25E6")

    assert commands == ["CHANnel1:BANDwidth 25E6"]


@pytest.mark.parametrize(
    ("model", "requested", "expected"),
    [
        ("DSOX1204G", "FULL", "CHANnel1:BWLimit OFF"),
        ("DSOX1204G", "fUlL", "CHANnel1:BWLimit OFF"),
        ("DSOX1204G", "OFF", "CHANnel1:BWLimit OFF"),
        ("DSOX1204G", "off", "CHANnel1:BWLimit OFF"),
        ("DSOX1204G", 0, "CHANnel1:BWLimit OFF"),
        ("DSOX1204G", 0.0, "CHANnel1:BWLimit OFF"),
        ("DSOX1204G", "25M", "CHANnel1:BANDwidth 25E6"),
        ("DSOX1204G", 25_000_000.0, "CHANnel1:BANDwidth 25E6"),
        ("MXR404A", "FULL", ":CHANnel1:BWLimit OFF"),
        ("MXR404A", "fUlL", ":CHANnel1:BWLimit OFF"),
        ("MXR404A", "OFF", ":CHANnel1:BWLimit OFF"),
        ("MXR404A", "off", ":CHANnel1:BWLimit OFF"),
        ("MXR404A", 0, ":CHANnel1:BWLimit OFF"),
        ("MXR404A", 0.0, ":CHANnel1:BWLimit OFF"),
        ("MXR404A", "20M", ":CHANnel1:BWLimit 20e6"),
        ("MXR404A", 20_000_000.0, ":CHANnel1:BWLimit 20e6"),
        ("MXR404A", "200M", ":CHANnel1:BWLimit 200e6"),
        ("MXR404A", 200_000_000.0, ":CHANnel1:BWLimit 200e6"),
    ],
)
def test_bandwidth_limit_uses_profile_supported_scpi_values(
    monkeypatch, model: str, requested: str | float, expected: str
) -> None:
    scope = AutoInstrument.from_config(f"keysight/{model}", simulate=True)
    commands: list[str] = []
    monkeypatch.setattr(scope, "_send_command", commands.append)
    if model == "MXR404A" and str(requested).casefold() in {"full", "off", "0", "0.0"}:
        _mock_mxr_bandwidth_context(monkeypatch, scope)

    scope.set_bandwidth_limit(1, requested)

    assert commands == [expected]


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("DSOX1204G", "CHANnel1:BWLimit OFF"),
        ("MXR404A", ":CHANnel1:BWLimit OFF"),
    ],
)
def test_channel_facade_full_bandwidth_uses_filter_off_command(
    monkeypatch, model: str, expected: str
) -> None:
    scope = AutoInstrument.from_config(f"keysight/{model}", simulate=True)
    commands: list[str] = []
    monkeypatch.setattr(scope, "_send_command", commands.append)
    if model == "MXR404A":
        _mock_mxr_bandwidth_context(monkeypatch, scope)

    scope.channel(1).setup(bandwidth_limit="FULL")

    assert commands == [expected]


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("DSOX1204G", "CHANnel1:BWLimit OFF"),
        ("MXR404A", ":CHANnel1:BWLimit OFF"),
    ],
)
def test_scope_setup_full_bandwidth_uses_filter_off_command(
    monkeypatch, model: str, expected: str
) -> None:
    scope = AutoInstrument.from_config(f"keysight/{model}", simulate=True)
    commands: list[str] = []
    monkeypatch.setattr(scope, "_send_command", commands.append)
    if model == "MXR404A":
        _mock_mxr_bandwidth_context(monkeypatch, scope)

    scope.setup_channel(1, bandwidth_limit="FULL")

    assert commands == [expected]


@pytest.mark.parametrize(
    ("model", "requested", "expected"),
    [
        ("DSOX1204G", "25M", "CHANnel1:BANDwidth 25E6"),
        ("MXR404A", "20M", ":CHANnel1:BWLimit 20e6"),
        ("MXR404A", "200M", ":CHANnel1:BWLimit 200e6"),
    ],
)
@pytest.mark.parametrize("entrypoint", ["channel_facade", "scope_setup"])
def test_limited_bandwidth_uses_supported_command_through_facades(
    monkeypatch, model: str, requested: str, expected: str, entrypoint: str
) -> None:
    scope = AutoInstrument.from_config(f"keysight/{model}", simulate=True)
    commands: list[str] = []
    monkeypatch.setattr(scope, "_send_command", commands.append)

    if entrypoint == "channel_facade":
        scope.channel(1).setup(bandwidth_limit=requested)
    else:
        scope.setup_channel(1, bandwidth_limit=requested)

    assert commands == [expected]


@pytest.mark.parametrize(
    ("model", "requested"),
    [
        ("DSOX1204G", "20M"),
        ("DSOX1204G", 10_000_000.0),
        ("MXR404A", "25M"),
        ("MXR404A", 25_000_000.0),
        ("MXR404A", "not-a-bandwidth"),
    ],
)
def test_unsupported_bandwidth_is_rejected_before_scpi_write(
    monkeypatch, model: str, requested: str | float
) -> None:
    scope = AutoInstrument.from_config(f"keysight/{model}", simulate=True)
    commands: list[str] = []
    monkeypatch.setattr(scope, "_send_command", commands.append)

    with pytest.raises(InstrumentParameterError):
        scope.set_bandwidth_limit(1, requested)

    assert commands == []


def test_mxr_full_bandwidth_preflights_input_referred_sensitivity(monkeypatch):
    scope = AutoInstrument.from_config("keysight/MXR404A", simulate=True)
    commands: list[str] = []
    contexts: list[int] = []
    monkeypatch.setattr(scope, "_send_command", commands.append)
    monkeypatch.setattr(
        scope,
        "_channel_axis_context",
        lambda channel, operation: (
            contexts.append(channel) or {"probe_attenuation": 1.0, "input_impedance": 1_000_000}
        ),
    )
    monkeypatch.setattr(scope, "get_channel_axis", lambda channel: [0.002, 0.0])

    with pytest.raises(InstrumentParameterError, match="input-referred scale"):
        scope.channel(1).setup(scale=0.002, bandwidth_limit="full")

    assert contexts == [1]
    assert commands == []


def test_mxr_direct_full_bandwidth_preflights_live_scale(monkeypatch):
    scope = AutoInstrument.from_config("keysight/MXR404A", simulate=True)
    commands: list[str] = []
    monkeypatch.setattr(scope, "_send_command", commands.append)
    _mock_mxr_bandwidth_context(monkeypatch, scope, scale=0.002, impedance=1_000_000, probe=1.0)

    with pytest.raises(InstrumentParameterError, match="input-referred scale"):
        scope.set_bandwidth_limit(1, "full")

    assert commands == []


@pytest.mark.parametrize(
    ("scale", "probe"),
    [
        (0.0, 1.0),
        (-0.001, 1.0),
        (float("nan"), 1.0),
        (float("inf"), 1.0),
        (0.003, 0.0),
    ],
)
def test_mxr_full_bandwidth_rejects_invalid_live_scale_readback(monkeypatch, scale, probe):
    scope = AutoInstrument.from_config("keysight/MXR404A", simulate=True)
    commands: list[str] = []
    monkeypatch.setattr(scope, "_send_command", commands.append)
    _mock_mxr_bandwidth_context(monkeypatch, scope, scale=scale, impedance=50, probe=probe)

    with pytest.raises(InstrumentDataError, match="not a positive finite value"):
        scope.set_bandwidth_limit(1, "full")

    assert commands == []


def test_mxr_full_bandwidth_accepts_boundary_and_50_ohm_context(monkeypatch):
    scope = AutoInstrument.from_config("keysight/MXR404A", simulate=True)
    commands: list[str] = []
    monkeypatch.setattr(scope, "_send_command", commands.append)
    monkeypatch.setattr(
        scope,
        "_channel_axis_context",
        lambda channel, operation: {"probe_attenuation": 1.0, "input_impedance": 1_000_000},
    )
    monkeypatch.setattr(scope, "get_channel_axis", lambda channel: [0.003, 0.0])

    scope.setup_channel(1, bandwidth_limit="full")

    assert commands == [":CHANnel1:BWLimit OFF"]


def test_mxr_probe_change_cannot_hide_insufficient_input_referred_scale(monkeypatch):
    scope = AutoInstrument.from_config("keysight/MXR404A", simulate=True)
    commands: list[str] = []
    monkeypatch.setattr(scope, "_send_command", commands.append)
    _mock_mxr_bandwidth_context(monkeypatch, scope, scale=0.002, impedance=1_000_000, probe=1.0)

    with pytest.raises(InstrumentParameterError, match="input-referred scale"):
        scope.channel(1).setup(probe_attenuation=10, bandwidth_limit="full")

    assert commands == []


def test_mxr_prospective_50_ohm_context_allows_full_bandwidth(monkeypatch):
    scope = AutoInstrument.from_config("keysight/MXR404A", simulate=True)
    commands: list[str] = []
    monkeypatch.setattr(scope, "_send_command", commands.append)
    _mock_mxr_bandwidth_context(monkeypatch, scope, scale=0.002, impedance=1_000_000, probe=1.0)

    scope.setup_channel(1, coupling="DC50", bandwidth_limit="full")

    assert commands == [":CHANnel1:INPut DC50", ":CHANnel1:BWLimit OFF"]


def test_mxr_bandwidth_sensitivity_constraint_is_publicly_described():
    scope = AutoInstrument.from_config("keysight/MXR404A", simulate=True)

    bandwidth_constraints = scope.describe_operation("bandwidth_limit")["parameters"]["bandwidth"]
    setup_constraints = scope.describe_operation("channel_setup")["parameters"]["bandwidth_limit"]

    assert (
        bandwidth_constraints["constraints"]["full_bandwidth_minimum_input_referred_scale"]["value"]
        == 0.003
    )
    assert (
        setup_constraints["constraints"]["full_bandwidth_minimum_input_referred_scale"]["value"]
        == 0.003
    )
