"""
Async Real Instrument Sanity Test for Keysight EDU36311A Power Supply

This script exercises key functionalities of the PowerSupply instrument class using the async API:
    - Query the instrument ID.
    - Get the current configuration of all channels.
    - Set voltage for different channels.
    - Set current for different channels.
    - Turn on/off the output for specific channels.
    - Turn on/off the display.
    - Test error handling.

Before running, ensure that your PowerSupplyConfig settings match your Keysight EDU36311A instrument.
"""

import pytest
import time
from pytestlab.instruments import AutoInstrument
def test_keysight_edu36311a_psu_sanity():
    # --- Instrument Instantiation ---
    psu = AutoInstrument.from_config("keysight/EDU36311A")
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
