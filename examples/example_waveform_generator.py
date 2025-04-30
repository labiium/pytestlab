# examples/example_waveform_generator.py
"""
Example script demonstrating basic control of a Waveform Generator using pytestlab.
"""

from pytestlab.instruments import InstrumentManager
import time

# Initialize the Instrument Manager
im = InstrumentManager()

# Find the Waveform Generator instrument
# Replace 'MyAWG' with the alias you defined in your configuration
awg_alias = 'MyAWG' # CHANGE THIS TO YOUR WAVEFORM GENERATOR ALIAS
awg = im.get_instrument(awg_alias)

if awg:
    print(f"Successfully connected to Waveform Generator: {awg.idn}")

    # --- Basic Waveform Configuration ---
    channel = 1

    # Configure a Sine wave on Channel 1
    print(f"\nConfiguring Channel {channel} for a Sine wave...")
    awg.set_function(channel, 'SIN')
    awg.set_frequency(channel, 1000.0) # Frequency: 1 kHz
    awg.set_amplitude(channel, 2.0)   # Amplitude: 2 Vpp (Voltage Peak-to-Peak)
    awg.set_offset(channel, 0.5)      # Offset: 0.5 V

    # Enable the output of Channel 1
    print(f"Enabling Channel {channel} output...")
    awg.enable_output(channel, True)

    print("Output enabled for 5 seconds...")
    time.sleep(5)

    # Configure a Square wave on Channel 1
    print(f"\nConfiguring Channel {channel} for a Square wave...")
    awg.set_function(channel, 'SQU')
    awg.set_frequency(channel, 500.0)  # Frequency: 500 Hz
    awg.set_amplitude(channel, 1.0)    # Amplitude: 1 Vpp
    awg.set_offset(channel, 0.0)       # Offset: 0 V
    awg.set_duty_cycle(channel, 25.0)  # Duty Cycle: 25%

    print("Output updated. Running for another 5 seconds...")
    time.sleep(5)

    # Disable the output of Channel 1
    print(f"\nDisabling Channel {channel} output...")
    awg.enable_output(channel, False)

    print("\nWaveform Generator example finished.")

else:
    print(f"Error: Could not find Waveform Generator with alias '{awg_alias}'.")
    print("Please check your configuration file and ensure the instrument is connected.")

# Close connections
im.close_all()
print("Instrument connections closed.")
