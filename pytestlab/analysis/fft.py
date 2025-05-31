# pytestlab/analysis/fft.py
import numpy as np
from typing import Tuple, Optional

def compute_fft(
    time_array: np.ndarray, 
    voltage_array: np.ndarray, 
    window: Optional[str] = 'hann' # Example: allow windowing
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Computes the Fast Fourier Transform (FFT) of a given time-domain signal.

    Args:
        time_array: NumPy array of time values.
        voltage_array: NumPy array of voltage (or other signal) values.
        window: Optional windowing function to apply before FFT (e.g., 'hann', 'hamming').
                Set to None or an empty string to disable windowing.

    Returns:
        A tuple containing:
            - frequency_array: NumPy array of frequency bins.
            - magnitude_array: NumPy array of FFT magnitudes (linear).
    """
    # Ensure time_array and voltage_array are of the same size
    if not isinstance(time_array, np.ndarray) or not isinstance(voltage_array, np.ndarray):
        raise TypeError("Input arrays must be NumPy ndarrays.")
    if time_array.size != voltage_array.size:
        raise ValueError("Time and voltage arrays must have the same size.")
    if time_array.ndim != 1 or voltage_array.ndim != 1:
        raise ValueError("Input arrays must be 1-dimensional.")
    
    N = voltage_array.size
    if N == 0:
        return np.array([]), np.array([])
    if N <= 1: # FFT not meaningful for 0 or 1 sample
            return np.array([]), np.array([])

    # Apply windowing if specified
    if window:
        if window == 'hann':
            voltage_array_windowed = voltage_array * np.hanning(N)
        elif window == 'hamming':
            voltage_array_windowed = voltage_array * np.hamming(N)
        # Add other windows or raise error for unsupported window
        # elif window is None or window == '': # No window
        #    voltage_array_windowed = voltage_array
        else:
            raise ValueError(f"Unsupported window function: {window}. Supported: 'hann', 'hamming', None.")
    else: # No window
        voltage_array_windowed = voltage_array


    # Compute FFT
    fft_values = np.fft.fft(voltage_array_windowed)
    # Take only positive frequencies (first N // 2 points)
    # For real inputs, the FFT is symmetric, so we only need half.
    fft_magnitudes = np.abs(fft_values)[:N // 2]

    # Compute frequency bins
    # This requires sampling frequency Fs.
    # A more robust way if time_array is uniformly spaced:
    if N > 1 and (time_array[-1] - time_array[0]) > 0:
            # Total duration T = time_array[-1] - time_array[0]
            # Number of sampling intervals = N - 1
            # Sampling interval dt = T / (N - 1)
            # Sampling frequency Fs = 1 / dt = (N - 1) / T
            dt = (time_array[-1] - time_array[0]) / (N - 1)
            if dt <= 0: # Avoid division by zero or negative dt if time_array is not monotonic
                # This case should ideally be caught by pre-checks or handled by requiring Fs
                return np.array([]), np.array([]) 
            Fs = 1 / dt
    elif N == 1 and time_array.size == 1: # Single point, Fs is undefined, Nyquist is 0
        # Return empty or a specific representation for a single point "spectrum"
        # For FFT, typically need >1 points.
        # Or, if Fs is *known* (e.g. from instrument settings), it could be passed in.
        # For now, aligning with N<=1 check above.
        return np.array([]), np.array([])
    else: # Cannot determine Fs (e.g., N > 1 but time_array[-1] == time_array[0]), or N is too small
            # Or if time_array is not sorted, (time_array[-1] - time_array[0]) could be non-positive.
            # Consider requiring Fs as an input for more robustness if time_array properties are not guaranteed.
            # For now, returning empty as a safe default.
            return np.array([]), np.array([])


    # d = sampling interval = 1/Fs
    frequency_array = np.fft.fftfreq(N, d=1/Fs)[:N // 2]

    # fft_magnitudes are linear. User can convert to dB if needed:
    # fft_magnitudes_db = 20 * np.log10(fft_magnitudes)

    return frequency_array, fft_magnitudes