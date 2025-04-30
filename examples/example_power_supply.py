# examples/example_power_supply.py
"""
Example script demonstrating basic control of a Power Supply using pytestlab.
"""

from pytestlab.instruments import InstrumentManager

# Initialize the Instrument Manager
# This will automatically discover connected instruments based on your configuration
# Ensure your configuration file (e.g., lm.yaml) is set up correctly
im = InstrumentManager()

# Find the Power Supply instrument
# Replace 'MyPSU' with the alias you defined in your configuration
psu_alias = 'MyPSU' # CHANGE THIS TO YOUR POWER SUPPLY ALIAS
psu = im.get_instrument(psu_alias)

if psu:
    print(f"Successfully connected to Power Supply: {psu.idn}")

    # --- Basic Operations ---

    # Set voltage on channel 1 to 5.0 Volts
    channel = 1
    voltage_setpoint = 5.0
    print(f"\nSetting Channel {channel} voltage to {voltage_setpoint} V...")
    psu.set_voltage(channel, voltage_setpoint)

    # Set current limit on channel 1 to 0.5 Amps
    current_limit = 0.5
    print(f"Setting Channel {channel} current limit to {current_limit} A...")
    psu.set_current_limit(channel, current_limit)

    # Enable the output of channel 1
    print(f"Enabling Channel {channel} output...")
    psu.enable_output(channel, True)

    # Read back the measured voltage and current
    measured_voltage = psu.measure_voltage(channel)
    measured_current = psu.measure_current(channel)
    print(f"Measured Voltage (Channel {channel}): {measured_voltage:.4f} V")
    print(f"Measured Current (Channel {channel}): {measured_current:.4f} A")

    # Disable the output of channel 1
    print(f"\nDisabling Channel {channel} output...")
    psu.enable_output(channel, False)

    print("\nPower Supply example finished.")

else:
    print(f"Error: Could not find Power Supply with alias '{psu_alias}'.")
    print("Please check your configuration file and ensure the instrument is connected.")

# Close connections
im.close_all()
print("Instrument connections closed.")
