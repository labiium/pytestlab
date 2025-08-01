#!/usr/bin/env python3
"""
Simple test script to verify the ReplayBackend functionality.
"""

import yaml
from pathlib import Path
from pytestlab.instruments.backends.replay_backend import ReplayBackend, ReplayMismatchError


def test_replay_backend():
    """Test the basic ReplayBackend functionality."""
    print("Testing ReplayBackend...")

    # Sample session log
    test_log = [
        {"type": "query", "command": "*IDN?", "response": "Test,Model,123,1.0", "timestamp": 0.1},
        {"type": "write", "command": "OUTP ON", "timestamp": 0.2},
        {"type": "query", "command": "MEAS:VOLT?", "response": "1.234", "timestamp": 0.5},
        {"type": "write", "command": "OUTP OFF", "timestamp": 0.8},
    ]

    # Create ReplayBackend
    backend = ReplayBackend(test_log, "test_instrument")

    try:
        # Test successful replay
        backend.connect()

        # Test correct sequence
        idn_response = backend.query("*IDN?")
        print(f"IDN Response: {idn_response}")
        assert idn_response == "Test,Model,123,1.0"

        backend.write("OUTP ON")
        print("Write command successful")

        volt_response = backend.query("MEAS:VOLT?")
        print(f"Voltage Response: {volt_response}")
        assert volt_response == "1.234"

        backend.write("OUTP OFF")
        print("Final write successful")

        backend.close()
        print("✓ Successful replay test passed")

    except Exception as e:
        print(f"✗ Error in successful replay test: {e}")
        return False

    # Test mismatch detection
    try:
        backend2 = ReplayBackend(test_log, "test_instrument2")
        backend2.connect()

        # This should work
        backend2.query("*IDN?")

        # This should fail - wrong command
        try:
            backend2.query("WRONG:CMD?")
            print("✗ Mismatch detection failed - should have raised ReplayMismatchError")
            return False
        except ReplayMismatchError as e:
            print(f"✓ Correctly caught mismatch: {e}")

        backend2.close()

    except Exception as e:
        print(f"✗ Error in mismatch test: {e}")
        return False

    return True


def test_session_files():
    """Test loading and replaying from session files."""
    print("\nTesting session file format...")

    # Sample session data
    session_data = {
        "psu": {
            "profile": "test/psu",
            "log": [
                {"type": "query", "command": "*IDN?", "response": "PSU,Model,456,2.0", "timestamp": 0.1},
                {"type": "write", "command": "VOLT 3.3", "timestamp": 0.2},
            ]
        },
        "dmm": {
            "profile": "test/dmm",
            "log": [
                {"type": "query", "command": "*IDN?", "response": "DMM,Model,789,1.5", "timestamp": 0.1},
                {"type": "query", "command": "READ?", "response": "3.301", "timestamp": 0.3},
            ]
        }
    }

    # Write to temporary file
    session_file = Path("test_session.yaml")
    try:
        with open(session_file, "w") as f:
            yaml.dump(session_data, f)

        # Read back and create backends
        with open(session_file, "r") as f:
            loaded_data = yaml.safe_load(f)

        # Test PSU backend
        psu_backend = ReplayBackend(loaded_data["psu"]["log"], "psu")
        psu_backend.connect()
        psu_id = psu_backend.query("*IDN?")
        psu_backend.write("VOLT 3.3")
        psu_backend.close()
        print(f"✓ PSU replay successful: {psu_id}")

        # Test DMM backend
        dmm_backend = ReplayBackend(loaded_data["dmm"]["log"], "dmm")
        dmm_backend.connect()
        dmm_id = dmm_backend.query("*IDN?")
        reading = dmm_backend.query("READ?")
        dmm_backend.close()
        print(f"✓ DMM replay successful: {dmm_id}, Reading: {reading}")

        return True

    except Exception as e:
        print(f"✗ Session file test failed: {e}")
        return False
    finally:
        if session_file.exists():
            session_file.unlink()


if __name__ == "__main__":
    def main():
        success1 = test_replay_backend()
        success2 = test_session_files()

        if success1 and success2:
            print("\n✓ All tests passed!")
            return 0
        else:
            print("\n✗ Some tests failed!")
            return 1

    import sys
    sys.exit(main())
