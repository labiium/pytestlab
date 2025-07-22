import pytest
import asyncio
import numpy as np
import pytest

from pytestlab.instruments import AutoInstrument
from pytestlab.config.waveform_generator_config import WaveformGeneratorConfig

# Use the built-in Keysight EDU33212A AWG profile for testing
AWG_PROFILE_KEY = "keysight/EDU33212A"

@pytest.mark.asyncio
async def test_awg_basic_idn_and_connect():
    """Test that the AWG instrument can be loaded, connected, and returns an actual IDN."""
    awg = await AutoInstrument.from_config(
        config_source=AWG_PROFILE_KEY,
        debug_mode=True
    )
    await awg.connect_backend()
    idn = await awg.id()
    assert "EDU33212A" in idn
    await awg.close()

@pytest.mark.asyncio
async def test_awg_channel_facade_sine_wave():
    """Test the channel() facade for basic sine wave configuration."""
    awg = await AutoInstrument.from_config(
        config_source=AWG_PROFILE_KEY,
        debug_mode=True
    )
    await awg.connect_backend()
    ch = awg.channel(1)
    # Setup a sine wave
    await ch.setup_sine(frequency=1e3, amplitude=2.0, offset=0.5)
    # Enable output
    await ch.enable()
    # Check output state
    state = await awg.get_output_state(1)
    assert state.value == "ON"
    # Disable output
    await ch.disable()
    state = await awg.get_output_state(1)
    assert state.value == "OFF"
    await awg.close()

@pytest.mark.asyncio
async def test_awg_set_and_get_frequency_amplitude_offset():
    """Test set/get for frequency, amplitude, and offset."""
    awg = await AutoInstrument.from_config(
        config_source=AWG_PROFILE_KEY,
        debug_mode=True
    )
    await awg.connect_backend()
    ch = 1
    freq = 12345.0
    amp = 1.23
    offset = 0.12
    await awg.set_frequency(ch, freq)
    await awg.set_amplitude(ch, amp)
    await awg.set_offset(ch, offset)

    f = await awg.get_frequency(ch)
    a = await awg.get_amplitude(ch)
    o = await awg.get_offset(ch)
    assert isinstance(f, float)
    assert isinstance(a, float)
    assert isinstance(o, float)
    await awg.close()

@pytest.mark.asyncio
async def test_awg_set_square_wave_and_duty_cycle():
    """Test setting a square wave and duty cycle."""
    awg = await AutoInstrument.from_config(
        config_source=AWG_PROFILE_KEY,
        debug_mode=True
    )
    await awg.connect_backend()
    ch = 2
    await awg.set_function(ch, "SQUARE", duty_cycle=25.0)
    await awg.set_frequency(ch, 500)
    await awg.set_amplitude(ch, 1.0)
    await awg.set_offset(ch, 0.0)
    duty = await awg.get_square_duty_cycle(ch)
    assert isinstance(duty, float)
    await awg.close()

@pytest.mark.asyncio
async def test_awg_arbitrary_waveform_download_and_select():
    """Test downloading an arbitrary waveform and selecting it."""
    awg = await AutoInstrument.from_config(
        config_source=AWG_PROFILE_KEY,
        debug_mode=True
    )
    await awg.connect_backend()
    ch = 1
    arb_name = "TESTARB"
    # Generate a simple ramp waveform (DAC values)
    dac_data = np.linspace(-32768, 32767, 128, dtype=np.int16)
    await awg.download_arbitrary_waveform_data_csv(ch, arb_name, dac_data, data_type="DAC")
    # Select the arbitrary waveform
    await awg.select_arbitrary_waveform(ch, arb_name)
    selected = await awg.get_selected_arbitrary_waveform_name(ch)
    assert selected == arb_name
    await awg.close()

@pytest.mark.asyncio
async def test_awg_error_handling_on_invalid_channel():
    """Test that setting an invalid channel raises an error."""
    awg = await AutoInstrument.from_config(
        config_source=AWG_PROFILE_KEY,
        debug_mode=True
    )
    await awg.connect_backend()
    # The EDU33212A has 2 channels; channel 3 should be invalid
    with pytest.raises(Exception):
        await awg.set_frequency(3, 1000)
    await awg.close()

@pytest.mark.asyncio
async def test_awg_facade_chain_methods():
    """Test chaining facade methods for a ramp waveform."""
    awg = await AutoInstrument.from_config(
        config_source=AWG_PROFILE_KEY,
        debug_mode=True
    )
    await awg.connect_backend()
    ch2 = awg.channel(2)
    # Test method chaining for a ramp waveform
    await ch2.setup_ramp(frequency=5000, amplitude=2.0, offset=0.0, symmetry=60.0).enable()

    state = await awg.get_output_state(2)
    assert state.value == "ON"
    await ch2.disable()  # Await a new chain
    await awg.close()

@pytest.mark.asyncio
async def test_awg_config_snapshot_and_limits():
    """Test getting a complete config snapshot and voltage limits."""
    awg = await AutoInstrument.from_config(
        config_source=AWG_PROFILE_KEY,
        debug_mode=True
    )
    await awg.connect_backend()
    ch = 1
    config = await awg.get_complete_config(ch)
    assert config.channel == 1

    await awg.set_voltage_limit_high(ch, 5.0)
    await awg.set_voltage_limit_low(ch, -5.0)
    high = await awg.get_voltage_limit_high(ch)
    low = await awg.get_voltage_limit_low(ch)
    assert isinstance(high, float)
    assert isinstance(low, float)
    await awg.close()

@pytest.mark.asyncio
async def test_awg_reset_and_selftest():
    """Test reset and self-test commands."""
    awg = await AutoInstrument.from_config(
        config_source=AWG_PROFILE_KEY,
        debug_mode=True
    )
    await awg.connect_backend()
    await awg.reset()
    result = await awg.run_self_test()
    assert "Passed" in result or "Failed" in result
    await awg.close()
