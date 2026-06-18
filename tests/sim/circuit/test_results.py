from __future__ import annotations

import numpy as np
import polars as pl

from pytestlab.sim.circuit.results import BodeResult
from pytestlab.sim.circuit.results import FrequencySpectrum
from pytestlab.sim.circuit.results import SimChannelReadingResult
from pytestlab.sim.circuit.results import SweepResult
from pytestlab.sim.circuit.results import WaveformResult


def test_waveform_result_metrics_and_dataframe() -> None:
    time = np.linspace(0.0, 1.0, 101)
    voltage = np.where(time < 0.2, 0.0, 1.0)
    result = WaveformResult(time, voltage, sample_rate=100.0, instrument="scope1")

    assert result.peak_to_peak() == 1.0
    assert np.isclose(result.rms(), np.sqrt(np.mean(voltage**2)))
    assert result.rise_time() is not None
    assert result[0] == (time[0], voltage[0])
    assert result.to_dataframe().columns == ["Time (s)", "Voltage (V)"]


def test_frequency_spectrum_thd() -> None:
    freq = np.asarray([0.0, 1_000.0, 2_000.0, 3_000.0])
    mag = np.asarray([0.0, 1.0, 0.1, 0.05])
    spectrum = FrequencySpectrum(freq, mag, np.zeros_like(freq), fundamental_hz=1_000.0)

    assert np.isclose(spectrum.thd(n_harmonics=3), np.sqrt(0.1**2 + 0.05**2))
    assert np.isclose(spectrum.harmonic_magnitudes(3), [1.0, 0.1, 0.05]).all()
    assert spectrum.to_dataframe().columns == ["freq_hz", "magnitude", "phase"]


def test_bode_result_bandwidth_and_interpolation() -> None:
    freq = np.asarray([10.0, 100.0, 1_000.0])
    bode = BodeResult(freq, np.asarray([0.0, -1.0, -3.5]), np.asarray([0.0, -30.0, -90.0]))

    assert bode.bandwidth_3db() == 1_000.0
    assert np.isclose(bode.gain_at(55.0), -0.5)
    assert np.isclose(bode.phase_at(550.0), -60.0)


def test_sweep_result_column_access() -> None:
    data = pl.DataFrame({"vbias": [0.0, 1.0], "vout": [0.1, 0.2]})
    result = SweepResult("vbias", np.asarray([0.0, 1.0]), "V", data)

    assert np.isclose(result["vout"], [0.1, 0.2]).all()
    assert result.to_dataframe().shape == (2, 2)


def test_sim_channel_reading_result_compatibility() -> None:
    time = np.asarray([0.0, 1.0])
    wave = WaveformResult(time, np.asarray([1.0, 2.0]), 1.0, "scope1")
    result = SimChannelReadingResult(channels=[1], time=time, readings={1: wave})

    read_time, read_voltage = result[1]
    assert np.array_equal(read_time, time)
    assert np.array_equal(read_voltage, wave.voltage)
    assert result.for_channel(1) is wave
    assert result.to_dataframe().columns == ["Time (s)", "Channel 1 (V)"]
