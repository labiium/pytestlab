"""
Real Instrument Sanity Test for Keysight EDU34450A Multimeter

This script exercises key functionality of the Multimeter instrument class:
  - Query the instrument ID.
  - Configure the multimeter for a voltage measurement with DC mode.
  - Retrieve and display the current configuration using both legacy and structured methods.
  - Make a voltage measurement and display the result.
  - Check for any system errors.
  - Run a self-test and print its result.

Before running, ensure that your MultimeterConfig settings match your Keysight EDU34450A instrument.
"""

import time
import numpy as np

# Import instrument class; adjust the module path as needed.
from pytestlab.instruments import AutoInstrument

def main():
    # Create an instrument instance from configuration.
    mm = AutoInstrument.from_config("keysight/EDU34450A")
    
    # --- Instrument Identification ---
    idn = mm.id()  # Assuming the base Instrument class implements an id() method.
    print("Instrument ID:", idn)
    
    # --- Configure Measurement Settings ---
    print("\n[1] Configuring multimeter for Voltage measurement in DC mode...")
    # Here, we assume "10V" is a valid voltage range for the instrument.
    mm.configure(mode="VOLT", ac_dc="DC", rang="10V", res="MED")
    time.sleep(0.2)
    
    # --- Query and Display Current Configuration (Legacy Method) ---
    print("\n[2] Querying legacy configuration...")
    mm.get_configuration()  # This method prints out the configuration details internally.
    
    # --- Retrieve and Display Structured Configuration ---
    print("\n[3] Retrieving structured configuration...")
    config = mm.get_config()
    print("Current Configuration:")
    print(config)
    
    # --- Perform a Measurement ---
    print("\n[4] Making a voltage measurement...")
    # Using the 'measure' method to perform a DC voltage measurement with the same range.
    measurement = mm.measure(measurement_type="VOLTAGE", mode="DC", rang="10V", int_time="MED")
    print(f"Measured Voltage: {measurement.values} {measurement.units}")
    
    # --- Check for System Errors ---
    print("\n[5] Checking for system errors...")
    # Assuming the instrument provides an _error_check method; if not, this can be adapted.
    if hasattr(mm, "_error_check"):
        error = mm._error_check()
    else:
        error = "No error checking implemented."
    print("System Error Query Response:", error)
    
    # --- Run Self-Test ---
    print("\n[6] Running self-test...")
    # Assuming the instrument provides a self_test method; if not, handle appropriately.
    if hasattr(mm, "self_test"):
        result = mm.self_test()
    else:
        result = "Self-test not implemented."
    print("Self-test result:", result)
    
    print("\nMultimeter sanity check completed.")

if __name__ == "__main__":
    main()
