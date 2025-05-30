from __future__ import annotations
import os
from pytestlab.instruments import AutoInstrument
# from pytestlab.measurements import MeasurementSession # If applicable
# from pytestlab import set_log_level # From Section C

def run_simulated_iv_sweep():
    # set_log_level("DEBUG") # Optional: to see sim backend logs
    print("Running simulated IV sweep...")

    # Ensure PYTESTLAB_SIMULATE is set, or pass simulate=True
    # os.environ["PYTESTLAB_SIMULATE"] = "1" # Option 1: Set env var

    psu = None # Initialize to None for finally block
    dmm = None # Initialize to None for finally block

    try:
        # Example: Using a power supply and a multimeter
        # The config path/dict should point to a valid (even if minimal) YAML or dict
        # For simulation, the actual connection details in YAML don't matter as much,
        # but the 'device_type' and 'model' are important for the loader and SimBackend.
        
        # Create a dummy PSU config dict for simulation
        # Ensure these fields align with your PowerSupplyConfig Pydantic model
        psu_config_dict = {
            "device_type": "power_supply", # Matches registry in loader.py
            "model": "SimulatedPSU", 
            "address": "SIM_PSU_ADDRESS", # Placeholder, not used by SimBackend
            "serial_number": "SIMPSU001", # SimBackend might use model, but good practice
            "vendor": "PyTestLabSim",      # Example additional field
            # Add other fields required by PowerSupplyConfig Pydantic model if any
            # e.g., "voltage_limit": 30.0, "current_limit": 5.0 
        }
        # Create a dummy DMM config dict for simulation
        # Ensure these fields align with your MultimeterConfig Pydantic model
        dmm_config_dict = {
            "device_type": "multimeter", # Matches registry in loader.py
            "model": "SimulatedDMM",
            "address": "SIM_DMM_ADDRESS", # Placeholder
            "serial_number": "SIMDMM001", # Good practice
            "vendor": "PyTestLabSim",     # Example additional field
            # Add other fields required by MultimeterConfig Pydantic model if any
            # e.g., "measurement_mode": "DC Current"
        }

        # Option 2: Pass simulate=True
        psu = AutoInstrument.from_config(psu_config_dict, simulate=True, debug_mode=True)
        dmm = AutoInstrument.from_config(dmm_config_dict, simulate=True, debug_mode=True)

        print(f"PSU IDN: {psu.query('*IDN?')}") # Uses SimBackend
        print(f"DMM IDN: {dmm.query('*IDN?')}") # Uses SimBackend

        # Example IV sweep logic
        voltages_to_set = [0.1, 0.5, 1.0, 1.5, 2.0]
        measured_currents = []

        psu.write(":OUTP:STAT ON") # Simulated command
        print(f"PSU Output Status: {psu.query(':OUTP:STAT?')}")


        for voltage in voltages_to_set:
            psu.write(f":VOLT {voltage}") # Simulated command
            print(f"PSU Voltage Set: {psu.query(':VOLT?')}")
            # In a real scenario, add a small delay or check for command completion
            
            # Simulate reading current from DMM
            # The SimBackend for DMM would need to be smart enough to provide
            # a current based on the PSU's voltage, or just return a fixed/random value.
            # For this example, SimDMM's query(":CURR?") returns a default from its state.
            # To make this more interactive, SimDMM's _simulate could potentially
            # access a shared state or be aware of the PSU's state if they were linked.
            # For now, we'll assume it returns its internally stored current.
            # Let's simulate setting a current on the DMM for it to "measure"
            # This is a bit artificial for a DMM, but demonstrates state in SimBackend
            # A more realistic SimDMM might have its _simulate method for :CURR?
            # return something like voltage / R_load_simulated.
            simulated_reading = voltage / 10.0 # Assume a 10 Ohm load for simulation
            dmm.write(f":CURR {simulated_reading}") # Not a real DMM command, just to set state in SimDMM
            
            current_str = dmm.query(":CURR?") # Simulated query
            measured_currents.append(float(current_str))
            print(f"Set Voltage: {voltage} V, Measured Current: {current_str} A (simulated)")

        psu.write(":OUTP:STAT OFF") # Simulated command
        print(f"PSU Output Status: {psu.query(':OUTP:STAT?')}")
        print("Simulated IV sweep complete.")
        print("Voltages:", voltages_to_set)
        print("Currents:", measured_currents)

    except Exception as e:
        print(f"An error occurred: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Clean up env var if set
        # if "PYTESTLAB_SIMULATE" in os.environ:
        #     del os.environ["PYTESTLAB_SIMULATE"]
        if psu and hasattr(psu, 'close'): 
            psu.close()
            print("Simulated PSU closed.")
        if dmm and hasattr(dmm, 'close'): 
            dmm.close()
            print("Simulated DMM closed.")


if __name__ == "__main__":
    run_simulated_iv_sweep()