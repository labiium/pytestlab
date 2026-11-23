"""Regression coverage for waveform point-count requests."""

import numpy as np
import pytest
from pydantic import ValidationError

from pytestlab import AutoInstrument
from pytestlab.errors import InstrumentConfigurationError
from pytestlab.errors import InstrumentDataError
from pytestlab.errors import InstrumentParameterError
from pytestlab.instruments.Oscilloscope import ChannelReadingResult
from pytestlab.instruments.Oscilloscope import Preamble


@pytest.fixture
def scope():
    return AutoInstrument.from_config("keysight/DSOX1204G", simulate=True)


def test_acquire_waveform_forwards_requested_points(scope, monkeypatch):
    import polars as pl

    captured = {}

    def read_channels(*channels, **kwargs):
        captured["channels"] = channels
        captured.update(kwargs)
        return ChannelReadingResult(
            instrument="DSOX1204G",
            units="V",
            measurement_type="ChannelVoltageTime",
            values=pl.DataFrame({"Time (s)": np.array([0.0]), "Channel 1 (V)": np.array([0.0])}),
        )

    monkeypatch.setattr(scope, "read_channels", read_channels)
    monkeypatch.setattr(scope, "get_time_axis", lambda: (1e-3, 0.0))

    scope.acquire_waveform(1, points=2000, uncertainty=False)

    assert captured["channels"] == (1,)
    assert captured["points"] == 2000


@pytest.mark.parametrize("points", [0, -1])
def test_read_channels_rejects_invalid_point_requests_before_io(scope, points, monkeypatch):
    monkeypatch.setattr(
        scope,
        "_send_command",
        lambda command: pytest.fail(f"invalid point request attempted write: {command}"),
    )
    monkeypatch.setattr(
        scope,
        "_query",
        lambda command: pytest.fail(f"invalid point request attempted query: {command}"),
    )

    with pytest.raises(InstrumentParameterError):
        scope.read_channels(1, points=points)


@pytest.mark.parametrize("points", [1.5, True, "2000"])
def test_read_channels_requires_strict_integer_point_requests(scope, points, monkeypatch):
    monkeypatch.setattr(
        scope,
        "_send_command",
        lambda command: pytest.fail(f"invalid point request attempted write: {command}"),
    )
    monkeypatch.setattr(
        scope,
        "_query",
        lambda command: pytest.fail(f"invalid point request attempted query: {command}"),
    )

    with pytest.raises(ValidationError):
        scope.read_channels(1, points=points)


def test_read_only_acquisition_rejects_point_change_before_io(scope, monkeypatch):
    monkeypatch.setattr(
        scope,
        "_send_command",
        lambda command: pytest.fail(f"read-only point request attempted write: {command}"),
    )
    monkeypatch.setattr(
        scope,
        "_query",
        lambda command: pytest.fail(f"read-only point request attempted query: {command}"),
    )

    with pytest.raises(InstrumentParameterError):
        scope.read_channels(1, run_after=False, points=2000)


def _stub_waveform_io(scope, monkeypatch, events, *, count):
    monkeypatch.setattr(scope, "_wait", lambda: None)
    monkeypatch.setattr(scope, "_uncertainty_source_key", lambda: "point-count-test")
    monkeypatch.setattr(scope, "get_sampling_rate", lambda: 1e9)
    monkeypatch.setattr(scope.acquisition, "get_acquisition_type", lambda: "normal")
    monkeypatch.setattr(
        scope,
        "_query_profile_alias",
        lambda alias, **_kwargs: events.append(("query_alias", alias)) or "MAIN",
    )
    monkeypatch.setattr(
        scope,
        "_send_profile_alias",
        lambda alias, **_kwargs: events.append(("profile_alias", alias)),
    )
    monkeypatch.setattr(scope, "_send_command", lambda command: events.append(("command", command)))
    monkeypatch.setattr(
        scope,
        "_read_preamble",
        lambda: Preamble(
            format="0",
            type="0",
            points=count,
            xinc=1e-9,
            xorg=0.0,
            xref=0.0,
            yinc=1.0,
            yorg=0.0,
            yref=0.0,
        ),
    )
    monkeypatch.setattr(scope, "_read_wave_data", lambda *_args, **_kwargs: np.zeros(count))


def test_dsox_numeric_points_are_set_after_mode_without_max_and_count_is_recorded(
    scope, monkeypatch
):
    events = []
    _stub_waveform_io(scope, monkeypatch, events, count=1998)

    result = scope.read_channels(1, points=2000)

    aliases = [value for kind, value in events if kind == "profile_alias"]
    assert aliases.index("set_wave_points_mode_raw") < aliases.index("set_wave_points")
    assert "set_wave_points_max" not in aliases
    transfer = result.envelope["waveform_transfer"]
    assert transfer["requested_points"] == 2000
    assert transfer["effective_points"] == {"1": 1998}
    assert transfer["points_commands"] == ["set_wave_points"]
    assert len(result.values) == 1998


def test_default_point_request_keeps_profile_maximum_behavior(scope, monkeypatch):
    events = []
    _stub_waveform_io(scope, monkeypatch, events, count=3)

    result = scope.read_channels(1)

    aliases = [value for kind, value in events if kind == "profile_alias"]
    assert "set_wave_points_max" in aliases
    assert "set_wave_points" not in aliases
    transfer = result.envelope["waveform_transfer"]
    assert transfer["requested_points"] is None
    assert transfer["effective_points"] == {"1": 3}
    assert transfer["points_commands"] == ["set_wave_points_max"]


def test_mxr_limits_are_queried_before_digitize_for_numeric_point_request(monkeypatch):
    mxr = AutoInstrument.from_config("keysight/MXR404A", simulate=True)
    events = []
    _stub_waveform_io(mxr, monkeypatch, events, count=1000)
    monkeypatch.setattr(
        mxr,
        "_query_profile_alias",
        lambda alias, **_kwargs: (
            events.append(("query_alias", alias))
            or (
                "1,<numeric>16:200000000"
                if alias == "acquisition_points_limits_query"
                else "ON"
                if alias == "display_channel_query"
                else "MAIN"
            )
        ),
    )

    result = mxr.read_channels(1, points=1000)

    limits_index = events.index(("query_alias", "acquisition_points_limits_query"))
    digitize_index = next(
        index
        for index, event in enumerate(events)
        if event[0] == "command" and "digitize" in event[1].lower()
    )
    assert limits_index < digitize_index
    assert ("profile_alias", "set_acquisition_points") in events
    assert result.envelope["waveform_transfer"]["points_commands"] == ["set_acquisition_points"]


@pytest.mark.parametrize(
    ("points", "limits_response", "error"),
    [
        (8, "1,<numeric>16:200000000", InstrumentParameterError),
        (1000, "malformed limits", InstrumentDataError),
    ],
)
def test_mxr_invalid_dynamic_limits_fail_before_acquisition_or_digitize(
    monkeypatch, points, limits_response, error
):
    mxr = AutoInstrument.from_config("keysight/MXR404A", simulate=True)
    events = []
    _stub_waveform_io(mxr, monkeypatch, events, count=1000)
    monkeypatch.setattr(
        mxr,
        "_query_profile_alias",
        lambda alias, **_kwargs: (
            events.append(("query_alias", alias))
            or (
                limits_response
                if alias == "acquisition_points_limits_query"
                else "ON"
                if alias == "display_channel_query"
                else "MAIN"
            )
        ),
    )

    with pytest.raises(error):
        mxr.read_channels(1, points=points)

    assert not any(
        (kind == "profile_alias" and alias == "set_acquisition_points")
        or (kind == "command" and "digitize" in alias.lower())
        for kind, alias in events
    )


def test_numeric_point_request_requires_profile_capability_before_io(monkeypatch):
    limited = AutoInstrument.from_config("keysight/HD304MSO", simulate=True)
    monkeypatch.setattr(
        limited,
        "_send_command",
        lambda command: pytest.fail(f"unsupported point request attempted write: {command}"),
    )
    monkeypatch.setattr(
        limited,
        "_query",
        lambda command: pytest.fail(f"unsupported point request attempted query: {command}"),
    )

    with pytest.raises(InstrumentConfigurationError):
        limited.read_channels(1, points=2000)
