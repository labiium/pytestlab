# examples/example_oscilloscope.py
"""
Example script demonstrating basic control of an Oscilloscope using pytestlab.
"""

from pytestlab.instruments import InstrumentManager
import time
import numpy as np # Assuming numpy is available for potential waveform processing

# Initialize the Instrument Manager
im = InstrumentManager()

# Find the Oscilloscope instrument
# Replace 'MyScope' with the alias you defined in your configuration
scope_alias = 'MyScope' # CHANGE THIS TO YOUR OSCILLOSCOPE ALIAS
scope = im.get_instrument(scope_alias)

if scope:
    print(f"Successfully connected to Oscilloscope: {scope.idn}")

    # --- Basic Setup and Acquisition ---

    # Configure Channel 1
    channel = 1
    print(f"\nConfiguring Channel {channel}...")
    scope.set_channel_scale(channel, 1.0) # Set vertical scale to 1 V/div
    scope.set_channel_offset(channel, 0.0) # Set vertical offset to 0 V
    scope.set_channel_coupling(channel, 'DC') # Set coupling to DC
    scope.enable_channel(channel, True)    # Enable the channel

    # Configure Timebase
    print("Configuring timebase...")
    scope.set_timebase_scale(0.001) # Set horizontal scale to 1 ms/div
    scope.set_timebase_offset(0.0)  # Set horizontal offset to 0 s

    # Configure Trigger
    print("Configuring trigger...")
    scope.set_trigger_source(f'CH{channel}') # Trigger on Channel 1
    scope.set_trigger_level(channel, 0.5) # Set trigger level to 0.5 V
    scope.set_trigger_slope('POS')      # Trigger on positive slope
    scope.set_trigger_mode('AUTO')      # Set trigger mode to Auto

    # Acquire waveform data from Channel 1
    print(f"\nAcquiring waveform from Channel {channel}...")
    scope.run()
    time.sleep(2) # Allow time for acquisition
    scope.stop()

    waveform_data = scope.get_waveform_data(channel)

    if waveform_data:
        # waveform_data is typically a dictionary containing time and voltage arrays
        time_axis = waveform_data.get('time')
        voltage_data = waveform_data.get('voltage')

        if time_axis is not None and voltage_data is not None:
            print(f"Successfully acquired {len(voltage_data)} points.")
            # Optional: Print first few data points
            print("First 5 points (Time, Voltage):")
            for i in range(min(5, len(time_axis))):
                print(f"  ({time_axis[i]:.6f}, {voltage_data[i]:.6f})")
            # Here you could plot the data using matplotlib or process it further
            # import matplotlib.pyplot as plt
            # plt.plot(time_axis, voltage_data)
            # plt.xlabel("Time (s)")
            # plt.ylabel("Voltage (V)")
            # plt.title(f"Oscilloscope Channel {channel} Waveform")
            # plt.grid(True)
            # plt.show()
        else:
            print("Error: Waveform data format unexpected.")
    else:
        print("Error: Failed to acquire waveform data.")

    print("\nOscilloscope example finished.")

else:
    print(f"Error: Could not find Oscilloscope with alias '{scope_alias}'.")
    print("Please check your configuration file and ensure the instrument is connected.")

# Close connections
im.close_all()
print("Instrument connections closed.")
