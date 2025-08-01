#!/usr/bin/env python3
"""
CLI test script for PyTestLab replay functionality.
This script mimics the measurement sequence recorded in real_instrument_session.yaml
"""

import time


def main(bench):
    """Main measurement function called by PyTestLab replay system."""
    print("Starting CLI replay test measurement...")

    # Get instrument references
    psu = bench.psu
    osc = bench.osc

    # Initialize instruments
    print("Initializing instruments...")

    # Get instrument identification
    psu_id = psu.id()
    osc_id = osc.id()
    print(f"PSU ID: {psu_id}")
    print(f"OSC ID: {osc_id}")

    # Configure oscilloscope - matching recorded sequence
    print("Configuring oscilloscope...")
    osc._backend.write(":TIMebase:SCALe 0.001")  # 1ms/div
    osc._backend.write(":TIMebase:POSition 0.0")
    osc._backend.query("*OPC?")
    osc._backend.write(":CHANnel1:SCALe 1.0")
    osc._backend.write(":CHANnel1:OFFSet 0.0")
    osc._backend.query("*OPC?")
    osc._backend.write("CHANnel1:DISPlay ON")
    osc._backend.write(":TRIG:SOUR CHANnel1")
    osc._backend.write(":TRIGger:LEVel 2.5, CHANnel1")
    osc._backend.write(":TRIGger:SLOPe POS")
    osc._backend.write(":TRIGger:MODE EDGE")
    osc._backend.query("*OPC?")

    # Voltage sweep parameters - matching recorded sequence
    voltages = [1.0, 2.0, 3.0, 4.0, 5.0]
    measurements = []

    print("\nPerforming voltage sweep measurement...")

    try:
        # Set current limit and enable output - matching recorded sequence
        psu.set_current(1, 0.1)  # 100mA current limit
        psu.output(1, True)

        for i, voltage in enumerate(voltages):
            print(f"Step {i+1}/{len(voltages)}: Setting {voltage}V")

            # Set PSU voltage
            psu.set_voltage(1, voltage)

            # Wait for settling
            time.sleep(0.5)

            # Read PSU measurements
            measured_voltage = psu.read_voltage(1)
            measured_current = psu.read_current(1)

            # Read oscilloscope measurement
            osc_measurement = osc._backend.query("MEAS:VPP? CHAN1")

            measurements.append({
                'set_voltage': voltage,
                'measured_voltage': float(measured_voltage),
                'measured_current': float(measured_current),
                'osc_vpp': float(osc_measurement),
                'step': i + 1
            })

            print(f"  Set: {voltage}V, PSU: {measured_voltage}V, {measured_current}A, OSC VPP: {osc_measurement}V")

    finally:
        # Always disable output for safety
        psu.output(1, False)
        psu.set_voltage(1, 0.0)

    print("\nMeasurement complete!")
    print("Results summary:")
    for result in measurements:
        psu_error = abs(result['measured_voltage'] - result['set_voltage'])
        print(f"  Step {result['step']}: {result['set_voltage']}V → PSU: {result['measured_voltage']:.3f}V (error: {psu_error:.3f}V), Current: {result['measured_current']:.3f}A, OSC VPP: {result['osc_vpp']:.3f}V")

    return measurements

if __name__ == "__main__":
    print("This script is designed to be run via PyTestLab replay commands.")
    print("Use: pytestlab replay run cli_test_measurement.py --session real_instrument_session.yaml")
