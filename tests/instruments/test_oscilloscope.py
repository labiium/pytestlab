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
  - Test acquisition settings (type, mode, average count, segmented memory).
  - Comprehensive acquisition type tests with data capture under each acquisition mode.
  - (Optionally) run a frequency response analysis sweep.

Before running, ensure that your OscilloscopeConfig settings match your Keysight EDU... instrument.
"""

import time
import numpy as np
import matplotlib.pyplot as plt
from io import BytesIO
from PIL import Image
import os

# Import instrument class; adjust the module path as needed.
from pytestlab.instruments import AutoInstrument

def test_acquisition_types_with_data_capture(scope, test_channel=1):
    """
    Test all acquisition types and capture data under each type.
    
    Args:
        scope: The oscilloscope instrument
        test_channel: The channel to use for testing (default=1)
    
    Returns:
        dict: Dictionary with acquisition types as keys and captured data as values
    """
    print("\n[*] Running comprehensive acquisition type tests with data capture...")
    
    # Ensure the channel is enabled and has a reasonable scale
    scope.set_channel_axis(test_channel, scale=0.5, offset=0.0)
    
    # Storage for results
    results = {}
    
    # Test all acquisition types
    acquisition_types = ["NORMAL", "HIGH_RES", "PEAK", "AVERAGE"]
    
    for acq_type in acquisition_types:
        try:
            print(f"\n  Testing acquisition type: {acq_type}")
            
            # Set acquisition type
            scope.set_acquisition_type(acq_type)
            time.sleep(0.5)  # Give time for the setting to take effect
            
            # If AVERAGE type, set a specific count
            if acq_type == "AVERAGE":
                try:
                    # Set the number of averages
                    scope.set_acquisition_average_count(8)
                    print(f"  Set average count to 8")
                    # Need to wait a bit longer for settings to take effect
                    time.sleep(1.0)
                except Exception as e:
                    print(f"  Error setting average parameters: {e}")
            
            # Verify the acquisition type was set correctly
            current_type = scope.get_acquisition_type()
            print(f"  Verified acquisition type is now: {current_type}")
            
            # Capture data with this acquisition type
            print(f"  Capturing data with {acq_type} acquisition...")
            scope.auto_scale()  # Ensure signal is visible
            time.sleep(1.0)     # Give time for auto-scale to settle
            
            # Capture data
            data = scope.read_channels(test_channel)
            
            # Store results
            results[acq_type] = data
            
            print(f"  Successfully captured data with {acq_type} acquisition type")
            
            # Get some statistics about the captured data
            if hasattr(data, 'values') and hasattr(data.values, 'shape'):
                print(f"  Data shape: {data.values.shape}")
                if hasattr(data.values, 'columns'):
                    print(f"  Data columns: {data.values.columns}")
            
        except Exception as e:
            print(f"  Error testing {acq_type} acquisition type: {e}")
    
    # Return to NORMAL acquisition type
    try:
        scope.set_acquisition_type("NORMAL")
        print("\n  Returned to NORMAL acquisition type")
    except Exception as e:
        print(f"  Error returning to NORMAL acquisition type: {e}")
        
    return results

def test_acquisition_modes_with_data_capture(scope, test_channel=1):
    """
    Test all acquisition modes and capture data under each mode.
    
    Args:
        scope: The oscilloscope instrument
        test_channel: The channel to use for testing (default=1)
    
    Returns:
        dict: Dictionary with acquisition modes as keys and captured data as values
    """
    print("\n[*] Running comprehensive acquisition mode tests with data capture...")
    
    # Storage for results
    results = {}
    
    # Test acquisition modes
    acquisition_modes = ["REAL_TIME", "SEGMENTED"]
    
    for acq_mode in acquisition_modes:
        try:
            print(f"\n  Testing acquisition mode: {acq_mode}")
            
            # Set acquisition mode
            scope.set_acquisition_mode(acq_mode)
            time.sleep(0.5)  # Give time for the setting to take effect
            
            # Verify the acquisition mode was set correctly
            current_mode = scope.get_acquisition_mode()
            print(f"  Verified acquisition mode is now: {current_mode}")
            
            # For SEGMENTED mode, set up some segments
            if acq_mode == "SEGMENTED":
                try:
                    # Set to a reasonable number of segments
                    scope.set_segmented_count(5)
                    count = scope.get_segmented_count()
                    print(f"  Set segmented count to {count}")
                    
                    # Capture data for each segment
                    segment_data = {}
                    for i in range(1, min(3, count+1)):  # Test first few segments only
                        try:
                            scope.set_segment_index(i)
                            time.sleep(0.3)
                            print(f"  Capturing data from segment {i}...")
                            segment_data[i] = scope.read_channels(test_channel)
                        except Exception as e:
                            print(f"  Error capturing data from segment {i}: {e}")
                    
                    results[acq_mode] = segment_data
                except Exception as e:
                    print(f"  Error configuring segmented mode: {e}")
            else:
                # Capture data with this acquisition mode
                print(f"  Capturing data with {acq_mode} acquisition...")
                scope.auto_scale()  # Ensure signal is visible
                time.sleep(1.0)     # Give time for auto-scale to settle
                
                # Capture data
                data = scope.read_channels(test_channel)
                
                # Store results
                results[acq_mode] = data
                
                print(f"  Successfully captured data with {acq_mode} acquisition mode")
                
        except Exception as e:
            print(f"  Error testing {acq_mode} acquisition mode: {e}")
    
    # Return to REAL_TIME acquisition mode
    try:
        scope.set_acquisition_mode("REAL_TIME")
        print("\n  Returned to REAL_TIME acquisition mode")
    except Exception as e:
        print(f"  Error returning to REAL_TIME acquisition mode: {e}")
        
    return results

def export_data_to_csv(data_dict, base_filename):
    """
    Export captured data to CSV files for later analysis.
    
    Args:
        data_dict: Dictionary containing captured data
        base_filename: Base name for the CSV files
    """
    print(f"\n[*] Exporting data to CSV files with base name: {base_filename}")
    
    try:
        os.makedirs("acquisition_test_results", exist_ok=True)
        
        for key, data in data_dict.items():
            if data is not None:
                try:
                    filename = f"acquisition_test_results/{base_filename}_{key.lower()}.csv"
                    
                    if isinstance(data, dict):
                        # Handle segmented data
                        for seg_idx, seg_data in data.items():
                            if hasattr(seg_data, 'values') and hasattr(seg_data.values, 'write_csv'):
                                seg_filename = f"acquisition_test_results/{base_filename}_{key.lower()}_segment_{seg_idx}.csv"
                                seg_data.values.write_csv(seg_filename)
                                print(f"  Exported {key} segment {seg_idx} data to {seg_filename}")
                    else:
                        # Handle regular data
                        if hasattr(data, 'values') and hasattr(data.values, 'write_csv'):
                            data.values.write_csv(filename)
                            print(f"  Exported {key} data to {filename}")
                        else:
                            print(f"  Cannot export {key} data: data.values is not CSV-exportable")
                except Exception as e:
                    print(f"  Error exporting {key} data: {e}")
    except Exception as e:
        print(f"  Error creating export directory: {e}")

def main():
    # --- Instrument Instantiation ---
    print("Instantiating Oscilloscope from configuration...")
    scope = AutoInstrument.from_config("keysight/DSOX1204G", debug_mode=True)
    
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
    
    # --- Run Comprehensive Acquisition Type Tests ---
    print("\n[5] Running comprehensive acquisition type tests...")
    acq_type_data = test_acquisition_types_with_data_capture(scope, channel)
    
    # Optional: Export the data to CSV files for further analysis
    try:
        export_data_to_csv(acq_type_data, "acq_type_test")
    except Exception as e:
        print(f"Could not export acquisition type test data: {e}")
    
    # --- Run Comprehensive Acquisition Mode Tests ---
    print("\n[6] Running comprehensive acquisition mode tests...")
    try:
        acq_mode_data = test_acquisition_modes_with_data_capture(scope, channel)
        
        # Optional: Export the data to CSV files for further analysis
        try:
            export_data_to_csv(acq_mode_data, "acq_mode_test")
        except Exception as e:
            print(f"Could not export acquisition mode test data: {e}")
    except Exception as e:
        print(f"Error during acquisition mode tests: {e}")
    
    # --- Read Channel Data and Plot ---
    print("\n[7] Reading channel 1 data...")
    # Read channel data. The read_channels method returns a ChannelReadingResult.
    channel_data = scope.read_channels(channel)
    print("Channel data acquired. Plotting voltage over time...")
    # Plot the entire multi-channel reading.
    channel_data.plot()
    
    # --- Measure RMS Voltage ---
    print("\n[8] Measuring RMS voltage on channel 1...")
    rms_result = scope.measure_rms_voltage(channel)
    print(f"Measured RMS Voltage on channel {channel}: {rms_result.values} {rms_result.units}")
    
    # --- Configure and Read FFT Data ---
    print("\n[9] Configuring FFT and reading FFT data from channel 1...")
    # Configure FFT on channel 1 with default settings.
    scope.configure_fft(source_channel=channel, window_type="HANNing", units="DECibel", display=True)
    time.sleep(0.5)  # Wait for FFT processing
    fft_result = scope.read_fft_data()
    print("FFT data acquired. Plotting FFT result...")
    fft_result.plot()
    
    # --- Capture a Screenshot ---
    print("\n[10] Capturing oscilloscope screenshot...")
    try:
        screenshot_img = scope.screenshot()
        # Display the image using PIL's show (or you could save it to a file)
        screenshot_img.show(title="Oscilloscope Screenshot")
        print("Screenshot captured and displayed.")
    except Exception as e:
        print("Failed to capture screenshot:", e)
    
    # --- Test Acquisition Settings ---
    print("\n[11] Testing acquisition settings...")
    
    # Get current acquisition setup
    acq_setup = scope.get_acquire_setup()
    print(f"Current acquisition setup: {acq_setup}")
    
    # Test acquisition type
    print("\n[11.1] Setting and getting acquisition type...")
    current_acq_type = scope.get_acquisition_type()
    print(f"Current acquisition type: {current_acq_type}")
    
    # Try each acquisition type (except AVERAGE which will be tested separately)
    for acq_type in ["NORMAL", "HIGH_RES", "PEAK"]:
        print(f"Setting acquisition type to {acq_type}...")
        scope.set_acquisition_type(acq_type)
        time.sleep(0.3)
        current_type = scope.get_acquisition_type()
        print(f"Acquisition type now: {current_type}")
        assert current_type == acq_type, f"Expected {acq_type}, got {current_type}"
    
    # Test AVERAGE type with average count
    print("\n[11.2] Testing AVERAGE acquisition type with average count...")
    try:
        # Set to AVERAGE mode with count of 8
        scope.set_acquisition_type("AVERAGE")
        time.sleep(0.3)
        
        # Verify type was set correctly
        current_type = scope.get_acquisition_type()
        assert current_type == "AVERAGE", f"Expected AVERAGE, got {current_type}"
        print(f"Acquisition type set to AVERAGE successfully")
        
        # Set average count to 16
        scope.set_acquisition_average_count(16)
        time.sleep(0.3)
        
        # Verify count was set correctly
        count = scope.get_acquisition_average_count()
        assert count == 16, f"Expected count 16, got {count}"
        print(f"Average count set to {count} successfully")
    except Exception as e:
        print(f"Error testing AVERAGE mode: {e}")
    
    # Test acquisition mode
    print("\n[11.3] Testing acquisition mode (REAL_TIME and SEGMENTED)...")
    try:
        # Test REAL_TIME mode
        scope.set_acquisition_mode("REAL_TIME")
        time.sleep(0.3)
        mode = scope.get_acquisition_mode()
        assert mode == "REAL_TIME", f"Expected REAL_TIME, got {mode}"
        print(f"Set acquisition mode to {mode} successfully")
        
        # Test SEGMENTED mode if supported
        try:
            scope.set_acquisition_mode("SEGMENTED")
            time.sleep(0.3)
            mode = scope.get_acquisition_mode()
            assert mode == "SEGMENTED", f"Expected SEGMENTED, got {mode}"
            print(f"Set acquisition mode to {mode} successfully")
            
            # Test segmented memory features
            print("\n[11.4] Testing segmented memory features...")
            
            # Set segment count to 10
            scope.set_segmented_count(10)
            time.sleep(0.3)
            count = scope.get_segmented_count()
            assert count == 10, f"Expected segment count 10, got {count}"
            print(f"Segmented count set to {count} successfully")
            
            # Set segment index to 2
            scope.set_segment_index(2)
            time.sleep(0.3)
            index = scope.get_segment_index()
            assert index == 2, f"Expected segment index 2, got {index}"
            print(f"Segment index set to {index} successfully")
            
            # Return to REAL_TIME mode for other tests
            scope.set_acquisition_mode("REAL_TIME")
            time.sleep(0.3)
            
        except Exception as e:
            print(f"Segmented mode test error (possibly not supported): {e}")
    except Exception as e:
        print(f"Acquisition mode test error: {e}")
    
    # Test acquisition points and sample rate queries
    print("\n[11.5] Testing acquisition points and sample rate queries...")
    points = scope.get_acquire_points()
    sample_rate = scope.get_acquisition_sample_rate()
    print(f"Current acquisition points: {points}")
    print(f"Current sample rate: {sample_rate} Hz")
    
    # Return to normal acquisition mode
    print("\n[11.6] Returning to normal acquisition settings...")
    scope.set_acquisition_type("NORMAL")
    scope.set_acquisition_mode("REAL_TIME")
    time.sleep(0.3)
    
    # --- Frequency Response Analysis Sweep (Optional) ---
    print("\n[12] Performing frequency response analysis sweep...")
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
