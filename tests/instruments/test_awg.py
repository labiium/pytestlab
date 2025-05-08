"""
Real Instrument Sanity Test for EDU33210 Series Waveform Generator

This script exercises key functionality of the WaveformGenerator instrument class:
  - Query the instrument ID.
  - Reset the instrument.
  - Set channel 1 to a SINE waveform with specific frequency, amplitude, and DC offset.
  - Set phase offset, get current phase, and query maximum allowed phase.
  - Set angle unit to Radians and Degrees.
  - Switch to a RAMP waveform, set its symmetry, and verify the setting.
  - Download an arbitrary waveform to channel 1, select it, and set its sample rate.
  - Set the expected load impedance, test MIN/MAX/DEF and INFinity.
  - Set, query, enable, and then disable voltage limits.
  - Test output polarity (normal and inverted).
  - Test voltage units (VPP, VRMS, DBM with appropriate impedance).
  - Test voltage autorange settings.
  - Enable channel 1 output briefly, then disable it.
  - Test extra parameters on a PULSE waveform (duty_cycle, width, transition_leading/trailing/both, period, hold_mode).
  - Test extra parameters on a SQUARE waveform (duty_cycle, period).
  - Test extra parameters on a PRBS waveform (bit_rate, data_type, transition_both).
  - Test extra parameters on a NOISE waveform (bandwidth).
  - Reset phase reference and synchronize phase across channels (if 2-channel).
  - Set and get phase unlock error state.
  - Apply waveform settings using the high-level APPLy command.
  - Test AM modulation.
  - Wait for operations to complete.
  - Clear status and check for system errors.
  - Retrieve and print the current configuration using get_complete_config.
  - Run a self-test and print its result.
  - Close the instrument connection.

Before running, ensure that your WaveformGeneratorConfig settings match your EDU33210
instrument and the instrument is connected.
This test is designed for a Keysight EDU33212A (2-channel) but will adapt some tests for 1-channel models.
"""

import numpy as np
import time
import unittest

from pytestlab.errors import InstrumentConfigurationError # Using unittest for structured testing
from pytestlab.instruments import AutoInstrument
# --- Placeholder for your actual configuration loading ---
# You'll need to have a JSON configuration file for your instrument.
# Example: "configs/keysight_edu33212a.json"

class TestWaveformGeneratorEDU33210(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        """Set up the instrument connection once for all tests."""
        try:
            # Use the AutoInstrument factory pattern
            cls.wg = AutoInstrument.from_config("keysight/EDU33212A", debug_mode=True)

            # --- FIX IS HERE ---
            # Access config VIA the instrument instance (cls.wg)
            if cls.wg and hasattr(cls.wg, 'config'): # Check if wg was created and has config
                cls.config = cls.wg.config # Store config on cls for convenience if needed later
                cls.is_two_channel = len(cls.config.channels)
                print(f"Instrument setup complete. Model: {cls.config.model}, Two-channel: {cls.is_two_channel}")
            else:
                # Handle case where instrument creation failed but didn't raise immediately
                print("Instrument object (cls.wg) or its config is missing after creation attempt.")
                cls.wg = None # Ensure it's None
                raise InstrumentConfigurationError("Failed to properly initialize Waveform Generator or its config.")
            # --- END FIX ---

        except Exception as e:
            print(f"Failed to initialize instrument via AutoInstrument: {e}")
            cls.wg = None # Ensure wg is None if setup fails
            raise

    @classmethod
    def tearDownClass(cls):
        """Close the instrument connection after all tests."""
        if cls.wg:
            try:
                cls.wg.set_output_state(1, False) # Turn off output
                if cls.is_two_channel:
                    cls.wg.set_output_state(2, False)
            except Exception as e:
                print(f"Error turning off output during teardown: {e}")
            finally:
                cls.wg.close()
                print("\nInstrument connection closed.")

    def setUp(self):
        """Reset instrument before each test method."""
        if not self.wg:
            self.skipTest("Waveform Generator not initialized.")
        print(f"\n--- Running test: {self.id()} ---")
        self.wg.reset() # Use the new method name
        self.wg.clear_status()
        time.sleep(0.5) # Give instrument time to settle after reset

    def test_01_identification_and_reset(self):
        print("Querying instrument ID...")
        idn = self.wg.id()
        self.assertIn(self.config.manufacturer.upper(), idn.upper())
        self.assertIn(self.config.model.upper(), idn.upper())
        print("Instrument ID:", idn)

        print("Resetting instrument (already done in setUp, but good to have a test for it)...")
        self.wg.reset_instrument()
        time.sleep(0.5)
        # Verify a default state if possible, e.g., CH1 output is OFF
        self.assertFalse(self.wg.get_output_state(1), "Channel 1 output should be OFF after reset.")

    def test_02_sine_waveform_and_phase(self):
        print("Setting SINE waveform on channel 1...")
        self.wg.set_function(channel=1, function_type="SINE")
        self.wg.set_frequency(channel=1, frequency=50000)   # 50 kHz
        self.wg.set_amplitude(channel=1, amplitude=3.0)     # 3 Vpp (assuming VPP unit)
        self.wg.set_offset(channel=1, offset=0.5)           # 0.5 V DC offset

        self.assertEqual(self.wg.get_function(1).upper(), "SIN")
        self.assertAlmostEqual(self.wg.get_frequency(1), 50000, delta=1)
        self.assertAlmostEqual(self.wg.get_amplitude(1), 3.0, delta=0.01)
        self.assertAlmostEqual(self.wg.get_offset(1), 0.5, delta=0.01)

        print("Setting phase offset to 45° on channel 1...")
        self.wg.set_angle_unit("DEGree")
        self.wg.set_phase(channel=1, phase=45)
        time.sleep(0.1)
        current_phase = self.wg.get_phase(channel=1)
        self.assertAlmostEqual(current_phase, 45, delta=0.1)

        max_phase_val = self.wg.get_phase(channel=1, query_type="MAXimum")
        print(f"Max phase from get_phase: {max_phase_val}")
        self.assertGreaterEqual(max_phase_val, 360) # Should be 360 for degrees

        print("Setting angle unit to Radians...")
        self.wg.set_angle_unit("RADian")
        self.assertEqual(self.wg.get_angle_unit().upper(), "RAD")
        # Phase value will be converted by instrument, get it back to check
        phase_in_rad = self.wg.get_phase(channel=1)
        self.assertAlmostEqual(phase_in_rad, 45 * (np.pi / 180.0), delta=0.01)

        self.wg.set_angle_unit("DEGree") # Back to degrees for other tests
        self.assertEqual(self.wg.get_angle_unit().upper(), "DEG")


    def test_03_ramp_waveform_and_symmetry(self):
        print("Switching to RAMP waveform and setting symmetry on channel 1...")
        self.wg.set_function(channel=1, function_type="RAMP", symmetry=75)
        self.assertEqual(self.wg.get_function(1).upper(), "RAMP")

        # Query symmetry (assuming it's part of get_complete_config or a new get_symmetry method)
        # For now, let's assume get_complete_config can fetch it.
        # config = self.wg.get_complete_config(1)
        # self.assertAlmostEqual(config.symmetry, 75, delta=0.1)
        # Or, if a direct getter exists:
        # self.assertAlmostEqual(self.wg.get_ramp_symmetry(1), 75, delta=0.1)
        # Let's use a direct query for now if getter is not implemented in the class yet
        queried_symmetry = float(self.wg._query("SOUR1:FUNC:RAMP:SYMM?"))
        self.assertAlmostEqual(queried_symmetry, 75, delta=0.1)


    def test_04_arbitrary_waveform(self):
        print("Testing Arbitrary Waveform on channel 1...")
        arb_data_dac = np.linspace(-32767, 32767, 128, dtype=np.int16) # 128 points
        arb_name = "MyArbTest1"

        self.wg.clear_volatile_arbitrary_waveforms(1)
        free_mem_before = self.wg.get_free_volatile_arbitrary_memory(1)

        self.wg.download_arbitrary_waveform_data(channel=1, arb_name=arb_name, data_points=arb_data_dac, data_type="DAC")
        self.wg.select_arbitrary_waveform(channel=1, arb_name=arb_name)
        self.wg.set_function(channel=1, function_type="ARB") # Activate ARB mode
        self.assertEqual(self.wg.get_function(1).upper(), "ARB")
        self.assertTrue(arb_name in self.wg.get_selected_arbitrary_waveform_name(1))

        self.assertEqual(self.wg.get_arbitrary_waveform_points(1), len(arb_data_dac))

        self.wg.set_arbitrary_waveform_sample_rate(channel=1, sample_rate=100000) # 100 kSa/s
        self.assertAlmostEqual(self.wg.get_arbitrary_waveform_sample_rate(1), 100000, delta=1)

        free_mem_after = self.wg.get_free_volatile_arbitrary_memory(1)
        # Memory usage might be in blocks, so not an exact reduction of len(arb_data_dac)
        self.assertLess(free_mem_after, free_mem_before)
        print(f"Free arb memory before: {free_mem_before}, after: {free_mem_after}")

    def test_05_impedance_and_voltage_limits(self):
        print("Configuring impedance and voltage limits on channel 1...")
        # Test numeric impedance
        self.wg.set_output_load_impedance(channel=1, impedance=50)
        self.assertAlmostEqual(self.wg.get_output_load_impedance(channel=1), 50, delta=0.1)

        # Test INFinity
        self.wg.set_output_load_impedance(channel=1, impedance="INFinity")
        # get_output_load_impedance should return "INFinity" string for this
        self.assertEqual(self.wg.get_output_load_impedance(channel=1).upper(), "INFINITY")

        # Test MIN/MAX/DEF - These set the impedance to a specific value, query it back
        self.wg.set_output_load_impedance(channel=1, impedance="DEFault") # Default is 50 Ohm
        self.assertAlmostEqual(self.wg.get_output_load_impedance(channel=1), 50, delta=0.1)
        # Query MIN/MAX for impedance
        min_imp = self.wg.get_output_load_impedance(1, query_type="MINimum")
        max_imp = self.wg.get_output_load_impedance(1, query_type="MAXimum")
        self.assertEqual(min_imp, 1.0)    # Manual: 1 Ohm to 10 kOhm
        self.assertEqual(max_imp, 10000.0)


        self.wg.set_voltage_limit_low(channel=1, voltage=-2.5)
        self.wg.set_voltage_limit_high(channel=1, voltage=2.5)
        self.wg.set_voltage_limits_state(channel=1, state=True)
        self.assertTrue(self.wg.get_voltage_limits_state(channel=1))
        self.assertAlmostEqual(self.wg.get_voltage_limit_low(channel=1), -2.5, delta=0.01)
        self.assertAlmostEqual(self.wg.get_voltage_limit_high(channel=1), 2.5, delta=0.01)

        self.wg.set_voltage_limits_state(channel=1, state=False)
        self.assertFalse(self.wg.get_voltage_limits_state(channel=1))

    def test_06_output_state_and_polarity_voltage_unit_autorange(self):
        print("Testing output state, polarity, voltage unit, autorange on channel 1...")
        self.wg.set_output_state(channel=1, state=True)
        self.assertTrue(self.wg.get_output_state(channel=1))
        print("Channel 1 Output ON")
        time.sleep(0.5) # Keep output on briefly

        self.wg.set_output_polarity(channel=1, polarity="INVerted")
        self.assertEqual(self.wg.get_output_polarity(channel=1).upper(), "INVERTED")
        time.sleep(0.1)
        self.wg.set_output_polarity(channel=1, polarity="NORMal")
        self.assertEqual(self.wg.get_output_polarity(channel=1).upper(), "NORMAL")

        self.wg.set_voltage_unit(channel=1, unit="VRMS")
        self.assertEqual(self.wg.get_voltage_unit(channel=1).upper(), "VRMS")
        # Set DBM requires 50 Ohm load typically
        self.wg.set_output_load_impedance(channel=1, impedance=50)
        self.wg.set_voltage_unit(channel=1, unit="DBM")
        self.assertEqual(self.wg.get_voltage_unit(channel=1).upper(), "DBM")
        self.wg.set_voltage_unit(channel=1, unit="VPP") # Back to VPP
        self.assertEqual(self.wg.get_voltage_unit(channel=1).upper(), "VPP")


        self.wg.set_voltage_autorange_state(channel=1, state="OFF")
        self.assertEqual(self.wg.get_voltage_autorange_state(channel=1).upper(), "OFF")
        self.wg.set_voltage_autorange_state(channel=1, state="ONCE") # Sets to OFF after one autorange
        time.sleep(0.2) # Allow ONCE to complete
        self.assertEqual(self.wg.get_voltage_autorange_state(channel=1).upper(), "OFF")
        self.wg.set_voltage_autorange_state(channel=1, state="ON")
        self.assertEqual(self.wg.get_voltage_autorange_state(channel=1).upper(), "ON")


        self.wg.set_output_state(channel=1, state=False)
        self.assertFalse(self.wg.get_output_state(channel=1))
        print("Channel 1 Output OFF")

    def test_07_pulse_waveform_params(self):
        print("Testing PULSE waveform parameters on channel 1...")
        # Use values that are generally safe. Min edge/transition times are small (ns range).
        # Period should be significantly larger than sum of width and transitions.
        target_period = 0.001 # 1ms -> 1kHz
        target_width = target_period * 0.2 # 20% duty cycle -> 0.2ms width
        target_transition = target_width * 0.05 # 5% of width, e.g., 10us

        self.wg.set_function(
            channel=1,
            function_type="PULSE",
            period=target_period,
            width=target_width,
            # duty_cycle=20, # Either width or duty_cycle, not both initially. Hold mode determines behavior.
            transition_leading=target_transition,
            transition_trailing=target_transition,
            hold_mode="WIDTH" # Hold width constant when period changes
        )
        self.assertEqual(self.wg.get_function(1).upper(), "PULS")
        # Verify some params - direct queries for now
        self.assertAlmostEqual(float(self.wg._query("SOUR1:FUNC:PULS:PER?")), target_period, delta=target_period*0.01)
        self.assertAlmostEqual(float(self.wg._query("SOUR1:FUNC:PULS:WIDT?")), target_width, delta=target_width*0.01)
        self.assertAlmostEqual(float(self.wg._query("SOUR1:FUNC:PULS:TRAN:LEAD?")), target_transition, delta=target_transition*0.05)
        self.assertEqual(self.wg._query("SOUR1:FUNC:PULS:HOLD?").strip().upper(), "WIDT")

        # Test transition_both
        target_trans_both = target_width * 0.02
        self.wg.set_function(channel=1, function_type="PULSE", transition_both=target_trans_both)
        self.assertAlmostEqual(float(self.wg._query("SOUR1:FUNC:PULS:TRAN:LEAD?")), target_trans_both, delta=target_trans_both*0.05)
        self.assertAlmostEqual(float(self.wg._query("SOUR1:FUNC:PULS:TRAN:TRA?")), target_trans_both, delta=target_trans_both*0.05)

    def test_08_square_prbs_noise_params(self):
        print("Testing SQUARE, PRBS, NOISE parameters...")
        # SQUARE
        self.wg.set_function(channel=1, function_type="SQUARE", duty_cycle=30, period=0.0005) # 2kHz
        self.assertEqual(self.wg.get_function(1).upper(), "SQU")
        self.assertAlmostEqual(float(self.wg._query("SOUR1:FUNC:SQU:DCYC?")), 30, delta=0.1)
        self.assertAlmostEqual(float(self.wg._query("SOUR1:FUNC:SQU:PER?")), 0.0005, delta=0.0005*0.01)

        if self.is_two_channel:
            target_ch = 2
        else:
            target_ch = 1
            self.wg.reset_instrument() # Reset CH1 for PRBS/NOISE if only 1 channel

        # PRBS
        self.wg.set_function(channel=target_ch, function_type="PRBS", bit_rate=10000, data_type="PN11", transition_both=1e-7) # 10kbps, PN11, 100ns
        self.assertEqual(self.wg.get_function(target_ch).upper(), "PRBS")
        self.assertAlmostEqual(float(self.wg._query(f"SOUR{target_ch}:FUNC:PRBS:BRAT?")), 10000, delta=10)
        self.assertEqual(self.wg._query(f"SOUR{target_ch}:FUNC:PRBS:DATA?").strip().upper(), "PN11")
        self.assertAlmostEqual(float(self.wg._query(f"SOUR{target_ch}:FUNC:PRBS:TRAN:BOTH?")), 1e-7, delta=1e-7*0.05)

        # NOISE
        self.wg.set_function(channel=target_ch, function_type="NOISE", bandwidth=5e6) # 5MHz bandwidth
        self.assertEqual(self.wg.get_function(target_ch).upper(), "NOIS")
        self.assertAlmostEqual(float(self.wg._query(f"SOUR{target_ch}:FUNC:NOIS:BAND?")), 5e6, delta=5e6*0.01)


    def test_09_phase_reference_sync_unlock(self):
        print("Testing phase reference, synchronization, and unlock error state...")
        self.wg.set_phase(channel=1, phase=30)
        self.wg.set_phase_reference(channel=1)
        time.sleep(0.1)
        # After reference, phase should be 0 relative to the new reference
        self.assertAlmostEqual(self.wg.get_phase(channel=1), 0, delta=0.1)

        if self.is_two_channel:
            self.wg.set_phase(channel=1, phase=10)
            self.wg.set_phase(channel=2, phase=20)
            self.wg.synchronize_phase_all_channels()
            # The absolute phases might not be exactly 0, but they are now synced.
            # Verifying exact phase after sync is tricky without external measurement.
            # We mostly test that the command doesn't error.
            print("Phase synchronization command sent.")

        self.wg.set_phase_unlock_error_state(True)
        self.assertTrue(self.wg.get_phase_unlock_error_state())
        self.wg.set_phase_unlock_error_state(False)
        self.assertFalse(self.wg.get_phase_unlock_error_state())

    def test_10_apply_command_and_am_modulation(self):
        print("Testing APPLy command and AM Modulation on channel 1...")
        # APPLy SINE
        self.wg.apply_waveform_settings(channel=1, function_type="SINE", frequency=1000, amplitude=1.5, offset=0.1)
        config_summary = self.wg.get_channel_configuration_summary(1)
        self.assertIn("SIN", config_summary)
        self.assertIn("1.000000000000000E+03", config_summary) # Freq
        self.assertTrue(self.wg.get_output_state(1)) # APPLy turns output ON

        # AM Modulation
        self.wg.set_am_depth(channel=1, depth_percent=50)
        if self.is_two_channel:
            # Setup CH2 as a simple sine for modulation source
            self.wg.set_function(2, "SINE")
            self.wg.set_frequency(2, 100) # 100Hz modulating freq
            self.wg.set_amplitude(2, 1.0)
            self.wg.set_output_state(2, True)
            self.wg.set_am_source(channel=1, source="CH2")
        else:
            # Internal AM source for 1-channel test
            self.wg._send_command("SOUR1:AM:INT:FUNC SIN") # Not yet in class
            self.wg._send_command("SOUR1:AM:INT:FREQ 100")
            self.wg.set_am_source(channel=1, source="INTernal")

        self.wg.enable_am_modulation(channel=1, state=True)
        # Verify AM state with direct query for now
        self.assertEqual(self.wg._query("SOUR1:AM:STATe?").strip(), "1")

        self.wg.enable_am_modulation(channel=1, state=False)
        self.assertEqual(self.wg._query("SOUR1:AM:STATe?").strip(), "0")

    def test_11_opc_and_error_check(self):
        print("Testing Operation Complete and Error Check...")
        self.wg.set_frequency(1, 12345)
        opc_query_result = self.wg.wait_for_operation_complete(query_instrument=True)
        self.assertEqual(opc_query_result, "1")

        self.wg.set_amplitude(1, 2.345)
        self.wg.wait_for_operation_complete(query_instrument=False) # Just send *OPC
        # Could add a small delay and check status byte if we had status methods

        # Intentionally create an error (e.g., parameter out of range if known)
        # For now, just clear and check
        self.wg.clear_status()
        try:
            self.wg._error_check() # Should raise nothing
            print("No system errors reported after clear.")
        except Exception as e:
            self.fail(f"Error check failed unexpectedly after *CLS: {e}")

    def test_12_get_complete_config(self):
        print("Retrieving and printing complete configuration for channel 1...")
        self.wg.set_function(1, "RAMP", symmetry=60)
        self.wg.set_frequency(1, 7890)
        self.wg.set_amplitude(1, 2.2)
        self.wg.set_offset(1, -0.3)
        self.wg.set_phase(1, -15)
        self.wg.set_output_load_impedance(1, "INF")
        self.wg.set_voltage_unit(1, "VRMS")

        config_obj = self.wg.get_complete_config(1)
        print("\nDetailed Configuration on Channel 1:")
        print(f"  Function: {config_obj.function}")
        print(f"  Frequency: {config_obj.frequency} Hz")
        print(f"  Amplitude: {config_obj.amplitude} {config_obj.voltage_unit}")
        print(f"  Offset: {config_obj.offset} V")
        print(f"  Phase: {config_obj.phase} {self.wg.get_angle_unit()}")
        print(f"  Symmetry: {config_obj.symmetry}%")
        print(f"  Duty Cycle: {config_obj.duty_cycle}%")
        print(f"  Output State: {'ON' if config_obj.output_state else 'OFF'}")
        print(f"  Load Impedance: {config_obj.load_impedance}")

        self.assertEqual(config_obj.function.upper(), "RAMP")
        self.assertAlmostEqual(config_obj.frequency, 7890, delta=10)
        self.assertAlmostEqual(config_obj.amplitude, 2.2, delta=0.01) # Will be in VRMS
        self.assertAlmostEqual(config_obj.offset, -0.3, delta=0.01)
        self.assertAlmostEqual(config_obj.phase, -15, delta=0.1)
        self.assertAlmostEqual(config_obj.symmetry, 60, delta=0.1)
        self.assertEqual(config_obj.load_impedance.upper(), "INFINITY")
        self.assertEqual(config_obj.voltage_unit.upper(), "VRMS")


    def test_13_self_test(self):
        print("Running self-test...")
        result_code = self.wg._query("*TST?") # Using base class _query for direct result
        result_int = int(result_code.strip())
        self.assertEqual(result_int, 0, f"Self-test failed with code: {result_int}")
        print(f"Self-test passed (Code: {result_int}).")
        # Or using the class method:
        # test_status = self.wg.self_test()
        # self.assertEqual(test_status, "Passed")
        # print(f"Self-test result from method: {test_status}")

if __name__ == "__main__":
    # This allows running the tests directly from the script
    # For more robust testing, use `python -m unittest your_test_file.py`
    # You might need to adjust Python's path if imports fail when run directly
    # import sys
    # import os
    # # Add the parent directory of 'pytestlab' to the Python path
    # sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))
    
    unittest.main()