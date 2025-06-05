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

@pytest.mark.requires_real_hw
@pytest.mark.asyncio
async def test_oscilloscope_full_real():
    """
    Full functional test for a real oscilloscope using PyTestLab async API.
    """
    # Instantiate the oscilloscope (real hardware)
    osc = await AutoInstrument.from_config(
        OSC_CONFIG_KEY
    )
    await osc.connect_backend()

    # --- IDN ---
    idn = await osc.id()
    print(f"IDN: {idn}")
    assert isinstance(idn, str)
    assert "Keysight".upper() in idn

    # --- Channel configuration ---
    # Test all available channels
    n_channels = len(osc.config.channels)
    for ch in range(1, n_channels + 1):
        # Set scale and offset
        await osc.set_channel_axis(ch, scale=1.0, offset=0.0)
        scale, offset = await osc.get_channel_axis(ch)
        assert np.isclose(scale, 1.0, atol=1e-6)
        assert np.isclose(offset, 0.0, atol=1e-6)

        # Set and get probe attenuation
        probe_atten = osc.config.channels[ch-1].probe_attenuation[0]
        await osc.set_probe_attenuation(ch, probe_atten)
        probe_att_str = await osc.get_probe_attenuation(ch)
        assert probe_att_str.startswith(str(probe_atten))

        # Display channel ON/OFF
        await osc.display_channel(ch, state=True)
        await osc.display_channel(ch, state=False)
        await osc.display_channel(ch, state=True)

    # --- Timebase and sample rate ---
    await osc.set_time_axis(scale=1e-3, position=0.0)
    tb = await osc.get_time_axis()
    assert np.isclose(tb[0], 1e-3, atol=1e-6)
    assert np.isclose(tb[1], 0.0, atol=1e-6)
    sample_rate = await osc.get_sampling_rate()
    assert sample_rate > 0

    # --- Trigger configuration ---
    await osc.trigger.setup_edge(source="CH1", level=0.5, slope=TriggerSlope.POSITIVE)
    # Try negative slope as well
    await osc.trigger.setup_edge(source="CH1", level=0.5, slope=TriggerSlope.NEGATIVE)

    # --- Acquisition type and mode ---
    await osc.acquisition.set_acquisition_type(AcquisitionType.NORMAL)
    acq_type = await osc.acquisition.get_acquisition_type()
    assert acq_type in ("NORMAL", "NORM", AcquisitionType.NORMAL.name)
    await osc.acquisition.set_acquisition_mode("REAL_TIME")
    acq_mode = await osc.acquisition.get_acquisition_mode()
    assert acq_mode in ("REAL_TIME", "RTIMe")

    # --- Single channel acquisition ---
    ch1_result = await osc.read_channels(1)
    assert isinstance(ch1_result.values, pl.DataFrame)
    assert "Time (s)" in ch1_result.values.columns
    assert any("Channel 1" in col for col in ch1_result.values.columns)
    assert ch1_result.values.height > 0

    # --- Multi-channel acquisition ---
    if n_channels >= 2:
        multi_result = await osc.read_channels([1, 2])
        assert isinstance(multi_result.values, pl.DataFrame)
        assert "Time (s)" in multi_result.values.columns
        assert any("Channel 2" in col for col in multi_result.values.columns)
        assert multi_result.values.height > 0

    # --- Vpp and RMS measurement ---
    vpp = await osc.measure_voltage_peak_to_peak(1)
    print(f"Vpp: {vpp.values} V")
    assert isinstance(vpp.values, (float, np.floating))
    rms = await osc.measure_rms_voltage(1)
    print(f"RMS: {rms.values} V")
    assert isinstance(rms.values, (float, np.floating))

    # --- FFT ---
    if osc.config.fft:
        await osc.configure_fft(source_channel=1, window_type=osc.config.fft.window_types[0], units=osc.config.fft.units[0])
        fft_result = await osc.read_fft_data(1)
        assert isinstance(fft_result.values, pl.DataFrame)
        assert "Frequency (Hz)" in fft_result.values.columns
        assert "Magnitude (Linear)" in fft_result.values.columns
        print("FFT acquired.")

    # --- Screenshot ---
    img = await osc.screenshot()
    assert isinstance(img, Image.Image)
    img.save("/tmp/pytestlab_oscilloscope_screenshot.png")
    print("Screenshot saved.")

    # --- Error handling ---
    # Should be no error after normal operation
    errors = await osc.get_all_errors()
    assert all(code == 0 for code, _ in errors)

    # --- Health check ---
    health = await osc.health_check()
    print(f"Health: {health.status}")
    assert health.status in ("OK", "WARNING", "ERROR", "UNKNOWN")

    # --- Close ---
    await osc.close()
    print("Oscilloscope closed.")

@pytest.mark.requires_real_hw
@pytest.mark.asyncio
async def test_oscilloscope_facades_real():
    """
    Test the async channel, trigger, and acquisition facades on a real oscilloscope.
    """
    osc = await AutoInstrument.from_config(
        OSC_CONFIG_KEY
    )
    # await osc.connect_backend()

    # Channel facade
    ch1 = osc.channel(1)
    await ch1.setup(scale=0.5, position=0.0, coupling='DC')
    await ch1.enable()
    await ch1.disable()
    await ch1.enable()

    # Trigger facade
    await osc.trigger.setup_edge(source="CH1", level=1.0, slope=TriggerSlope.POSITIVE)

    # Acquisition facade
    await osc.acquisition.set_acquisition_type(AcquisitionType.NORMAL)
    await osc.acquisition.set_acquisition_mode("REAL_TIME")
    acq_type = await osc.acquisition.get_acquisition_type()
    acq_mode = await osc.acquisition.get_acquisition_mode()
    assert acq_type in ("NORMAL", "NORM", AcquisitionType.NORMAL.name)
    assert acq_mode in ("REAL_TIME", "RTIMe")

    # Acquire waveform
    result = await osc.read_channels(1)
    assert isinstance(result.values, pl.DataFrame)
    assert result.values.height > 0

    await osc.close()

@pytest.mark.requires_real_hw
@pytest.mark.asyncio
async def test_oscilloscope_error_cases_real():
    """
    Test error handling for invalid parameters on a real oscilloscope.
    """
    osc = await AutoInstrument.from_config(
        OSC_CONFIG_KEY
    )
    # await osc.connect_backend()

    # Invalid channel number
    with pytest.raises(Exception):
        await osc.read_channels(99)

    # Invalid probe attenuation
    with pytest.raises(Exception):
        await osc.set_probe_attenuation(1, 999)

    # Invalid timebase (negative)
    with pytest.raises(Exception):
        await osc.set_time_axis(-1.0, 0.0)

    await osc.close()
