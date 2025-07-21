#!/usr/bin/env python3
"""
Example measurement script for PyTestLab replay demonstration.
This script performs a comprehensive measurement using PSU and oscilloscope.
"""

import asyncio
import numpy as np
import time


async def main(bench):
    """
    Main measurement function called by PyTestLab replay system.
    
    Args:
        bench: Bench object containing instrument references (psu, osc)
    """
    print("Starting comprehensive measurement script...")
    
    # Get instrument references from bench
    psu = bench.psu if hasattr(bench, 'psu') else bench.instruments['psu']
    osc = bench.osc if hasattr(bench, 'osc') else bench.instruments['osc']
    
    print("Initializing instruments...")
    
    # Get instrument identification
    psu_id = await psu.id()
    osc_id = await osc.id()
    print(f"PSU ID: {psu_id}")
    print(f"OSC ID: {osc_id}")
    
    # Configure oscilloscope for voltage measurements
    print("Configuring oscilloscope...")
    await osc.set_timebase_scale(0.001)  # 1ms/div
    await osc.set_timebase_position(0.0)
    await osc.set_channel_scale(1, 1.0)  # 1V/div on channel 1
    await osc.set_channel_offset(1, 0.0)
    await osc.set_channel_coupling(1, "DC")
    await osc.enable_channel(1, True)
    
    # Set up trigger
    await osc.set_trigger_source("CHAN1")
    await osc.set_trigger_level(1, 2.5)
    await osc.set_trigger_mode("EDGE")
    
    # Configure PSU
    print("Configuring PSU...")
    await psu.set_current(1, 0.1)  # 100mA current limit for safety
    
    # Define measurement parameters
    voltages = [1.0, 2.0, 3.0, 4.0, 5.0, 4.0, 3.0, 2.0, 1.0, 0.0]
    measurements = []
    
    print(f"\nPerforming {len(voltages)}-point voltage sweep measurement...")
    
    try:
        # Enable PSU output
        await psu.output(1, True)
        print("PSU output enabled")
        
        for i, voltage in enumerate(voltages):
            print(f"Step {i+1}/{len(voltages)}: Setting {voltage}V")
            
            # Set PSU voltage
            await psu.set_voltage(1, voltage)
            
            # Wait for voltage settling
            await asyncio.sleep(0.5)
            
            # Trigger oscilloscope single shot
            await osc.single()
            await asyncio.sleep(0.3)  # Wait for trigger and measurement
            
            # Read PSU measurements
            actual_voltage = await psu.measure_voltage(1)
            actual_current = await psu.measure_current(1)
            
            # Read oscilloscope measurements
            try:
                vpp = await osc.measure_vpp(1)
                vmax = await osc.measure_vmax(1)
                vmin = await osc.measure_vmin(1)
                frequency = await osc.measure_frequency(1)
            except Exception as e:
                print(f"  Warning: OSC measurement error: {e}")
                vpp = vmax = vmin = frequency = 0.0
            
            # Store measurement data
            measurement = {
                'step': i + 1,
                'set_voltage': voltage,
                'actual_voltage': actual_voltage,
                'actual_current': actual_current,
                'osc_vpp': vpp,
                'osc_vmax': vmax,
                'osc_vmin': vmin,
                'osc_frequency': frequency,
                'timestamp': time.time()
            }
            measurements.append(measurement)
            
            # Print measurement results
            print(f"  PSU: Set={voltage}V, Actual={actual_voltage:.3f}V, Current={actual_current:.3f}A")
            print(f"  OSC: Vpp={vpp:.3f}V, Vmax={vmax:.3f}V, Vmin={vmin:.3f}V, Freq={frequency:.1f}Hz")
            
            # Small delay between measurements
            await asyncio.sleep(0.2)
        
    finally:
        # Safety: Always disable output and reset voltage
        print("\nShutting down safely...")
        await psu.output(1, False)
        await psu.set_voltage(1, 0.0)
        print("PSU output disabled and voltage reset to 0V")
    
    # Analysis and reporting
    print("\n" + "="*60)
    print("MEASUREMENT SUMMARY")
    print("="*60)
    
    for result in measurements:
        voltage_error = abs(result['actual_voltage'] - result['set_voltage'])
        print(f"Step {result['step']:2d}: "
              f"Set={result['set_voltage']:4.1f}V → "
              f"Actual={result['actual_voltage']:6.3f}V "
              f"(err={voltage_error:5.3f}V), "
              f"I={result['actual_current']:6.3f}A, "
              f"OSC_Vpp={result['osc_vpp']:6.3f}V")
    
    # Calculate statistics
    voltage_errors = [abs(m['actual_voltage'] - m['set_voltage']) for m in measurements]
    avg_error = np.mean(voltage_errors)
    max_error = max(voltage_errors)
    
    print(f"\nVoltage Accuracy Statistics:")
    print(f"  Average error: {avg_error:.3f}V")
    print(f"  Maximum error: {max_error:.3f}V")
    print(f"  RMS error: {np.sqrt(np.mean([e**2 for e in voltage_errors])):.3f}V")
    
    # Power consumption analysis
    powers = [m['actual_voltage'] * m['actual_current'] for m in measurements if m['set_voltage'] > 0]
    if powers:
        print(f"\nPower Consumption:")
        print(f"  Average power: {np.mean(powers):.3f}W")
        print(f"  Peak power: {max(powers):.3f}W")
    
    print("\nMeasurement completed successfully!")
    return measurements


# Additional helper functions for more complex scenarios
async def stress_test_sequence(bench):
    """Extended stress test sequence for thorough validation."""
    psu = bench.psu if hasattr(bench, 'psu') else bench.instruments['psu']
    osc = bench.osc if hasattr(bench, 'osc') else bench.instruments['osc']
    
    print("Running stress test sequence...")
    
    try:
        # Rapid voltage changes
        await psu.output(1, True)
        for i in range(10):
            await psu.set_voltage(1, 3.0)
            await asyncio.sleep(0.1)
            await psu.set_voltage(1, 1.0)
            await asyncio.sleep(0.1)
        
        # Oscilloscope configuration changes
        scales = [0.5, 1.0, 2.0, 0.5]
        for scale in scales:
            await osc.set_channel_scale(1, scale)
            await osc.single()
            await asyncio.sleep(0.2)
        
    finally:
        await psu.output(1, False)
        await psu.set_voltage(1, 0.0)


if __name__ == "__main__":
    print("This script is designed to be run via PyTestLab replay commands.")
    print("")
    print("Usage examples:")
    print("  # Record with real hardware:")
    print("  pytestlab replay record example_measurement.py --bench bench.yaml --output session.yaml")
    print("")
    print("  # Replay recorded session:")
    print("  pytestlab replay run example_measurement.py --session session.yaml")
