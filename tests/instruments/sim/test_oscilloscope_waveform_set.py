from __future__ import annotations

from pytestlab.instruments import WaveformSetResult


def test_sim_scope_acquire_waveforms_returns_shared_set(sim_scope) -> None:
    waveform_set = sim_scope.acquire_waveforms([1, 2])

    assert isinstance(waveform_set, WaveformSetResult)
    assert set(waveform_set.channels) == {1, 2}
    assert waveform_set.channel(1).point_count == waveform_set.channel(2).point_count
    assert waveform_set.channel(1).rms().unit == "V"
