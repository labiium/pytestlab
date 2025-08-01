#!/usr/bin/env python3
"""
Exact replay test script that matches the recorded session sequence.
This script replicates the exact SCPI command sequence from real_instrument_session.yaml
"""

import time


def main(bench):
    """Main measurement function that exactly matches the recorded sequence."""
    print("Starting exact replay test...")

    # Get instrument references
    psu = bench.psu
    osc = bench.osc

    # Get instrument identification (these are automatically recorded)
    psu_id = psu.id()
    osc_id = osc.id()
    print(f"PSU ID: {psu_id}")
    print(f"OSC ID: {osc_id}")

    # Now follow the exact sequence from the recorded session
    print("\nExecuting exact recorded sequence...")

    # PSU sequence: Set current, enable output, then voltage sweep
    psu.set_current(1, 0.1)  # CURR 0.1, (@1)
    psu.output(1, True)      # OUTP:STAT ON, (@1)

    # OSC configuration sequence (matches recorded exactly)
    osc._backend.write(":TIMebase:SCALe 0.001")
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

    # Voltage sweep with measurements (exact sequence)
    voltages = [1.0, 2.0, 3.0, 4.0, 5.0]
    measurements = []

    for i, voltage in enumerate(voltages):
        print(f"Step {i+1}: Setting {voltage}V...")

        # Set voltage
        psu.set_voltage(1, voltage)  # VOLT X, (@1)

        # Wait for settling
        time.sleep(0.5)

        # Read PSU measurements (exact sequence from recording)
        measured_voltage = psu.read_voltage(1)  # MEAS:VOLT? (@1)
        measured_current = psu.read_current(1)  # MEAS:CURR? (@1)

        # Read oscilloscope measurement
        osc_measurement = osc._backend.query("MEAS:VPP? CHAN1")

        measurements.append({
            'set_voltage': voltage,
            'measured_voltage': float(measured_voltage),
            'measured_current': float(measured_current),
            'osc_vpp': float(osc_measurement),
            'step': i + 1
        })

        print(f"  PSU: {measured_voltage}V, {measured_current}A, OSC VPP: {osc_measurement}V")

    # Shutdown sequence (exact)
    psu.output(1, False)     # OUTP:STAT OFF, (@1)
    psu.set_voltage(1, 0.0)  # VOLT 0.0, (@1)

    print("\n✓ Exact replay sequence completed successfully!")
    print("Results summary:")
    for result in measurements:
        psu_error = abs(result['measured_voltage'] - result['set_voltage'])
        print(f"  Step {result['step']}: {result['set_voltage']}V → PSU: {result['measured_voltage']:.3f}V (error: {psu_error:.3f}V), Current: {result['measured_current']:.6f}A, OSC VPP: {result['osc_vpp']:.3f}V")

    return measurements

if __name__ == "__main__":
    print("This script is designed to be run via PyTestLab replay commands.")
    print("Use: pytestlab replay run exact_replay_test.py --session real_instrument_session.yaml")
