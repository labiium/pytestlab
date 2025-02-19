"""
Real Instrument Sanity Test for Keysight EDU... Oscilloscope

This script exercises key functionalities of the Oscilloscope instrument class:
  - Query the instrument ID.
  - Auto-scale the display.
  - Set the time axis and channel (vertical) axis.
  - Configure a trigger on channel 1.
  - Read channel 1 data and plot the voltage over time.
  - Measure and display RMS voltage on channel 1.
  - Configure and read FFT data, then plot the FFT magnitude.
  - Capture a screenshot of the oscilloscope display.
  - (Optionally) run a frequency response analysis sweep.

Before running, ensure that your OscilloscopeConfig settings match your Keysight EDU... instrument.
"""

import time
import numpy as np
import matplotlib.pyplot as plt
from io import BytesIO
from PIL import Image

# Import instrument class; adjust the module path as needed.
from pytestlab.instruments import AutoInstrument

def main():
    # --- Instrument Instantiation ---
    print("Instantiating Oscilloscope from configuration...")
    scope = AutoInstrument.from_config("keysight/DSOX1204G")
    
    # --- Instrument Identification ---
    idn = scope.id()  # Assuming the instrument implements an id() method.
    print("Instrument ID:", idn)
    
    # --- Auto-scale Display ---
    print("\n[1] Auto-scaling the oscilloscope display...")
    scope.auto_scale()
    time.sleep(0.3)
    
    # --- Set Time Axis ---
    print("\n[2] Setting time axis (scale and position)...")
    time_scale = 0.001  # 1 ms per division, for example.
    time_position = 0.0  # Centered at trigger.
    scope.set_time_axis(scale=time_scale, position=time_position)
    current_time_axis = scope.get_time_axis()
    print(f"Time Axis - Scale: {current_time_axis[0]} s/div, Position: {current_time_axis[1]} s")
    
    # --- Set Channel Axis for Channel 1 ---
    print("\n[3] Configuring channel 1 axis (vertical scale and offset)...")
    channel = 1
    vertical_scale = 0.5  # 0.5 V/div
    vertical_offset = 0.0  # No offset
    scope.set_channel_axis(channel, scale=vertical_scale, offset=vertical_offset)
    current_channel_axis = scope.get_channel_axis(channel)
    print(f"Channel {channel} Axis - Scale: {current_channel_axis[0]} V/div, Offset: {current_channel_axis[1]} V")
    
    # --- Configure Trigger on Channel 1 ---
    print("\n[4] Configuring trigger for channel 1...")
    trigger_level = 0.2  # Trigger level at 0.2 V
    scope.configure_trigger(channel=channel, level=trigger_level, trigger_type="HIGH", slope="POS", mode="EDGE")
    time.sleep(0.3)
    
    # --- Read Channel Data and Plot ---
    print("\n[5] Reading channel 1 data...")
    # Read channel data. The read_channels method returns a ChannelReadingResult.
    channel_data = scope.read_channels(channel)
    print("Channel data acquired. Plotting voltage over time...")
    # Plot the entire multi-channel reading.
    channel_data.plot()
    
    # --- Measure RMS Voltage ---
    print("\n[6] Measuring RMS voltage on channel 1...")
    rms_result = scope.measure_rms_voltage(channel)
    print(f"Measured RMS Voltage on channel {channel}: {rms_result.values} {rms_result.units}")
    
    # --- Configure and Read FFT Data ---
    print("\n[7] Configuring FFT and reading FFT data from channel 1...")
    # Configure FFT on channel 1 with default settings.
    scope.configure_fft(source_channel=channel, window_type="HANNing", units="DECibel", display=True)
    time.sleep(0.5)  # Wait for FFT processing
    fft_result = scope.read_fft_data()
    print("FFT data acquired. Plotting FFT result...")
    fft_result.plot()
    
    # --- Capture a Screenshot ---
    print("\n[8] Capturing oscilloscope screenshot...")
    try:
        screenshot_img = scope.screenshot()
        # Display the image using PIL's show (or you could save it to a file)
        screenshot_img.show(title="Oscilloscope Screenshot")
        print("Screenshot captured and displayed.")
    except Exception as e:
        print("Failed to capture screenshot:", e)
    
    # --- Frequency Response Analysis Sweep (Optional) ---
    print("\n[9] Performing frequency response analysis sweep...")
    try:
        # Example parameters for FR analysis sweep.
        input_channel = 1
        output_channel = 2
        start_freq = 1000      # 1 kHz
        stop_freq = 100000     # 100 kHz
        amplitude = 1.0        # 1 V amplitude for the function generator part
        points = 20
        fr_result = scope.franalysis_sweep(input_channel, output_channel, start_freq, stop_freq, amplitude, points=points)
        print("Frequency Response Analysis Sweep Result:")
        print(fr_result.values)
        # Optionally, plot the frequency response analysis result if applicable.
        if hasattr(fr_result, "plot"):
            fr_result.plot()
    except Exception as e:
        print("Frequency Response Analysis not supported or failed:", e)
    
    print("\nOscilloscope sanity test completed.")

if __name__ == "__main__":
    main()
