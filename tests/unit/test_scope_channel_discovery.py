from __future__ import annotations

from itertools import combinations
from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pytest

from pytestlab import AutoInstrument
from pytestlab.instruments.Oscilloscope import Preamble

PROFILE_ROOT = Path(__file__).parents[2] / "pytestlab" / "profiles" / "keysight"
MODEL_CHANNELS = {
    "MXR404A": 4,
    "DSOX1204G": 4,
    "DSOX1202G": 2,
    "DSOX3054G": 4,
    "MSOX2024A": 4,
}


def _all_channel_groups(count: int) -> list[list[int]]:
    return [
        list(group)
        for size in range(1, count + 1)
        for group in combinations(range(1, count + 1), size)
    ]


def _scope(model: str):
    return AutoInstrument.from_config(
        config_source=str(PROFILE_ROOT / f"{model}.yaml"),
        simulate=False,
        backend_override=Mock(),
    )


@pytest.mark.parametrize(("model", "channel_count"), MODEL_CHANNELS.items())
def test_digitize_discovery_lists_each_channel_and_supported_group(model, channel_count):
    scope = _scope(model)
    options = scope.list_operation_options("digitize", "channels")

    values = [option["value"] for option in options]
    assert values == _all_channel_groups(channel_count)


@pytest.mark.parametrize(("model", "channel_count"), MODEL_CHANNELS.items())
def test_discovered_channel_groups_work_through_read_channels_with_mocked_io(
    model, channel_count, monkeypatch
):
    scope = _scope(model)
    options = scope.list_operation_options("digitize", "channels")
    sent = []
    monkeypatch.setattr(scope, "_send_command", sent.append)
    monkeypatch.setattr(scope, "_query_profile_alias", lambda *_args, **_kwargs: "1")
    monkeypatch.setattr(scope, "_send_profile_alias", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(scope, "_uncertainty_source_key", lambda: "channel-discovery-test")
    monkeypatch.setattr(scope, "get_sampling_rate", lambda: 1_000.0)
    monkeypatch.setattr(scope, "_resolve_waveform_format", lambda _format: "byte")
    monkeypatch.setattr(scope, "_configure_waveform_transfer", lambda *_args: None)
    monkeypatch.setattr(
        scope,
        "_read_preamble",
        lambda: Preamble(
            format="BYTE",
            type="NORM",
            points=3,
            xinc=1e-6,
            xorg=0.0,
            xref=0.0,
            yinc=0.01,
            yorg=0.0,
            yref=0.0,
        ),
    )
    monkeypatch.setattr(scope, "_read_wave_data", lambda *_args, **_kwargs: np.array([1, 2, 3]))

    for option in options:
        channels = option["value"]
        result = scope.read_channels(channels)
        assert result.channels == channels
        assert result.values.height == 3
    assert sent
