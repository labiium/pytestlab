#!/usr/bin/env python3
"""
Real instrument test for PyTestLab replay functionality.
Uses PSU and Oscilloscope with LAMB backend for recording and replay.
"""

import yaml
from pathlib import Path
from pytestlab.instruments import AutoInstrument
from pytestlab.instruments.backends.session_recording_backend import SessionRecordingBackend
from pytestlab.instruments.backends.replay_backend import ReplayBackend
import numpy as np
import time


def test_real_instruments_recording():
    """Test recording with real PSU and oscilloscope via LAMB backend."""
    print("Testing real instrument recording with LAMB backend...")

    # Session log for recording
    psu_log = []
    osc_log = []

    try:
        # Connect to real instruments via LAMB
        print("Connecting to PSU via LAMB...")
        psu = AutoInstrument.from_config(
            "keysight/EDU36311A",
            simulate=False,
            backend_type_hint="lamb"
        )
        psu.connect_backend()

        print("Connecting to Oscilloscope via LAMB...")
        osc = AutoInstrument.from_config(
            "keysight/DSOX1204G",
            simulate=False,
            backend_type_hint="lamb"
        )
        osc.connect_backend()

        # Wrap backends for recording
        psu._backend = SessionRecordingBackend(psu._backend, psu_log)
        osc._backend = SessionRecordingBackend(osc._backend, osc_log)

        print("Starting measurement sequence...")

        # Realistic measurement sequence
        perform_measurement_sequence(psu, osc)

        # Save recorded session
        session_data = {
            "psu": {
                "profile": "keysight/EDU36311A",
                "log": psu_log
            },
            "osc": {
                "profile": "keysight/DSOX1204G",
                "log": osc_log
            }
        }

        session_file = Path("real_instrument_session.yaml")
        with open(session_file, "w") as f:
            yaml.dump(session_data, f, sort_keys=False)

        print(f"✓ Session recorded to {session_file}")
        print(f"PSU commands recorded: {len(psu_log)}")
        print(f"OSC commands recorded: {len(osc_log)}")

        return session_file

    except Exception as e:
        print(f"✗ Error during recording: {e}")
        import traceback
        traceback.print_exc()
        return None
    finally:
        try:
            psu.close()
            osc.close()
        except:
            pass


def test_replay_session(session_file: Path):
    """Test replaying the recorded session."""
    print(f"\nTesting replay from {session_file}...")

    if not session_file.exists():
        print("✗ Session file not found")
        return False

    try:
        # Load session data
        with open(session_file, "r") as f:
            session_data = yaml.safe_load(f)

        # Create replay backends
        print("Creating replay backends...")
        psu_backend = ReplayBackend(session_data["psu"]["log"], "psu")
        osc_backend = ReplayBackend(session_data["osc"]["log"], "osc")

        # Create instruments with replay backends
        psu_replay = AutoInstrument.from_config(
            "keysight/EDU36311A",
            backend_override=psu_backend
        )
        psu_replay.connect_backend()

        osc_replay = AutoInstrument.from_config(
            "keysight/DSOX1204G",
            backend_override=osc_backend
        )
        osc_replay.connect_backend()

        print("Replaying measurement sequence...")

        # Replay the same measurement sequence
        perform_measurement_sequence(psu_replay, osc_replay)

        print("✓ Replay completed successfully")

        psu_replay.close()
        osc_replay.close()

        return True

    except Exception as e:
        print(f"✗ Error during replay: {e}")
        import traceback
        traceback.print_exc()
        return False


def perform_measurement_sequence(psu, osc):
    """Perform a realistic measurement sequence using PSU and oscilloscope."""

    # Get instrument identification
    print("Getting instrument IDs...")
    psu_id = psu.id()
    osc_id = osc.id()
    print(f"PSU: {psu_id}")
    print(f"OSC: {osc_id}")

    # Configure oscilloscope
    print("Configuring oscilloscope...")
    osc.set_time_axis(0.001, 0.0)  # 1ms/div, centered
    osc.set_channel_axis(1, 1.0, 0.0)  # 1V/div, no offset
    osc.display_channel(1, True)  # Enable channel 1

    # Set trigger
    osc.configure_trigger(1, 2.5, source="CHAN1", mode="EDGE")

    # Configure PSU
    print("Configuring PSU...")
    psu.set_current(1, 0.1)  # 100mA current limit

    # Voltage sweep with oscilloscope measurements
    voltages = [1.0, 2.0, 3.0, 4.0, 5.0]
    measurements = []

    try:
        # Enable PSU output
        psu.output(1, True)
        print("PSU output enabled")

        for i, voltage in enumerate(voltages):
            print(f"Step {i+1}: Setting {voltage}V")

            # Set voltage
            psu.set_voltage(1, voltage)

            # Wait for settling
            time.sleep(0.5)

            # Read oscilloscope measurements - this will automatically digitize
            vpp = osc.measure_voltage_peak_to_peak(1)

            # Read PSU actual output
            actual_voltage = psu.read_voltage(1)
            actual_current = psu.read_current(1)

            measurements.append({
                'set_voltage': voltage,
                'actual_voltage': float(actual_voltage.values) if hasattr(actual_voltage, 'values') else actual_voltage,
                'actual_current': float(actual_current.values) if hasattr(actual_current, 'values') else actual_current,
                'osc_vpp': float(vpp.values) if hasattr(vpp, 'values') else vpp,
            })

            print(f"  Set: {voltage}V, Actual: {measurements[-1]['actual_voltage']:.3f}V, "
                  f"Current: {measurements[-1]['actual_current']:.3f}A, Vpp: {measurements[-1]['osc_vpp']:.3f}V")

    finally:
        # Safety: disable output
        psu.output(1, False)
        psu.set_voltage(1, 0.0)
        print("PSU output disabled")

    print("Measurement sequence completed")
    return measurements


def test_mismatch_detection(session_file: Path):
    """Test that replay correctly detects command mismatches."""
    print(f"\nTesting mismatch detection...")

    if not session_file.exists():
        print("✗ Session file not found")
        return False

    try:
        # Load session data
        with open(session_file, "r") as f:
            session_data = yaml.safe_load(f)

        # Create replay backend
        psu_backend = ReplayBackend(session_data["psu"]["log"], "psu")

        psu_replay = AutoInstrument.from_config(
            "keysight/EDU36311A",
            backend_override=psu_backend
        )
        psu_replay.connect_backend()

        # Start with correct command
        psu_replay.id()

        # Now try wrong command - this should fail
        try:
            psu_replay.set_voltage(1, 999.0)  # Wrong voltage value
            print("✗ Mismatch detection failed - should have caught wrong voltage")
            return False
        except Exception as e:
            print(f"✓ Correctly detected mismatch: {type(e).__name__}")
            return True

    except Exception as e:
        print(f"✗ Error in mismatch test: {e}")
        return False


def main():
    """Main test function."""
    print("PyTestLab Replay System Test with Real Instruments")
    print("=" * 50)

    # Step 1: Record with real instruments
    session_file = test_real_instruments_recording()
    if not session_file:
        print("✗ Recording failed, cannot continue with replay tests")
        return 1

    # Step 2: Test replay
    replay_success = test_replay_session(session_file)
    if not replay_success:
        print("✗ Replay test failed")
        return 1

    # Step 3: Test mismatch detection
    mismatch_success = test_mismatch_detection(session_file)
    if not mismatch_success:
        print("✗ Mismatch detection test failed")
        return 1

    print("\n" + "=" * 50)
    print("✓ All tests passed!")
    print(f"Session file: {session_file}")
    print("\nTo manually test replay:")
    print(f"pytestlab replay run test_script.py --session {session_file}")

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
