# pytestlab/analysis/fft.py

import numpy as np


def compute_fft(
    time_array: np.ndarray,
    voltage_array: np.ndarray,
    window: str | None = "hann",
) -> tuple[np.ndarray, np.ndarray]:
    """Compute the positive-frequency FFT magnitude of a time-domain signal.

    Args:
        time_array: NumPy array of time values.
        voltage_array: NumPy array of signal values.
        window: ``"hann"``, ``"hamming"``, or ``None``.

    Returns:
        Frequency bins and linear FFT magnitudes. Signals shorter than two
        samples or with nonpositive duration produce two empty arrays.
    """
    if not isinstance(time_array, np.ndarray) or not isinstance(voltage_array, np.ndarray):
        raise TypeError("Input arrays must be NumPy ndarrays.")
    if time_array.size != voltage_array.size:
        raise ValueError("Time and voltage arrays must have the same size.")
    if time_array.ndim != 1 or voltage_array.ndim != 1:
        raise ValueError("Input arrays must be 1-dimensional.")

    sample_count = voltage_array.size
    if sample_count <= 1:
        return np.array([]), np.array([])

    if window:
        if window == "hann":
            voltage_array_windowed = voltage_array * np.hanning(sample_count)
        elif window == "hamming":
            voltage_array_windowed = voltage_array * np.hamming(sample_count)
        else:
            raise ValueError(
                f"Unsupported window function: {window}. Supported: 'hann', 'hamming', None."
            )
    else:
        voltage_array_windowed = voltage_array

    fft_values = np.fft.fft(voltage_array_windowed)
    fft_magnitudes = np.abs(fft_values)[: sample_count // 2]

    duration = time_array[-1] - time_array[0]
    if duration <= 0:
        return np.array([]), np.array([])

    sample_interval = duration / (sample_count - 1)
    frequency_array = np.fft.fftfreq(sample_count, d=sample_interval)[: sample_count // 2]
    return frequency_array, fft_magnitudes
