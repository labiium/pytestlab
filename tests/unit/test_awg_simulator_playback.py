"""Offline playback state regressions; hardware access is explicitly blocked."""

from unittest.mock import patch

import numpy as np
import pytest

from pytestlab import Bench
from pytestlab.errors import InstrumentCommunicationError


@pytest.fixture
def awg():
    with patch("pyvisa.ResourceManager", side_effect=AssertionError("hardware forbidden")):
        with Bench.open(
            {
                "bench_name": "Offline AWG",
                "simulate": True,
                "instruments": {"awg": {"profile": "keysight/EDU33212A"}},
            }
        ) as bench:
            yield bench.awg


@pytest.mark.parametrize("channel", [1, 2])
def test_polarity_readback_and_channel_isolation(awg, channel):
    awg.set_output_polarity(channel, "inverted")
    assert awg.get_output_polarity(channel) == "inverted"
    assert awg.get_output_polarity(3 - channel) == "normal"
    awg.set_output_polarity(channel, "normal")
    assert awg.get_output_polarity(channel) == "normal"


@pytest.mark.parametrize("channel", [1, 2])
def test_named_waveform_playback_stays_off_and_retains_samples(awg, channel):
    ch = awg.channel(channel)
    ch.disable()
    ch.set_load_impedance("INFinity")
    ch.setup_sine(1000, 0.2)
    assert not awg.get_output_state(channel)
    samples = np.sin(2 * np.pi * np.arange(256) / 256)
    awg.download_arbitrary_waveform_data(
        channel, "first", samples, data_type="normalized", use_binary=False
    )
    awg.download_arbitrary_waveform_data(
        channel, "second", samples[:128], data_type="normalized", use_binary=False
    )
    ch.setup_arbitrary("first", sample_rate=256000, amplitude=0.2)
    assert awg.get_selected_arbitrary_waveform_name(channel) == "first"
    assert awg.get_arbitrary_waveform_points(channel) == 256
    assert awg.get_arbitrary_waveform_sample_rate(channel) == 256000
    assert not awg.get_output_state(channel)
    awg.select_arbitrary_waveform(channel, "second")
    assert awg.get_arbitrary_waveform_points(channel) == 128
    with pytest.raises(InstrumentCommunicationError, match="File name not found"):
        awg.select_arbitrary_waveform(channel, "missing")
    assert awg.get_selected_arbitrary_waveform_name(channel) == "second"
    assert not awg.get_output_state(channel)
    assert not awg.get_output_state(3 - channel)
