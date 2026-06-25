from __future__ import annotations

import json

import pytest

from pytestlab.instruments.waveform_result import WaveformResult
from pytestlab.instruments.waveform_set import SharedClockModel
from pytestlab.instruments.waveform_set import WaveformSetResult
from pytestlab.uncertainty import DataOrigin
from pytestlab.uncertainty import EvidencePurpose
from pytestlab.uncertainty import WaveformAxis
from pytestlab.uncertainty import WaveformUncertaintyModel


def _model(channel: int) -> WaveformUncertaintyModel:
    return WaveformUncertaintyModel(
        unit="V",
        channel=channel,
        source_key=f"scope:ch{channel}:vertical",
        axis=WaveformAxis(
            sample_interval_s=1.0,
            trigger_jitter_std_s=0.1,
            timebase_relative_std=1e-3,
            sample_aperture_s=1e-12,
            channel_skew_std_s=0.01,
        ),
        data_origin=DataOrigin.MEASURED,
        evidence_purpose=EvidencePurpose.MEASUREMENT_RESULT,
        provenance_complete=True,
    )


def _wave(channel: int, delay_s: float = 0.0) -> WaveformResult:
    return WaveformResult(
        [0.0, 1.0],
        time=[delay_s, 1.0 + delay_s],
        channel=channel,
        model=_model(channel),
        instrument="sim-scope",
    )


def test_waveform_set_delay_cancels_shared_clock_and_keeps_channel_skew() -> None:
    independent_a = _wave(1)
    independent_b = _wave(2)
    with pytest.warns(RuntimeWarning, match="different uncertainty registries"):
        naive = independent_a.timing.delay(independent_b)

    waveform_set = WaveformSetResult(
        {1: _wave(1), 2: _wave(2)},
        clock_model=SharedClockModel(
            source_key="shared-scope-clock",
            trigger_jitter_std_s=0.1,
            timebase_relative_std=1e-3,
            sample_aperture_s=1e-12,
            channel_skew_std_s=0.01,
        ),
    )
    delay = waveform_set.delay(1, 2)

    assert delay.nominal == pytest.approx(0.0)
    assert delay.u == pytest.approx((2 * 0.01**2) ** 0.5)
    assert delay.u < naive.u
    assert waveform_set.channel(1).rms().nominal == pytest.approx(2**-0.5)


def test_waveform_set_channel_timing_uses_same_shared_covariance_path() -> None:
    waveform_set = WaveformSetResult(
        {1: _wave(1), 2: _wave(2)},
        clock_model=SharedClockModel(
            source_key="shared-scope-clock",
            trigger_jitter_std_s=0.1,
            timebase_relative_std=1e-3,
            sample_aperture_s=1e-12,
            channel_skew_std_s=0.01,
        ),
    )

    via_set = waveform_set.delay(1, 2)
    via_channels = waveform_set.channel(1).timing.delay(waveform_set.channel(2))

    assert via_channels.nominal == pytest.approx(via_set.nominal)
    assert via_channels.u == pytest.approx(via_set.u)
    assert via_channels.budget().to_dicts() == via_set.budget().to_dicts()


def test_waveform_set_channel_delay_rejects_detached_or_other_set_channel() -> None:
    waveform_set = WaveformSetResult(
        {1: _wave(1), 2: _wave(2)},
        clock_model=SharedClockModel(source_key="shared-scope-clock", channel_skew_std_s=0.01),
    )
    other_set = WaveformSetResult(
        {1: _wave(1), 2: _wave(2)},
        clock_model=SharedClockModel(source_key="other-scope-clock", channel_skew_std_s=0.01),
    )

    with pytest.raises(ValueError, match="same WaveformSetResult"):
        waveform_set.channel(1).timing.delay(other_set.channel(2))
    with pytest.raises(ValueError, match="same WaveformSetResult"):
        waveform_set.channel(1).timing.delay(_wave(2))  # type: ignore[arg-type]


def test_waveform_set_channel_reductions_use_set_owned_quantity_array() -> None:
    wave_a = _wave(1)
    wave_b = _wave(2)
    waveform_set = WaveformSetResult(
        {1: wave_a, 2: wave_b},
        clock_model=SharedClockModel(source_key="shared-scope-clock", channel_skew_std_s=0.01),
    )

    area = waveform_set.channel(1).integrate()
    assert area.nominal == pytest.approx(1.0)
    assert wave_a._quantity is None
    assert wave_b._quantity is None


def test_waveform_set_evidence_records_shared_clock_and_channel_hashes(tmp_path) -> None:
    waveform_set = WaveformSetResult(
        {1: _wave(1), 2: _wave(2, delay_s=0.1)},
        clock_model=SharedClockModel(source_key="shared-scope-clock", channel_skew_std_s=0.01),
    )

    path = waveform_set.to_evidence_bundle(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["schema"] == "pytestlab.waveform_set_evidence.v1"
    assert payload["shared_clock_model"]["source_key"] == "shared-scope-clock"
    assert {"1", "2"} <= payload["channels"].keys()
    assert "delay_1_2" in payload["cross_channel"]
    assert payload["payload_sha256"]


def test_waveform_set_does_not_mutate_child_waveform_quantity_cache() -> None:
    wave_a = _wave(1)
    wave_b = _wave(2)

    waveform_set = WaveformSetResult(
        {1: wave_a, 2: wave_b},
        clock_model=SharedClockModel(source_key="shared-scope-clock", channel_skew_std_s=0.01),
    )
    _ = waveform_set.delay(1, 2)

    assert wave_a._quantity is None
    assert wave_b._quantity is None
    assert waveform_set.quantity_array(1).registry is waveform_set.quantity_array(2).registry


def test_waveform_set_evidence_records_all_channel_pairs(tmp_path) -> None:
    waveform_set = WaveformSetResult(
        {1: _wave(1), 2: _wave(2, delay_s=0.1), 3: _wave(3, delay_s=0.2)},
        clock_model=SharedClockModel(source_key="shared-scope-clock", channel_skew_std_s=0.01),
    )

    path = waveform_set.to_evidence_bundle(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert {"delay_1_2", "delay_1_3", "delay_2_3"} <= payload["cross_channel"].keys()
