# examples/example_multimeter.py
"""
Example script demonstrating basic control of a Multimeter using pytestlab.
"""

from pytestlab.instruments import InstrumentManager
import time

# Initialize the Instrument Manager
im = InstrumentManager()

# Find the Multimeter instrument
# Replace 'MyDMM' with the alias you defined in your configuration
dmm_alias = 'MyDMM' # CHANGE THIS TO YOUR MULTIMETER ALIAS
dmm = im.get_instrument(dmm_alias)

if dmm:
    print(f"Successfully connected to Multimeter: {dmm.idn}")

    # --- Basic Measurements ---

    # Measure DC Voltage
    print("\nMeasuring DC Voltage...")
    dc_voltage = dmm.measure_voltage_dc()
    print(f"Measured DC Voltage: {dc_voltage:.6f} V")
    time.sleep(1) # Pause briefly between measurements

    # Measure AC Voltage
    print("\nMeasuring AC Voltage...")
    ac_voltage = dmm.measure_voltage_ac()
    print(f"Measured AC Voltage: {ac_voltage:.6f} V")
    time.sleep(1)

    # Measure DC Current (Ensure setup is correct for current measurement!)
    # print("\nMeasuring DC Current...")
    # dc_current = dmm.measure_current_dc()
    # print(f"Measured DC Current: {dc_current:.6f} A")
    # time.sleep(1)

    # Measure Resistance (2-wire)
    print("\nMeasuring Resistance (2-wire)...")
    resistance = dmm.measure_resistance()
    print(f"Measured Resistance: {resistance:.6f} Ohms")
    time.sleep(1)

    # Measure Frequency
    print("\nMeasuring Frequency...")
    frequency = dmm.measure_frequency()
    print(f"Measured Frequency: {frequency:.3f} Hz")

    print("\nMultimeter example finished.")

else:
    print(f"Error: Could not find Multimeter with alias '{dmm_alias}'.")
    print("Please check your configuration file and ensure the instrument is connected.")

# Close connections
im.close_all()
print("Instrument connections closed.")
