from __future__ import annotations

import logging

import polars as pl
import pytest

from pytestlab.instruments.Oscilloscope import ChannelReadingResult
from pytestlab.instruments.Oscilloscope import Oscilloscope
from pytestlab.instruments.waveform_result import WaveformResult
from pytestlab.uncertainty.specs import AccuracySpec
from pytestlab.uncertainty.waveform import WaveformUncertaintyModel


def test_channel_reading_result_waveform_result_reductions(tmp_path) -> None:
    result = ChannelReadingResult(
        values=pl.DataFrame(
            {
                "Time (s)": [0.0, 1e-6, 2e-6, 3e-6],
                "Channel 1 (V)": [1.0, -1.0, 1.0, -1.0],
            }
        ),
        instrument="FixtureScope",
        units="V",
        measurement_type="ChannelVoltageTime",
        envelope={
            "waveform_uncertainty": {
                "1": {
                    "unit": "V",
                    "resolution": 0.002,
                    "source_key": "fixture:scope:ch1",
                    "accuracy_spec": AccuracySpec(offset=0.01, distribution="standard"),
                }
            }
        },
    )

    wave = result.waveform(1)

    assert isinstance(wave, WaveformResult)
    assert wave.rms().nominal == pytest.approx(1.0)
    assert wave.mean().budget().entries
    path = wave.to_evidence_bundle(tmp_path)
    assert path.is_file()
    assert "not a signed DCC" in path.read_text(encoding="utf-8")


def test_channel_aliases_make_error_propagation_automatic() -> None:
    result = ChannelReadingResult(
        values=pl.DataFrame(
            {
                "Time (s)": [0.0, 1e-6, 2e-6, 3e-6],
                "Channel 1 (V)": [0.25, 0.50, 0.75, 1.00],
            }
        ),
        instrument="FixtureScope",
        units="V",
        measurement_type="ChannelVoltageTime",
        envelope={
            "waveform_uncertainty": {
                "1": {
                    "unit": "V",
                    "resolution": 0.002,
                    "source_key": "fixture:scope:ch1",
                    "accuracy_spec": AccuracySpec(offset=0.01, distribution="standard"),
                }
            }
        },
    )

    rms = result.channel(1).rms()
    mean = result.ch(1).mean()

    assert rms.u > 0.0
    assert mean.u > 0.0
    assert rms.budget().entries
    assert mean.budget().entries


def test_explicit_zero_model_overrides_metadata_for_uncertainty_disabled() -> None:
    zero_model = WaveformUncertaintyModel(
        unit="V",
        channel=1,
        provenance_complete=False,
        assumptions=("uncertainty model disabled by caller",),
    )
    wave = WaveformResult(
        [1.0, 2.0, 3.0],
        unit="V",
        channel=1,
        model=zero_model,
        metadata={
            "waveform_uncertainty": {
                "unit": "V",
                "resolution": 0.002,
                "accuracy_spec": AccuracySpec(offset=0.01, distribution="standard"),
            }
        },
    )

    quantity = wave.quantity_array()

    assert quantity.u.tolist() == [0.0, 0.0, 0.0]
    assert wave.model.assumptions == ("uncertainty model disabled by caller",)


def test_acquire_waveform_uncertainty_false_does_not_rebuild_from_metadata() -> None:
    class FakeScope:
        _logger = logging.getLogger("pytestlab.tests.fake_scope")

        def read_channels(self, channel: int, timeout_ms: int | None = None):
            return ChannelReadingResult(
                values=pl.DataFrame({"Time (s)": [0.0, 1.0], "Channel 1 (V)": [1.0, 2.0]}),
                instrument="FixtureScope",
                units="V",
                measurement_type="ChannelVoltageTime",
                envelope={
                    "waveform_uncertainty": {
                        "1": {
                            "unit": "V",
                            "resolution": 0.1,
                            "accuracy_spec": AccuracySpec(offset=1.0, distribution="standard"),
                        }
                    }
                },
            )

    wave = Oscilloscope.acquire_waveform(FakeScope(), 1, mode="read_only", uncertainty=False)

    assert wave.quantity_array().u.tolist() == [0.0, 0.0]
    assert wave.metadata == {}
    assert "uncertainty model not requested" in wave.acquisition.notes
