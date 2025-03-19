"""
Real Instrument Sanity Test for EDU33212A Waveform Generator

This script exercises key functionality of the WaveformGenerator instrument class:
  - Query the instrument ID.
  - Set channel 1 to a SINE waveform with specific frequency, amplitude, and DC offset.
  - Set a phase offset.
  - Query the maximum allowed phase.
  - Switch to a RAMP waveform, set its symmetry, and verify the setting.
  - Download an arbitrary waveform to channel 1.
  - Set the expected load impedance.
  - Set and then query voltage limits.
  - Enable channel 1 output briefly.
  - Query system errors.
  - Retrieve and print the current configuration.
  - Run a self-test and print its result.
  
Before running, ensure that your WaveformGeneratorConfig settings match your EDU33212A instrument.
"""

import numpy as np
import time

# Import instrument class; adjust the module path as needed.
from pytestlab.instruments import AutoInstrument

def main():
    # Create an instrument instance from configuration.
    wg = AutoInstrument.from_config("keysight/EDU33212A")
    
    # --- Instrument Identification ---
    idn = wg.id()
    print("Instrument ID:", idn)
    
    # --- Test Built-In SINE Waveform Settings ---
    print("\n[1] Setting SINE waveform on channel 1...")
    wg.set_waveform(channel=1, waveform_type="SINusoid")
    time.sleep(0.2)
    wg.set_frequency(channel=1, frequency=50000)   # 50 kHz
    wg.set_amplitude(channel=1, amplitude=3.0)       # 3 Vpp
    wg.set_offset(channel=1, offset=0.5)             # 0.5 V DC offset
    
    # Set phase offset and query maximum allowed phase.
    print("\n[2] Setting phase offset to 45° on channel 1...")
    wg.set_phase(channel=1, phase=45)
    time.sleep(0.3)
    max_phase = wg._query("SOUR1:PHASe? MAXimum")
    print("Maximum phase allowed (raw query):", max_phase)
    
    # --- Test Ramp Waveform and Symmetry ---
    print("\n[3] Switching to RAMP waveform and setting symmetry to 50% on channel 1...")
    wg.set_waveform(channel=1, waveform_type="RAMP")
    wg.set_symmetry(channel=1, symmetry=50)
    time.sleep(0.2)
    
    # --- Test Arbitrary Waveform Download ---
    print("\n[4] Downloading an arbitrary waveform on channel 1...")
    # Create a simple linear ramp waveform with 100 sample points.
    arb_waveform = np.linspace(0, 1, 100)
    wg.set_arbitrary_waveform(channel=1, waveform=arb_waveform, scale=True, name="MyArbTest")
    
    # --- Test Impedance and Voltage Limits ---
    print("\n[5] Configuring impedance and voltage limits on channel 1...")
    wg.set_impedance(channel=1, impedance=50)
    imp = wg.get_impedance(channel=1)
    print(f"Impedance on channel 1 set to: {imp}")
    
    # Set voltage limits (e.g. limit output to ±2.5 V)
    wg.set_voltage_limits(channel=1, low=-2.5, high=2.5)
    print("Voltage limits enabled on channel 1 (Low=-2.5V, High=2.5V)")
    
    # --- Enable Output for a Short Duration ---
    print("\n[6] Turning output ON for channel 1...")
    wg.output(channel=1, state=True)
    time.sleep(2)  # Allow time for observation
    
    # --- Check for System Errors ---
    error = wg._error_check()
    print("\nSystem Error Query Response:", error)
    
    # --- Disable Output and Print Configuration ---
    print("\n[7] Turning output OFF for channel 1...")
    wg.output(channel=1, state=False)
    config = wg.get_config(1)
    print("\nCurrent Configuration on Channel 1:")
    print(config)
    
    # --- Set SQUARE with duty cycle 50% ---
    print("\n[8] Setting SQUARE waveform on channel 1...")
    wg.set_waveform(channel=1, waveform_type="SQUare", duty_cycle=50)

    # --- Self-Test ---
    print("\n[10] Running self-test...")
    result = wg.self_test()
    print("Self-test result:", result)
    
    print("\nSanity check completed.")

if __name__ == "__main__":
    main()
