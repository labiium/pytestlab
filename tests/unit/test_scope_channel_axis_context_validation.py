from __future__ import annotations

import pytest

from pytestlab import AutoInstrument
from pytestlab.errors import InstrumentDataError
from pytestlab.errors import InstrumentParameterError


def _mock_axis_io(scope, monkeypatch, *, probe: str, impedance: str | None = None):
    queries: list[str] = []
    sent: list[str] = []

    def query_alias(alias: str, **parameters: object) -> str:
        queries.append(alias)
        if alias == "probe_get":
            return probe
        if alias == "channel_input":
            assert impedance is not None
            return impedance
        if alias == "get_channel_offset":
            return "0"
        raise AssertionError(f"unexpected context query alias {alias!r}")

    monkeypatch.setattr(scope, "_query_profile_alias", query_alias)
    monkeypatch.setattr(scope, "_send_command", sent.append)
    monkeypatch.setattr(scope, "_wait", lambda: None)
    return queries, sent


def test_dsox_rejects_scale_below_manual_limit_before_write(monkeypatch):
    scope = AutoInstrument.from_config("keysight/DSOX1204G", simulate=True)
    queries, sent = _mock_axis_io(scope, monkeypatch, probe="1")

    with pytest.raises(InstrumentParameterError, match="outside the profile-declared range"):
        scope.set_channel_axis(1, 0.0003668, 0.0)

    assert queries == ["probe_get"]
    assert sent == []


@pytest.mark.parametrize(
    ("impedance", "scale", "expected_min", "expected_max"),
    [
        ("DC50", 0.005, 0.01, 10),
        ("DC", 0.005, 0.01, 50),
    ],
)
def test_mxr_probe_and_impedance_limits_are_contextual_and_preflighted(
    monkeypatch, impedance, scale, expected_min, expected_max
):
    scope = AutoInstrument.from_config("keysight/MXR404A", simulate=True)
    queries, sent = _mock_axis_io(scope, monkeypatch, probe="10", impedance=impedance)
    description = scope.describe_operation(
        "channel_axis",
        context={
            "probe_attenuation": 10,
            "input_impedance": 50 if impedance == "DC50" else 1000000,
        },
    )
    scale_constraints = description["parameters"]["scale"]["constraints"]

    assert scale_constraints["min"] == expected_min
    assert scale_constraints["max"] == expected_max
    with pytest.raises(InstrumentParameterError, match="outside the profile-declared range"):
        scope.set_channel_axis(1, scale, 0.0)

    assert queries == ["probe_get", "channel_input"]
    assert sent == []


def test_mxr_accepts_limits_at_selected_context_boundaries(monkeypatch):
    scope = AutoInstrument.from_config("keysight/MXR404A", simulate=True)
    queries, sent = _mock_axis_io(scope, monkeypatch, probe="10", impedance="DC50")

    scope.set_channel_axis(1, 0.01, 0.0)

    assert queries == ["probe_get", "channel_input", "get_channel_offset"]
    assert sent == [":CHANnel1:SCALe 0.01", ":CHANnel1:OFFSet 0.0"]


@pytest.mark.parametrize(
    ("profile", "probe", "impedance", "scale"),
    [
        ("keysight/DSOX1204G", "0.1", None, 0.00005),
        ("keysight/DSOX1204G", "2", None, 20.0),
        ("keysight/DSOX1204G", "3.2", None, 0.0016),
        ("keysight/DSOX1204G", "10", None, 100.0),
        ("keysight/MXR404A", "0.1", "DC50", 0.0001),
        ("keysight/MXR404A", "2", "DC50", 2.0),
        ("keysight/MXR404A", "3.2", "DC50", 0.0032),
        ("keysight/MXR404A", "10", "DC50", 10.0),
        ("keysight/MXR404A", "0.1", "DC", 0.0001),
        ("keysight/MXR404A", "2", "DC", 10.0),
        ("keysight/MXR404A", "3.2", "DC", 0.0032),
        ("keysight/MXR404A", "10", "DC", 50.0),
    ],
)
def test_scale_accepts_contextual_endpoints_for_numeric_probe_factors(
    monkeypatch, profile, probe, impedance, scale
):
    scope = AutoInstrument.from_config(profile, simulate=True)
    _queries, sent = _mock_axis_io(scope, monkeypatch, probe=probe, impedance=impedance)

    scope.set_channel_axis(1, scale, 0.0)

    assert sent[0] == f":CHANnel1:SCALe {scale}"


@pytest.mark.parametrize("probe", ["0", "nan", "-2"])
def test_invalid_live_probe_context_fails_before_scale_or_offset_write(monkeypatch, probe):
    scope = AutoInstrument.from_config("keysight/DSOX1204G", simulate=True)
    _queries, sent = _mock_axis_io(scope, monkeypatch, probe=probe)

    with pytest.raises(InstrumentDataError, match="positive finite attenuation"):
        scope.set_channel_axis(1, 0.1, 0.0)

    assert sent == []


def test_axis_discovery_exposes_contextual_ranges_without_false_global_bounds():
    scope = AutoInstrument.from_config("keysight/DSOX1204G", simulate=True)

    description = scope.describe_operation("channel_axis")
    constraints = description["parameters"]["scale"]["constraints"]

    assert "min" not in constraints
    assert "max" not in constraints
    assert constraints["contextual_ranges"]
    assert constraints["multiplier_parameter"] == "probe_attenuation"
    assert description["parameters"]["scale"]["dependencies"] == [
        "probe_attenuation",
        "input_impedance",
    ]
    assert description["parameters"]["probe_attenuation"]["kind"] == "range"
    assert description["parameters"]["probe_attenuation"]["constraints"].get("max") is None


@pytest.mark.parametrize(
    ("profile", "context", "expected_min", "expected_max"),
    [
        (
            "keysight/DSOX1204G",
            {"probe_attenuation": 3.2, "input_impedance": 1000000},
            0.0016,
            32.0,
        ),
        (
            "keysight/MXR404A",
            {"probe_attenuation": 3.2, "input_impedance": 50},
            0.0032,
            3.2,
        ),
    ],
)
def test_discovery_scales_profile_ranges_by_arbitrary_probe_factor(
    profile, context, expected_min, expected_max
):
    scope = AutoInstrument.from_config(profile, simulate=True)

    constraints = scope.describe_operation("channel_axis", context=context)["parameters"]["scale"][
        "constraints"
    ]

    assert constraints["min"] == pytest.approx(expected_min)
    assert constraints["max"] == pytest.approx(expected_max)


def test_nonfinite_scaled_limit_is_rejected():
    scope = AutoInstrument.from_config("keysight/DSOX1204G", simulate=True)

    with pytest.raises(InstrumentParameterError, match="non-finite scale limit"):
        scope.describe_operation(
            "channel_axis",
            context={"probe_attenuation": 1e308, "input_impedance": 1000000},
        )
