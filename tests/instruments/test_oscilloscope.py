"""
pytestlab/tests/test_oscilloscope.py

Comprehensive asynchronous test suite for a real oscilloscope using the
PyTestLab async API.

This test covers all major features:
- Connection and identification
- Channel configuration and display
- Timebase and sample rate
- Trigger configuration and acquisition
- Measurement (Vpp, RMS)
- Multi-channel acquisition
- FFT
- Screenshot
- Error handling
- Closing

**NOTE:** This test requires a real oscilloscope connected and accessible via VISA.
Set VISA_ADDRESS and OSC_CONFIG_KEY below.

Run with:
    pytest -v pytestlab/tests/test_oscilloscope.py

Requires:
    pytest
    pytest-asyncio
    numpy
    polars
    Pillow
    pytestlab (with async API)
"""

import pytest
import numpy as np
import polars as pl
from PIL import Image

from pytestlab.instruments import AutoInstrument
from pytestlab.common.enums import TriggerSlope, AcquisitionType

# ------------------- CONFIGURE THESE FOR YOUR LAB -------------------
OSC_CONFIG_KEY = "keysight/DSOX1204G"                 # <-- Set your profile key or path here
# --------------------------------------------------------------------

def check_hardware_available():
    """Check if oscilloscope hardware is available for testing."""
    try:
        osc = AutoInstrument.from_config(OSC_CONFIG_KEY)
        osc.connect_backend()
        # Try to get IDN to verify connection
        idn = osc.id()
        osc.close()
        return True, None
    except Exception as e:
        return False, str(e)

@pytest.mark.requires_real_hw
def test_oscilloscope_full_real():
    """
    Full functional test for a real oscilloscope using PyTestLab async API.
    """
    is_available, error_msg = check_hardware_available()
    if not is_available:
        pytest.skip(f"Oscilloscope hardware not available: {error_msg}")

    # Instantiate the oscilloscope (real hardware)
    osc = AutoInstrument.from_config(
        OSC_CONFIG_KEY
    )
    osc.connect_backend()

    # --- IDN ---
    idn = osc.id()
    print(f"IDN: {idn}")
    assert isinstance(idn, str)
    assert "Keysight".upper() in idn

    # --- Channel configuration ---
    # Test all available channels
    n_channels = len(osc.config.channels)
    for ch in range(1, n_channels + 1):
        # Set scale and offset
        osc.set_channel_axis(ch, scale=1.0, offset=0.0)
        scale, offset = osc.get_channel_axis(ch)
        assert np.isclose(scale, 1.0, atol=1e-6)
        assert np.isclose(offset, 0.0, atol=1e-6)

        # Set and get probe attenuation
        probe_atten = osc.config.channels[ch-1].probe_attenuation[0]
        osc.set_probe_attenuation(ch, probe_atten)
        probe_att_str = osc.get_probe_attenuation(ch)
        assert probe_att_str.startswith(str(probe_atten))

        # Display channel ON/OFF
        osc.display_channel(ch, state=True)
        osc.display_channel(ch, state=False)
        osc.display_channel(ch, state=True)

    # --- Timebase and sample rate ---
    osc.set_time_axis(scale=1e-3, position=0.0)
    tb = osc.get_time_axis()
    assert np.isclose(tb[0], 1e-3, atol=1e-6)
    assert np.isclose(tb[1], 0.0, atol=1e-6)
    sample_rate = osc.get_sampling_rate()
    assert sample_rate > 0

    # --- Trigger configuration ---
    osc.trigger.setup_edge(source="CH1", level=0.5, slope=TriggerSlope.POSITIVE)
    # Try negative slope as well
    osc.trigger.setup_edge(source="CH1", level=0.5, slope=TriggerSlope.NEGATIVE)

    # --- Acquisition type and mode ---
    osc.acquisition.set_acquisition_type(AcquisitionType.NORMAL)
    acq_type = osc.acquisition.get_acquisition_type()
    assert acq_type in ("NORMAL", "NORM", AcquisitionType.NORMAL.name)
    osc.acquisition.set_acquisition_mode("REAL_TIME")
    acq_mode = osc.acquisition.get_acquisition_mode()
    assert acq_mode in ("REAL_TIME", "RTIMe")

    # --- Single channel acquisition ---
    ch1_result = osc.read_channels(1)
    assert isinstance(ch1_result.values, pl.DataFrame)
    assert "Time (s)" in ch1_result.values.columns
    assert any("Channel 1" in col for col in ch1_result.values.columns)
    assert ch1_result.values.height > 0

    # --- Multi-channel acquisition ---
    if n_channels >= 2:
        multi_result = osc.read_channels([1, 2])
        assert isinstance(multi_result.values, pl.DataFrame)
        assert "Time (s)" in multi_result.values.columns
        assert any("Channel 2" in col for col in multi_result.values.columns)
        assert multi_result.values.height > 0

    # --- Vpp and RMS measurement ---
    vpp = osc.measure_voltage_peak_to_peak(1)
    print(f"Vpp: {vpp.values} V")
    assert isinstance(vpp.values, (float, np.floating))
    rms = osc.measure_rms_voltage(1)
    print(f"RMS: {rms.values} V")
    assert isinstance(rms.values, (float, np.floating))

    # --- FFT ---
    if osc.config.fft:
        osc.configure_fft(source_channel=1, window_type=osc.config.fft.window_types[0], units=osc.config.fft.units[0])
        fft_result = osc.read_fft_data(1)
        assert isinstance(fft_result.values, pl.DataFrame)
        assert "Frequency (Hz)" in fft_result.values.columns
        assert "Magnitude (Linear)" in fft_result.values.columns
        print("FFT acquired.")

    # --- Screenshot ---
    img = osc.screenshot()
    assert isinstance(img, Image.Image)
    img.save("/tmp/pytestlab_oscilloscope_screenshot.png")
    print("Screenshot saved.")

    # --- Error handling ---
    # Should be no error after normal operation
    errors = osc.get_all_errors()
    assert all(code == 0 for code, _ in errors)

    # --- Health check ---
    health = osc.health_check()
    print(f"Health: {health.status}")
    assert health.status in ("OK", "WARNING", "ERROR", "UNKNOWN")

    # --- Close ---
    osc.close()
    print("Oscilloscope closed.")

@pytest.mark.requires_real_hw
def test_oscilloscope_facades_real():
    """
    Test the async channel, trigger, and acquisition facades on a real oscilloscope.
    """
    is_available, error_msg = check_hardware_available()
    if not is_available:
        pytest.skip(f"Oscilloscope hardware not available: {error_msg}")

    osc = AutoInstrument.from_config(
        OSC_CONFIG_KEY
    )
    osc.connect_backend()

    # Channel facade
    ch1 = osc.channel(1)
    ch1.setup(scale=0.5, position=0.0, coupling='DC')
    ch1.enable()
    ch1.disable()
    ch1.enable()

    # Trigger facade
    osc.trigger.setup_edge(source="CH1", level=1.0, slope=TriggerSlope.POSITIVE)

    # Acquisition facade
    osc.acquisition.set_acquisition_type(AcquisitionType.NORMAL)
    osc.acquisition.set_acquisition_mode("REAL_TIME")
    acq_type = osc.acquisition.get_acquisition_type()
    acq_mode = osc.acquisition.get_acquisition_mode()
    assert acq_type in ("NORMAL", "NORM", AcquisitionType.NORMAL.name)
    assert acq_mode in ("REAL_TIME", "RTIMe")

    # Acquire waveform
    result = osc.read_channels(1)
    assert isinstance(result.values, pl.DataFrame)
    assert result.values.height > 0

    osc.close()

@pytest.mark.requires_real_hw
def test_oscilloscope_error_cases_real():
    """
    Test error handling for invalid parameters on a real oscilloscope.
    """
    is_available, error_msg = check_hardware_available()
    if not is_available:
        pytest.skip(f"Oscilloscope hardware not available: {error_msg}")

    osc = AutoInstrument.from_config(
        OSC_CONFIG_KEY
    )
    osc.connect_backend()

    # Invalid channel number
    with pytest.raises(Exception):
        osc.read_channels(99)

    # Invalid probe attenuation
    with pytest.raises(Exception):
        osc.set_probe_attenuation(1, 999)

    # Invalid timebase (negative)
    with pytest.raises(Exception):
        osc.set_time_axis(-1.0, 0.0)

    osc.close()
