import numpy as np
import pytest

from pytestlab.analysis.fft import compute_fft


@pytest.mark.parametrize("sample_count", [0, 1])
def test_compute_fft_returns_empty_arrays_for_short_signals(sample_count: int) -> None:
    time = np.arange(sample_count, dtype=float)
    frequency, magnitude = compute_fft(time, np.zeros(sample_count))

    assert frequency.size == 0
    assert magnitude.size == 0


def test_compute_fft_matches_numpy_for_valid_signal() -> None:
    time = np.arange(4, dtype=float) / 4
    voltage = np.array([0.0, 1.0, 0.0, -1.0])

    frequency, magnitude = compute_fft(time, voltage, window=None)

    assert frequency == pytest.approx(np.fft.fftfreq(4, d=0.25)[:2])
    assert magnitude == pytest.approx(np.abs(np.fft.fft(voltage))[:2])


def test_compute_fft_returns_empty_arrays_for_nonpositive_duration() -> None:
    frequency, magnitude = compute_fft(np.array([1.0, 0.0]), np.ones(2))

    assert frequency.size == 0
    assert magnitude.size == 0
