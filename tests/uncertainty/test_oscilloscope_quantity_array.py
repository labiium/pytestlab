from __future__ import annotations

import polars as pl
import pytest

from pytestlab.instruments.Oscilloscope import ChannelReadingResult
from pytestlab.uncertainty import QuantityArray
from pytestlab.uncertainty.specs import AccuracySpec


def test_channel_reading_result_builds_lazy_quantity_array_from_waveform_metadata() -> None:
    result = ChannelReadingResult(
        values=pl.DataFrame(
            {
                "Time (s)": [0.0, 1e-6, 2e-6],
                "Channel 1 (V)": [1.0, 2.0, 3.0],
            }
        ),
        instrument="FixtureScope",
        units="V",
        measurement_type="ChannelVoltageTime",
        sampling_rate=1_000_000.0,
        envelope={
            "waveform_uncertainty": {
                "1": {
                    "unit": "V",
                    "range_value": 5.0,
                    "resolution": 0.001,
                    "bandwidth": 100e6,
                    "source_key": "fixture:scope:ch1:read_channels:5",
                    "accuracy_spec": AccuracySpec(
                        reading_fraction=0.01,
                        offset=0.02,
                        distribution="standard",
                    ),
                }
            }
        },
    )

    arr = result.quantity(1)

    assert isinstance(arr, QuantityArray)
    assert arr.nominal.tolist() == [1.0, 2.0, 3.0]
    assert arr.u[0] == pytest.approx((0.01**2 + 0.02**2) ** 0.5)
    assert arr.u[2] == pytest.approx((0.03**2 + 0.02**2) ** 0.5)
    assert arr.measurement_model.function == "read_channels"
    assert arr.provenance.provenance_complete is False


def test_channel_filter_preserves_waveform_uncertainty_metadata() -> None:
    result = ChannelReadingResult(
        values=pl.DataFrame(
            {
                "Time (s)": [0.0, 1e-6],
                "Channel 1 (V)": [1.0, 2.0],
                "Channel 2 (V)": [3.0, 4.0],
            }
        ),
        instrument="FixtureScope",
        units="V",
        measurement_type="ChannelVoltageTime",
        envelope={"waveform_uncertainty": {"1": {"unit": "V"}, "2": {"unit": "V"}}},
    )

    ch2 = result.for_channel(2)

    assert ch2.channels == [2]
    assert ch2.quantity(2).nominal.tolist() == [3.0, 4.0]
