from __future__ import annotations

import numpy as np
import pytest

from pytestlab import AutoInstrument
from pytestlab.errors import InstrumentParameterError
from pytestlab.instruments.Oscilloscope import Preamble


def _mxr_channel_state(monkeypatch, *, probe=1.0, coupling="DC", scale=0.1, offset=0.0):
    scope = AutoInstrument.from_config("keysight/MXR404A", simulate=True)
    state = dict(probe=probe, coupling=coupling, scale=scale, offset=offset)
    commands = []
    monkeypatch.setattr(scope, "_wait", lambda: None)
    monkeypatch.setattr(
        scope, "get_channel_axis", lambda _channel: [state["scale"], state["offset"]]
    )
    monkeypatch.setattr(
        scope,
        "_query_profile_alias",
        lambda alias, **_kwargs: str(
            {
                "probe_get": state["probe"],
                "channel_input": state["coupling"],
                "get_channel_scale": state["scale"],
                "get_channel_offset": state["offset"],
            }[alias]
        ),
    )

    def apply(command):
        token, value = command.rsplit(" ", 1)
        if token.upper().endswith(":INPUT"):
            if value.upper() == "DC50":
                assert state["scale"] <= state["probe"]
                assert state["offset"] == 0
            state["coupling"] = value.upper()
        elif token.upper().endswith(":PROBE:USER"):
            factor = float(value.rsplit(",", 1)[-1])
            ratio = factor / state["probe"]
            state.update(probe=factor, scale=state["scale"] * ratio, offset=state["offset"] * ratio)
        elif token.upper().endswith(":SCALE"):
            state["scale"] = float(value)
        elif token.upper().endswith(":OFFSET"):
            state["offset"] = float(value)
        commands.append(command)

    monkeypatch.setattr(scope, "_send_command", apply)
    return scope, state, commands


@pytest.mark.parametrize(
    "invalid", [dict(coupling="banana"), dict(bandwidth_limit="banana"), dict(offset=100)]
)
def test_facade_complete_preflight_does_not_partially_apply_probe(monkeypatch, invalid):
    scope, _state, commands = _mxr_channel_state(monkeypatch)
    with pytest.raises(InstrumentParameterError):
        scope.channel(1).setup(probe_attenuation=2, scale=0.1, **invalid)
    assert commands == []


def test_facade_axis_uses_prospective_impedance(monkeypatch):
    scope, state, commands = _mxr_channel_state(monkeypatch, coupling="DC50")
    scope.channel(1).setup(scale=5, offset=20, coupling="dc")
    assert state["coupling"] == "DC"
    assert state["scale"] == 5
    assert state["offset"] == 20
    assert ":INPut DC" in commands[0]


def test_facade_axis_uses_prospective_probe_factor(monkeypatch):
    scope, state, _commands = _mxr_channel_state(monkeypatch, coupling="DC50")
    scope.channel(1).setup(probe_attenuation=10, scale=10, offset=30)
    assert state == dict(probe=10, coupling="DC50", scale=10, offset=30)


@pytest.mark.parametrize("coupling", ["dc50", "DC50", "DCFifty"])
def test_facade_bridges_oversized_axis_before_fifty_ohm_input(monkeypatch, coupling):
    scope, state, commands = _mxr_channel_state(monkeypatch, scale=5, offset=40)
    scope.channel(1).setup(scale=0.5, offset=3, coupling=coupling)
    transition = commands.index(":CHANnel1:INPut DC50")
    assert commands[:transition] == [":CHANnel1:OFFSet 0.0", ":CHANnel1:SCALe 0.5"]
    assert state == dict(probe=1, coupling="DC50", scale=0.5, offset=3)


@pytest.mark.parametrize("entrypoint", ["facade", "setup"])
def test_invalid_final_impedance_axis_has_no_writes(monkeypatch, entrypoint):
    scope, _state, commands = _mxr_channel_state(monkeypatch, scale=5, offset=40)
    with pytest.raises(InstrumentParameterError):
        if entrypoint == "facade":
            scope.channel(1).setup(coupling="dc50")
        else:
            scope.setup_channel(1, coupling="dc50")
    assert commands == []


@pytest.mark.parametrize(
    ("profile", "minimum", "maximum"), [("DSOX1204G", 20e-9, 500), ("MXR404A", 50e-12, 200)]
)
def test_acquisition_duration_uses_ten_division_native_range(
    monkeypatch, profile, minimum, maximum
):
    scope = AutoInstrument.from_config(f"keysight/{profile}", simulate=True)
    commands = []
    monkeypatch.setattr(scope, "_send_command", commands.append)
    monkeypatch.setattr(
        scope,
        "_query_profile_alias",
        lambda alias, **_kwargs: "MAIN" if alias == "timebase_mode_query" else "0",
    )
    scope.set_acquisition_time(minimum)
    scope.set_acquisition_time(maximum)
    assert commands == [f":TIMebase:RANGe {minimum}", f":TIMebase:RANGe {float(maximum)}"]
    for invalid in [minimum / 2, maximum + 1, float("inf"), float("nan"), 0, -1]:
        commands.clear()
        with pytest.raises(InstrumentParameterError):
            scope.set_acquisition_time(invalid)
        assert commands == []


def _time_axis_state(
    monkeypatch, profile, *, mode="MAIN", scale=1e-6, position=0.0, effective=None
):
    scope = AutoInstrument.from_config(f"keysight/{profile}", simulate=True)
    state = dict(scale=scale, position=position)
    commands = []
    monkeypatch.setattr(scope, "_wait", lambda: None)
    monkeypatch.setattr(
        scope,
        "_query_profile_alias",
        lambda alias, **_kwargs: str(
            {
                "timebase_mode_query": mode,
                "get_timebase_scale": state["scale"],
                "get_timebase_position": state["position"],
            }[alias]
        ),
    )

    def apply(command):
        token, value = command.rsplit(" ", 1)
        if token.upper().endswith((":SCALE", ":RANGE")):
            assert state["position"] == 0, "existing delay must be neutralized before scale change"
            requested = float(value) / 10 if token.upper().endswith(":RANGE") else float(value)
            state["scale"] = effective if effective is not None else requested
        elif token.upper().endswith(":POSITION"):
            state["position"] = float(value)
        commands.append(command)

    monkeypatch.setattr(scope, "_send_command", apply)
    return scope, state, commands


@pytest.mark.parametrize(
    ("profile", "scale", "position"),
    [
        ("DSOX1204G", 1e-6, -0.000501),
        ("DSOX1204G", 1e-6, 1.00001),
        ("DSOX1204G", 1, -500.001),
        ("DSOX1204G", 1, 500.001),
        ("MXR404A", 1e-6, -200.001),
        ("MXR404A", 20, 200.001),
    ],
)
def test_qualified_horizontal_bounds_reject_before_writes(monkeypatch, profile, scale, position):
    scope, _state, commands = _time_axis_state(monkeypatch, profile)
    with pytest.raises(InstrumentParameterError):
        scope.set_time_axis(scale, position)
    assert commands == []


def test_timebase_scale_transition_neutralizes_existing_position(monkeypatch):
    scope, state, commands = _time_axis_state(monkeypatch, "DSOX1204G", scale=1, position=500)
    scope.set_time_axis(1e-6, 0)
    assert commands == [":TIMebase:POSition 0.0", ":TIMebase:SCALe 1e-06"]
    assert state == dict(scale=1e-6, position=0)


def test_position_revalidated_after_effective_timebase_scale(monkeypatch):
    scope, state, commands = _time_axis_state(monkeypatch, "DSOX1204G", effective=0.0001)
    with pytest.raises(InstrumentParameterError, match="effective"):
        scope.set_time_axis(0.00010001, 1.00005)
    assert commands == [":TIMebase:SCALe 0.00010001"]
    assert state["position"] == 0


def test_dsox_negative_position_uses_qualified_ceiling_screen_width(monkeypatch):
    scope, state, _commands = _time_axis_state(monkeypatch, "DSOX1204G", effective=0.0001235)
    scope.set_time_axis(0.00012345, -0.0015)
    assert state["position"] == -0.0015


@pytest.mark.parametrize(
    ("requested", "effective", "position"),
    [
        (0.0001235, 0.0001235, 1.235),
        (0.00012345, 0.0001235, 1.2349),
    ],
)
def test_dsox_position_accepts_measured_decimal_and_quantized_endpoints(
    monkeypatch, requested, effective, position
):
    scope, state, _commands = _time_axis_state(monkeypatch, "DSOX1204G", effective=effective)
    scope.set_time_axis(requested, position)
    assert state["position"] == position


def test_negative_position_ceiling_compares_exact_decimal_boundaries(monkeypatch):
    scope, state, _commands = _time_axis_state(
        monkeypatch, "DSOX1204G", effective=0.00005000000000001
    )
    scope.set_time_axis(0.00005000000000001, -0.001)
    assert state["position"] == -0.001


def test_changed_timebase_defers_conditional_position_until_effective_scale(monkeypatch):
    scope, state, commands = _time_axis_state(monkeypatch, "DSOX1204G")
    with pytest.raises(InstrumentParameterError, match="effective"):
        scope.set_time_axis(1, -10.001)
    assert commands == [":TIMebase:SCALe 1.0"]
    assert state["position"] == 0


def test_unchanged_measured_timebase_rejects_invalid_position_before_writes(monkeypatch):
    scope, _state, commands = _time_axis_state(monkeypatch, "DSOX1204G", scale=1)
    with pytest.raises(InstrumentParameterError):
        scope.set_time_axis(1, -10.001)
    assert commands == []


@pytest.mark.parametrize(
    ("profile", "old_position", "expected_position"),
    [
        ("DSOX1204G", 500, 0),
        ("MXR404A", 150, 150),
    ],
)
def test_duration_neutralizes_delay_and_preserves_it_only_when_compatible(
    monkeypatch, profile, old_position, expected_position
):
    scope, state, commands = _time_axis_state(monkeypatch, profile, scale=1, position=old_position)
    scope.set_acquisition_time(1e-5)
    assert commands[:2] == [":TIMebase:POSition 0.0", ":TIMebase:RANGe 1e-05"]
    assert state["position"] == expected_position


def test_duration_keeps_neutral_delay_when_effective_scale_changes_its_limit(monkeypatch):
    scope, state, commands = _time_axis_state(
        monkeypatch, "DSOX1204G", scale=1, position=1.00005, effective=0.0001
    )
    scope.set_acquisition_time(0.0010001)
    assert state["position"] == 0
    assert all(not command.endswith("1.00005") for command in commands)


def test_duration_preserves_retained_position_in_effective_scale_fringe(monkeypatch):
    scope, state, commands = _time_axis_state(
        monkeypatch, "DSOX1204G", scale=1, position=1.2349, effective=0.0001235
    )
    scope.set_acquisition_time(0.0012345)
    assert state["position"] == 1.2349
    assert commands[-1] == ":TIMebase:POSition 1.2349"


@pytest.mark.parametrize("method", ["axis", "duration"])
def test_dsox_xy_unavailable_timebase_operations_fail_before_writes(monkeypatch, method):
    scope, _state, commands = _time_axis_state(monkeypatch, "DSOX1204G", mode="XY")
    with pytest.raises(InstrumentParameterError, match="XY"):
        if method == "axis":
            scope.set_time_axis(1e-6, 0)
        else:
            scope.set_acquisition_time(1e-3)
    assert commands == []


@pytest.mark.parametrize(
    ("profile", "factor"),
    [
        ("DSOX1204G", 0.1),
        ("DSOX1204G", 3.2),
        ("DSOX1204G", 10_000),
        ("MXR404A", 0.0001),
        ("MXR404A", 3.2),
        ("MXR404A", 1000),
    ],
)
@pytest.mark.parametrize("entrypoint", ["setter", "setup", "facade"])
def test_public_probe_paths_accept_native_numeric_factors(monkeypatch, profile, factor, entrypoint):
    scope = AutoInstrument.from_config(f"keysight/{profile}", simulate=True)
    commands: list[str] = []
    monkeypatch.setattr(scope, "_send_command", commands.append)

    if entrypoint == "setter":
        scope.set_probe_attenuation(1, factor)
    elif entrypoint == "setup":
        scope.setup_channel(1, probe_attenuation=factor)
    else:
        scope.channel(1).setup(probe_attenuation=factor)

    assert len(commands) == 1
    assert float(commands[0].rsplit(" ", 1)[-1].split(",")[-1]) == factor


@pytest.mark.parametrize(
    ("profile", "factor"),
    [("DSOX1204G", 0.09), ("DSOX1204G", 10_001), ("MXR404A", 0.00009), ("MXR404A", 1001)],
)
def test_outside_native_probe_factor_is_rejected_before_write(monkeypatch, profile, factor):
    scope = AutoInstrument.from_config(f"keysight/{profile}", simulate=True)
    commands: list[str] = []
    monkeypatch.setattr(scope, "_send_command", commands.append)

    with pytest.raises(InstrumentParameterError):
        scope.set_probe_attenuation(1, factor)

    assert commands == []


def test_mxr_timebase_discovery_and_runtime_use_seconds_per_division(monkeypatch):
    scope = AutoInstrument.from_config("keysight/MXR404A", simulate=True)
    commands: list[str] = []
    monkeypatch.setattr(scope, "_send_command", commands.append)
    monkeypatch.setattr(scope, "_wait", lambda: None)
    monkeypatch.setattr(scope, "_query_profile_alias", lambda _alias, **_kwargs: "0")

    constraints = scope.describe_operation("time_axis")["parameters"]["scale"]["constraints"]
    assert constraints["min"] == 5e-12
    assert constraints["max"] == 20
    scope.set_time_axis(20, 0)
    commands.clear()
    with pytest.raises(InstrumentParameterError):
        scope.set_time_axis(20.1, 0)
    assert commands == []


@pytest.mark.parametrize("profile", ["DSOX1204G", "MXR404A"])
def test_nonfinite_position_fails_before_timebase_scale_write(monkeypatch, profile):
    scope = AutoInstrument.from_config(f"keysight/{profile}", simulate=True)
    commands: list[str] = []
    monkeypatch.setattr(scope, "_send_command", commands.append)
    monkeypatch.setattr(scope, "_wait", lambda: None)

    with pytest.raises(InstrumentParameterError):
        scope.set_time_axis(1e-6, float("nan"))

    assert commands == []


@pytest.mark.parametrize(
    ("profile", "probe", "impedance", "scale", "offset"),
    [
        ("DSOX1204G", "1", None, 0.2, 2.01),
        ("DSOX1204G", "10", None, 2.0, 20.1),
        ("MXR404A", "1,RAT", "DC50", 0.055, 0.81),
        ("MXR404A", "1,RAT", "DC", 0.005, 5.01),
        ("MXR404A", "1,RAT", "DC50", 0.121, 3.2),
        ("MXR404A", "1,RAT", "DC50", 0.261, 4.0),
    ],
)
def test_full_axis_request_is_validated_before_scale_or_offset_write(
    monkeypatch, profile, probe, impedance, scale, offset
):
    scope = AutoInstrument.from_config(f"keysight/{profile}", simulate=True)
    commands: list[str] = []
    monkeypatch.setattr(
        scope,
        "_query_profile_alias",
        lambda alias, **_kwargs: {
            "probe_get": probe,
            "channel_input": impedance,
            "get_channel_offset": "0",
        }[alias],
    )
    monkeypatch.setattr(scope, "_send_command", commands.append)
    monkeypatch.setattr(scope, "_wait", lambda: None)

    with pytest.raises(InstrumentParameterError):
        scope.set_channel_axis(1, scale, offset)

    assert commands == []


@pytest.mark.parametrize(
    ("profile", "probe", "impedance", "scale", "offset"),
    [
        ("DSOX1204G", "1", None, 0.2, 2),
        ("DSOX1204G", "1", None, 0.201, 100),
        ("DSOX1204G", "10", None, 2.0, 20),
        ("DSOX1204G", "10", None, 2.01, 1000),
        ("MXR404A", "1,RAT", "DC50", 0.055, 0.8),
        ("MXR404A", "1,RAT", "DC50", 0.0551, 1.6),
        ("MXR404A", "1,RAT", "DC50", 0.12, 1.6),
        ("MXR404A", "1,RAT", "DC50", 0.122, 3.2),
        ("MXR404A", "1,RAT", "DC50", 0.26, 3.2),
        ("MXR404A", "1,RAT", "DC50", 0.262, 4),
        ("MXR404A", "1,RAT", "DC", 0.0099, 5),
        ("MXR404A", "1,RAT", "DC", 0.01, 20),
        ("MXR404A", "1,RAT", "DC", 0.2, 20),
        ("MXR404A", "1,RAT", "DC", 0.201, 40),
        ("MXR404A", "3.2,RAT", "DC50", 0.176, 2.56),
    ],
)
def test_offset_band_boundaries_use_requested_scale_and_probe_context(
    monkeypatch, profile, probe, impedance, scale, offset
):
    scope = AutoInstrument.from_config(f"keysight/{profile}", simulate=True)
    commands: list[str] = []
    monkeypatch.setattr(
        scope,
        "_query_profile_alias",
        lambda alias, **_kwargs: {
            "probe_get": probe,
            "channel_input": impedance,
            "get_channel_offset": "0",
            "get_channel_scale": str(scale),
        }[alias],
    )
    monkeypatch.setattr(scope, "_send_command", commands.append)
    monkeypatch.setattr(scope, "_wait", lambda: None)

    scope.set_channel_axis(1, scale, -offset)

    assert len(commands) == 2
    assert float(commands[0].rsplit(" ", 1)[-1]) == scale
    assert float(commands[1].rsplit(" ", 1)[-1]) == -offset


def test_narrowing_scale_clears_incompatible_old_offset_before_scale_write(monkeypatch):
    scope = AutoInstrument.from_config("keysight/DSOX1204G", simulate=True)
    state = {"scale": 1.0, "offset": 100.0}
    commands: list[str] = []
    monkeypatch.setattr(
        scope,
        "_query_profile_alias",
        lambda alias, **_kwargs: {
            "probe_get": "1",
            "get_channel_offset": str(state["offset"]),
            "get_channel_scale": str(state["scale"]),
        }[alias],
    )
    monkeypatch.setattr(scope, "_wait", lambda: None)

    def apply(command):
        value = float(command.rsplit(" ", 1)[-1])
        if ":SCALe " in command:
            if value <= 0.2 and abs(state["offset"]) > 2:
                raise AssertionError(
                    "new scale invalidates the old offset before final offset runs"
                )
            state["scale"] = value
        else:
            state["offset"] = value
        commands.append(command)

    monkeypatch.setattr(scope, "_send_command", apply)

    scope.set_channel_axis(1, 0.1, 1.0)

    assert commands == [":CHANnel1:OFFSet 0.0", ":CHANnel1:SCALe 0.1", ":CHANnel1:OFFSet 1.0"]
    assert state == {"scale": 0.1, "offset": 1.0}


def test_scale_change_neutralizes_offset_that_native_rescales_in_divisions(monkeypatch):
    scope = AutoInstrument.from_config("keysight/DSOX1204G", simulate=True)
    state = {"scale": 0.0005, "offset": 2.0}
    commands: list[str] = []
    monkeypatch.setattr(
        scope,
        "_query_profile_alias",
        lambda alias, **_kwargs: {
            "probe_get": "1",
            "get_channel_offset": str(state["offset"]),
            "get_channel_scale": str(state["scale"]),
        }[alias],
    )
    monkeypatch.setattr(scope, "_wait", lambda: None)

    def apply(command):
        value = float(command.rsplit(" ", 1)[-1])
        if ":SCALe " in command:
            projected_offset = state["offset"] * value / state["scale"]
            if abs(projected_offset) > 2:
                raise AssertionError("scale changes the offset in divisions beyond its range")
            state.update(scale=value, offset=projected_offset)
        else:
            state["offset"] = value
        commands.append(command)

    monkeypatch.setattr(scope, "_send_command", apply)

    scope.set_channel_axis(1, 0.2, -2.0)

    assert commands == [":CHANnel1:OFFSet 0.0", ":CHANnel1:SCALe 0.2", ":CHANnel1:OFFSet -2.0"]


@pytest.mark.parametrize(
    ("profile", "requested", "effective", "offset", "accepted"),
    [
        ("DSOX1204G", 0.2001, 0.2, 100.0, False),
        ("MXR404A", 0.12125, 0.121, 3.2, False),
        ("MXR404A", 0.26125, 0.261, 4.0, False),
        ("MXR404A", 0.1215, 0.122, 3.2, True),
        ("MXR404A", 0.2615, 0.262, 4.0, True),
    ],
)
def test_quantized_scale_is_read_before_nonzero_offset_is_written(
    monkeypatch, profile, requested, effective, offset, accepted
):
    scope = AutoInstrument.from_config(f"keysight/{profile}", simulate=True)
    state = {"scale": 1.0, "offset": 0.0}
    commands: list[str] = []
    monkeypatch.setattr(
        scope,
        "_query_profile_alias",
        lambda alias, **_kwargs: {
            "probe_get": "1",
            "get_channel_offset": str(state["offset"]),
            "get_channel_scale": str(state["scale"]),
            "channel_input": "DC50",
        }[alias],
    )
    monkeypatch.setattr(scope, "_wait", lambda: None)

    def apply(command):
        commands.append(command)
        if ":SCALe " in command:
            state["scale"] = effective

    monkeypatch.setattr(scope, "_send_command", apply)

    if accepted:
        scope.set_channel_axis(1, requested, offset)
        assert commands == [f":CHANnel1:SCALe {requested}", f":CHANnel1:OFFSet {offset}"]
    else:
        with pytest.raises(InstrumentParameterError, match="effective scale"):
            scope.set_channel_axis(1, requested, offset)
        assert commands == [f":CHANnel1:SCALe {requested}"]

    assert state["scale"] == effective


def test_dsox_raw_transfer_requires_actual_main_timebase(monkeypatch):
    scope = AutoInstrument.from_config("keysight/DSOX1204G", simulate=True)
    commands: list[str] = []
    monkeypatch.setattr(scope, "_send_command", commands.append)
    monkeypatch.setattr(scope, "_wait", lambda: None)
    monkeypatch.setattr(scope, "_query", lambda command: "NORM" if "TYPE?" in command else "WIND")

    selected = scope._configure_waveform_transfer("CHANnel1", "byte")

    assert selected == "set_wave_points_mode_normal"
    assert ":WAVeform:POINts:MODE RAW" not in commands
    assert ":WAVeform:POINts:MODE NORMal" in commands


@pytest.mark.parametrize("run_after", [True, False])
def test_dsox_peak_pairs_share_their_acquisition_time(monkeypatch, run_after):
    scope = AutoInstrument.from_config("keysight/DSOX1204G", simulate=True)
    monkeypatch.setattr(scope, "_send_command", lambda _command: None)
    monkeypatch.setattr(scope, "_query", lambda _command: "PEAK")
    monkeypatch.setattr(scope, "get_sampling_rate", lambda: 1e9)
    monkeypatch.setattr(scope, "_read_current_waveform_source", lambda: 1)
    monkeypatch.setattr(scope, "_read_current_waveform_format", lambda: "byte")
    monkeypatch.setattr(scope, "_uncertainty_source_key", lambda: "peak-test")
    monkeypatch.setattr(
        scope, "_configure_waveform_transfer", lambda *_args: "set_wave_points_mode_normal"
    )
    monkeypatch.setattr(
        scope,
        "_read_preamble",
        lambda: Preamble(
            format="0",
            type="1",
            points=4,
            xinc=1e-9,
            xorg=3e-9,
            xref=0,
            yinc=0.1,
            yorg=0,
            yref=0,
        ),
    )
    monkeypatch.setattr(
        scope, "_read_wave_data", lambda *_args, **_kwargs: np.array([-1, 1, -2, 2])
    )

    result = scope.read_channels(1, run_after=run_after).to_dataframe()

    assert result["Channel 1 (V)"].to_list() == pytest.approx([-0.1, 0.1, -0.2, 0.2])
    assert result["Time (s)"].to_list() == pytest.approx([3e-9, 3e-9, 5e-9, 5e-9], abs=1e-20)


@pytest.mark.parametrize("selection", ["DISP", "ALL"])
def test_mxr_autoscale_empty_display_selection_is_checked_without_enabling(monkeypatch, selection):
    scope = AutoInstrument.from_config("keysight/MXR404A", simulate=True)
    commands: list[str] = []
    monkeypatch.setattr(scope, "_send_command", commands.append)
    monkeypatch.setattr(
        scope,
        "_query_profile_alias",
        lambda alias, **_kwargs: selection if alias == "autoscale_channels_query" else "0",
    )

    if selection == "DISP":
        with pytest.raises(InstrumentParameterError, match="display"):
            scope.auto_scale()
        assert commands == []
    else:
        scope.auto_scale()
        assert commands == [":AUToscale"]
