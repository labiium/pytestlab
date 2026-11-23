"""
pytestlab/tests/instruments/test_psu.py

Comprehensive test suite for a real power supply using the PyTestLab API.

This test covers all major features:
- Connection and identification
- Channel configuration and control
- Voltage and current setting
- Output enable/disable
- Display control
- Error handling

**NOTE:** This test requires a real power supply connected and accessible via VISA.
Tests will be gracefully skipped if hardware is not available.

Run with:
    pytest -v pytestlab/tests/instruments/test_psu.py

Requires:
    pytest
    pytestlab
"""

import os
import time

import pytest

from pytestlab import AutoInstrument

# ------------------- CONFIGURE THESE FOR YOUR LAB -------------------
PSU_CONFIG_KEY = os.getenv("PYTESTLAB_INSTRUMENT_TEST_PROFILE", "keysight/EDU36311A")
# --------------------------------------------------------------------


def _safe_channel_value(range_spec, preferred):
    lower = range_spec.min if range_spec.min is not None else range_spec.min_val
    upper = range_spec.max if range_spec.max is not None else range_spec.max_val
    value = preferred
    if lower is not None:
        value = max(value, lower)
    if upper is not None:
        value = min(value, upper)
    return value


def check_hardware_available():
    """Check if power supply hardware is available for testing."""
    try:
        psu = AutoInstrument.from_config(PSU_CONFIG_KEY)
        # Try to get IDN to verify connection
        _ = psu.id()
        return True, None
    except Exception as e:
        return False, str(e)


@pytest.mark.requires_real_hw
def test_keysight_edu36311a_psu_sanity():
    """Test complete power supply functionality with hardware availability check."""
    is_available, error_msg = check_hardware_available()
    if not is_available:
        pytest.skip(f"Power supply hardware not available: {error_msg}")

    # --- Instrument Instantiation ---
    psu = AutoInstrument.from_config(PSU_CONFIG_KEY)
    assert psu is not None

    # --- Instrument Identification ---
    idn = psu.id()
    assert isinstance(idn, str)
    assert psu.config.model.upper() in idn.upper()

    # --- Get Initial Configuration ---
    initial_config = psu.get_configuration()
    assert isinstance(initial_config, dict)
    assert all(
        hasattr(cfg, "voltage") and hasattr(cfg, "current") and hasattr(cfg, "state")
        for cfg in initial_config.values()
    )

    channels = list(range(1, len(psu.config.channels) + 1))
    for channel, channel_config in zip(channels, psu.config.channels, strict=True):
        psu.set_voltage(channel, _safe_channel_value(channel_config.voltage_range, 1.0 + channel))
        psu.set_current(
            channel, _safe_channel_value(channel_config.current_limit_range, 0.1 * channel)
        )
        psu.output(channel, True)
    time.sleep(0.5)

    # --- Get Current Configuration ---
    updated_config = psu.get_configuration()
    for _channel, config in updated_config.items():
        assert config.state == "ON"

    # --- Enable Output for Multiple Channels at Once ---
    psu.output(channels, False)
    time.sleep(0.5)
    config_after_off = psu.get_configuration()
    for _channel, config in config_after_off.items():
        assert config.state == "OFF"

    # --- Display Control ---
    psu.display(False)
    time.sleep(2)
    psu.display(True)
    time.sleep(0.5)

    # --- Final Configuration ---
    final_config = psu.get_configuration()
    assert isinstance(final_config, dict)
    assert all(
        hasattr(cfg, "voltage") and hasattr(cfg, "current") and hasattr(cfg, "state")
        for cfg in final_config.values()
    )

    # Optionally, add more assertions as needed for your use case


@pytest.mark.requires_real_hw
def test_psu_individual_functions():
    """Test individual PSU functions separately."""
    is_available, error_msg = check_hardware_available()
    if not is_available:
        pytest.skip(f"Power supply hardware not available: {error_msg}")

    psu = AutoInstrument.from_config(PSU_CONFIG_KEY)

    # Test IDN separately
    idn = psu.id()
    assert isinstance(idn, str)
    assert psu.config.model.upper() in idn.upper()

    # Test configuration retrieval
    config = psu.get_configuration()
    assert isinstance(config, dict)
    assert len(config) > 0

    # Test voltage setting for channel 1
    psu.set_voltage(1, 2.0)
    time.sleep(0.1)

    # Test current setting for channel 1
    psu.set_current(1, 0.5)
    time.sleep(0.1)

    # Test output control
    psu.output(1, True)
    time.sleep(0.1)
    psu.output(1, False)


@pytest.mark.requires_real_hw
def test_psu_error_handling():
    """Test PSU error handling with invalid parameters."""
    is_available, error_msg = check_hardware_available()
    if not is_available:
        pytest.skip(f"Power supply hardware not available: {error_msg}")

    psu = AutoInstrument.from_config(PSU_CONFIG_KEY)

    # Test invalid channel number (assuming 3 channels max)
    with pytest.raises(__import__("pytestlab.errors").errors.InstrumentParameterError):
        psu.set_voltage(99, 1.0)

    # Test invalid voltage (negative)
    with pytest.raises(__import__("pytestlab.errors").errors.InstrumentParameterError):
        psu.set_voltage(1, -10.0)
