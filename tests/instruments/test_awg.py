"""
Real Instrument Sanity Test for EDU33212A Waveform Generator

This script exercises key functionality of the WaveformGenerator instrument class:
  - Query the instrument ID.
  - Set channel 1 to a SINE waveform with specific frequency, amplitude, and DC offset.
  - Set a phase offset and query maximum allowed phase.
  - Switch to a RAMP waveform, set its symmetry, and verify the setting.
  - Download an arbitrary waveform to channel 1.
  - Set the expected load impedance.
  - Set and then query voltage limits.
  - Enable channel 1 output briefly.
  - Test extra parameters on a PULSE waveform (duty cycle, pulse edge, transition, period).
  - Reset phase reference and synchronize phase across channels.
  - Set output polarity, voltage unit, and disable voltage coupling.
  - Set phase unlock error state.
  - Set additional waveforms (SQUARE with duty cycle and PRBS).
  - Check for system errors.
  - Retrieve and print the current configuration.
  - Run a self-test and print its result.
  
Before running, ensure that your WaveformGeneratorConfig settings match your EDU33212A instrument.
"""

import numpy as np
import time

# Import instrument class; adjust the module path as needed.
from pytestlab.instruments import AutoInstrument

def main():
    # Create an instrument instance using a string config.
    wg = AutoInstrument.from_config("keysight/EDU33212A")
    
    # --- Instrument Identification ---
    idn = wg.id()
    print("Instrument ID:", idn)
    
    # --- Reset Instrument to Default Settings ---
    print("\nResetting instrument to default settings...")
    wg.reset()
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
    arb_waveform = np.linspace(0, 1, 100)
    wg.set_arbitrary_waveform(channel=1, waveform=arb_waveform, scale=True, name="MyArbTest")
    
    # --- Test Impedance and Voltage Limits ---
    print("\n[5] Configuring impedance and voltage limits on channel 1...")
    wg.set_impedance(channel=1, impedance=50)
    imp = wg.get_impedance(channel=1)
    print(f"Impedance on channel 1 set to: {imp}")
    wg.set_voltage_limits(channel=1, low=-2.5, high=2.5)
    print("Voltage limits enabled on channel 1 (Low=-2.5V, High=2.5V)")
    
    # --- Enable Output for a Short Duration ---
    print("\n[6] Turning output ON for channel 1...")
    wg.output(channel=1, state=True)
    time.sleep(2)
    
    # --- Test Extra Parameters on PULSE Waveform ---
    print("\n[7] Testing extra parameters on PULSE waveform on channel 1...")
    # Adjusted values to avoid "data out of range" error:
    # Using 10 µs (0.00001 s) for pulse edge and 20 µs (0.00002 s) for transition (both).
    wg.set_waveform(
        channel=2,
        waveform_type="PULSE",
        duty_cycle=30,
        edge_time=0.000001,
        transition_both=0.0000002,
        period=0.005
    )
    time.sleep(0.2)
    
    # --- Test Phase Reference and Synchronization ---
    print("\n[8] Resetting phase reference on channel 1...")
    wg.set_phase_reference(channel=1)
    time.sleep(0.1)
    
    print("\n[9] Synchronizing phase across channels...")
    wg.synchronize_phase()
    time.sleep(0.1)
    
    # --- Test Output Polarity ---
    print("\n[10] Setting output polarity to inverted on channel 1...")
    wg.set_output_polarity(channel=1, polarity="inverted")
    time.sleep(0.1)
    
    # --- Test Voltage Unit and Coupling ---
    print("\n[11] Setting voltage unit to VRMS on channel 1...")
    wg.set_voltage_unit(channel=1, unit="VRMS")
    time.sleep(0.1)
    
    print("\n[12] Disabling voltage coupling on channel 1...")
    wg.set_voltage_coupling(channel=1, state=False)
    time.sleep(0.1)
    
    # --- Test Phase Unlock Error State ---
    print("\n[13] Setting phase unlock error state ON on channel 1...")
    wg.set_phase_unlock_error_state(True)
    time.sleep(0.1)
    
    # --- Test Additional Waveform Settings ---
    print("\n[14] Setting SQUARE waveform with duty cycle 50% on channel 1...")
    wg.set_waveform(channel=1, waveform_type="SQUare", duty_cycle=50)
    time.sleep(0.1)
    
    print("\n[15] Setting PRBS waveform on channel 2...")
    wg.set_waveform(channel=2, waveform_type="PRBS")
    time.sleep(0.1)
    
    # --- Check for System Errors ---
    print("\n[16] Querying system errors...")
    try:
        wg._error_check()
        print("No system errors reported.")
    except Exception as e:
        print("System Error:", e)
    
    # --- Disable Output and Print Configuration ---
    print("\n[17] Turning output OFF for channel 1...")
    wg.output(channel=1, state=False)
    config = wg.get_config(1)
    print("\nCurrent Configuration on Channel 1:")
    print(config)
    
    # --- Self-Test ---
    print("\n[18] Running self-test...")
    result = wg.self_test()
    print("Self-test result:", result)
    
    print("\nSanity check completed.")

if __name__ == "__main__":
    main()
