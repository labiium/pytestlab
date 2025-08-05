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

import pytest
import time
from pytestlab.instruments import AutoInstrument

# ------------------- CONFIGURE THESE FOR YOUR LAB -------------------
PSU_CONFIG_KEY = "keysight/EDU36311A"
# --------------------------------------------------------------------

def check_hardware_available():
    """Check if power supply hardware is available for testing."""
    try:
        psu = AutoInstrument.from_config(PSU_CONFIG_KEY)
        # Try to get IDN to verify connection
        idn = psu.id()
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
    assert "EDU36311A" in idn  # Adjust as needed for your instrument

    # --- Get Initial Configuration ---
    initial_config = psu.get_configuration()
    assert isinstance(initial_config, dict)
    assert all(hasattr(cfg, "voltage") and hasattr(cfg, "current") and hasattr(cfg, "state") for cfg in initial_config.values())

    # --- Set Voltage for Each Channel ---
    psu.set_voltage(1, 1.5)
    psu.set_voltage(2, 2.5)
    psu.set_voltage(3, 3.3)
    time.sleep(0.5)

    # --- Set Current for Each Channel ---
    psu.set_current(1, 0.1)
    psu.set_current(2, 0.2)
    psu.set_current(3, 0.3)
    time.sleep(0.5)

    # --- Enable Output for Each Channel ---
    psu.output(1, True)
    time.sleep(0.5)
    psu.output(2, True)
    time.sleep(0.5)
    psu.output(3, True)
    time.sleep(0.5)

    # --- Get Current Configuration ---
    updated_config = psu.get_configuration()
    for channel, config in updated_config.items():
        assert config.state == "ON"

    # --- Enable Output for Multiple Channels at Once ---
    psu.output([1, 2, 3], False)
    time.sleep(0.5)
    config_after_off = psu.get_configuration()
    for channel, config in config_after_off.items():
        assert config.state == "OFF"

    # --- Display Control ---
    psu.display(False)
    time.sleep(2)
    psu.display(True)
    time.sleep(0.5)

    # --- Final Configuration ---
    final_config = psu.get_configuration()
    assert isinstance(final_config, dict)
    assert all(hasattr(cfg, "voltage") and hasattr(cfg, "current") and hasattr(cfg, "state") for cfg in final_config.values())

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
    assert "EDU36311A" in idn

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
    with pytest.raises(Exception):
        psu.set_voltage(99, 1.0)

    # Test invalid voltage (negative)
    with pytest.raises(Exception):
        psu.set_voltage(1, -10.0)
