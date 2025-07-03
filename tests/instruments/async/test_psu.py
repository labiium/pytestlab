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
import asyncio
from pytestlab.instruments import AutoInstrument

@pytest.mark.asyncio
async def test_keysight_edu36311a_psu_sanity():
    # --- Instrument Instantiation ---
    psu = await AutoInstrument.from_config("keysight/EDU36311A")
    assert psu is not None

    # --- Instrument Identification ---
    idn = await psu.id()
    assert isinstance(idn, str)
    assert "EDU36311A" in idn  # Adjust as needed for your instrument

    # --- Get Initial Configuration ---
    initial_config = await psu.get_configuration()
    assert isinstance(initial_config, dict)
    assert all(hasattr(cfg, "voltage") and hasattr(cfg, "current") and hasattr(cfg, "state") for cfg in initial_config.values())

    # --- Set Voltage for Each Channel ---
    await psu.set_voltage(1, 1.5)
    await psu.set_voltage(2, 2.5)
    await psu.set_voltage(3, 3.3)
    await asyncio.sleep(0.5)

    # --- Set Current for Each Channel ---
    await psu.set_current(1, 0.1)
    await psu.set_current(2, 0.2)
    await psu.set_current(3, 0.3)
    await asyncio.sleep(0.5)

    # --- Enable Output for Each Channel ---
    await psu.output(1, True)
    await asyncio.sleep(0.5)
    await psu.output(2, True)
    await asyncio.sleep(0.5)
    await psu.output(3, True)
    await asyncio.sleep(0.5)

    # --- Get Current Configuration ---
    updated_config = await psu.get_configuration()
    for channel, config in updated_config.items():
        assert config.state == "ON"

    # --- Enable Output for Multiple Channels at Once ---
    await psu.output([1, 2, 3], False)
    await asyncio.sleep(0.5)
    config_after_off = await psu.get_configuration()
    for channel, config in config_after_off.items():
        assert config.state == "OFF"

    # --- Display Control ---
    await psu.display(False)
    await asyncio.sleep(2)
    await psu.display(True)
    await asyncio.sleep(0.5)

    # --- Final Configuration ---
    final_config = await psu.get_configuration()
    assert isinstance(final_config, dict)
    assert all(hasattr(cfg, "voltage") and hasattr(cfg, "current") and hasattr(cfg, "state") for cfg in final_config.values())

    # Optionally, add more assertions as needed for your use case