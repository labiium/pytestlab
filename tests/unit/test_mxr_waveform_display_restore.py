from __future__ import annotations

import numpy as np
import pytest

from pytestlab import AutoInstrument
from pytestlab.instruments.Oscilloscope import Preamble


def _prepare_scope(monkeypatch, *, read_error: Exception | None = None):
    scope = AutoInstrument.from_config("keysight/MXR404A", simulate=True)
    queried: list[tuple[str, dict[str, object]]] = []
    writes: list[tuple[str, dict[str, object]]] = []
    events: list[str] = []
    display_state = {1: "1", 2: "0", 3: "1", 4: "0"}

    def query_alias(alias: str, **params):
        events.append("visibility_query")
        queried.append((alias, params))
        if alias == "display_channel_query":
            return display_state[params["channel"]]
        raise AssertionError(f"unexpected alias query: {alias}")

    monkeypatch.setattr(scope, "_query_profile_alias", query_alias)

    def send_alias(alias: str, **params):
        events.append("visibility_restore")
        writes.append((alias, params))

    monkeypatch.setattr(scope, "_send_profile_alias", send_alias)
    monkeypatch.setattr(scope, "_send_command", lambda _command, **_kwargs: None)
    monkeypatch.setattr(scope, "_uncertainty_source_key", lambda: "test-mxr-display")
    monkeypatch.setattr(scope, "get_sampling_rate", lambda: 1.0e9)
    monkeypatch.setattr(scope, "_configure_waveform_transfer", lambda *_args: None)
    monkeypatch.setattr(
        scope,
        "_read_preamble",
        lambda: Preamble(
            format="1",
            type="1",
            points=2,
            xinc=1e-9,
            xorg=0.0,
            xref=0.0,
            yinc=0.01,
            yorg=0.0,
            yref=0.0,
        ),
    )

    def read_data(*_args, **_kwargs):
        events.append("data_read")
        if read_error is not None:
            raise read_error
        return np.array([-1, 1], dtype=np.int16)

    monkeypatch.setattr(scope, "_read_wave_data", read_data)
    return scope, queried, writes, events


def test_mxr_read_channels_restores_requested_channel_visibility(monkeypatch):
    scope, queried, writes, events = _prepare_scope(monkeypatch)

    scope.read_channels(1, 2)

    assert queried == [
        ("display_channel_query", {"channel": 1}),
        ("display_channel_query", {"channel": 2}),
    ]
    assert writes == [
        ("display_channel", {"channel": 1, "state": True}),
        ("display_channel", {"channel": 2, "state": False}),
    ]
    assert events.index("data_read") < events.index("visibility_restore")


def test_mxr_read_channels_restores_visibility_after_data_error(monkeypatch):
    scope, _queried, writes, _events = _prepare_scope(
        monkeypatch, read_error=RuntimeError("read failed")
    )

    with pytest.raises(RuntimeError, match="read failed"):
        scope.read_channels(1)

    assert writes == [("display_channel", {"channel": 1, "state": True})]


def test_mxr_read_channels_read_only_does_not_query_or_restore_visibility(monkeypatch):
    scope, queried, writes, _events = _prepare_scope(monkeypatch)
    monkeypatch.setattr(scope, "_read_current_waveform_source", lambda: 1)
    monkeypatch.setattr(scope, "_read_current_waveform_format", lambda: "byte")

    scope.read_channels(1, run_after=False)

    assert queried == []
    assert writes == []


def test_mxr_read_channels_does_not_mask_primary_error_if_restore_fails(monkeypatch):
    scope, _queried, _writes, _events = _prepare_scope(
        monkeypatch, read_error=RuntimeError("read failed")
    )

    def fail_restore(*_args, **_kwargs):
        raise OSError("restore failed")

    monkeypatch.setattr(scope, "_send_profile_alias", fail_restore)

    with pytest.raises(RuntimeError, match="read failed"):
        scope.read_channels(1)


def test_profiles_without_display_capability_keep_read_channels_behavior(monkeypatch):
    scope = AutoInstrument.from_config("keysight/DSOX1204G", simulate=False)
    calls: list[str] = []
    monkeypatch.setattr(
        scope, "_query_profile_alias", lambda *args, **kwargs: calls.append("query")
    )
    monkeypatch.setattr(scope, "_send_profile_alias", lambda *args, **kwargs: calls.append("write"))

    with scope._preserve_channel_display([1]):
        pass

    assert calls == []
