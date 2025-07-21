# examples_ci/simulated_psu_dmm_sweep.py
#! pytest: marker=ci_example
import pytest # If using pytest markers
import asyncio # For async operations
import numpy as np
from pytestlab.instruments import AutoInstrument
# Assuming Pydantic models for config are preferred over dicts now
from pytestlab.config.power_supply_config import PowerSupplyConfig # Adjust as per actual model
from pytestlab.config.multimeter_config import MultimeterConfig # Adjust as per actual model

# Minimal Pydantic configs for simulation
PSU_CFG_DATA = {"device_type": "power_supply", "model": "SimPSUCI", "address": "SIM_PSU", "channels": [{"channel_id": 1}]} # Added minimal channel for PSU

@pytest.mark.ci_example # Mark test for CI
async def test_simulated_psu_dmm_sweep(simulated_psu_profile, simulated_dmm_profile): # Make test async and accept fixtures
    psu_config = PowerSupplyConfig(**PSU_CFG_DATA)
    
    # The DMM now loads its configuration from the temporary profile file
    # created by the fixture.
    psu = await AutoInstrument.from_config(config_source=psu_config, simulate=True)
    dmm = await AutoInstrument.from_config(config_source=simulated_dmm_profile, simulate=True)

    await psu.connect_backend() # Explicitly connect if needed by new async model
    await dmm.connect_backend()

    # Using facade if available and async
    # await psu.channel(1).set(voltage=5.0)
    # await psu.channel(1).on()
    # For direct command if facade isn't used or for specific test:
    await psu.write(":OUTP1:STAT ON")
    await psu.write(":SOUR1:VOLT 5.0")

    # The simulated DMM will now automatically respond with "5.001" to the
    # :MEAS:VOLT:DC? query, as defined in the YAML profile.
    measured_val_str = await dmm.query(":MEAS:VOLT:DC?")
    measured_val = float(measured_val_str)

    assert np.isclose(measured_val, 5.0, atol=0.01), f"Expected ~5.0V, got {measured_val}V"

    await psu.close()
    await dmm.close()
    print("CI Example: PSU-DMM sweep ran successfully.")

    assert np.isclose(measured_val, 5.0, atol=0.01), f"Expected ~5.0V, got {measured_val}V"

    await psu.close()
    await dmm.close()
    print("CI Example: PSU-DMM sweep ran successfully.")

# If running script directly (not via pytest)
# async def main():
#    await test_simulated_psu_dmm_sweep()
# if __name__ == "__main__":
#    asyncio.run(main())