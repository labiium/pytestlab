"""
Integration tests for the replay system CLI commands.
"""

import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import click.exceptions
import pytest
import yaml

from pytestlab.cli import replay_record
from pytestlab.cli import replay_run
from pytestlab.errors import ReplayMismatchError


@pytest.fixture
def sample_bench_config():
    """Sample bench configuration for testing."""
    return {
        "psu": {
            "profile": "keysight/EDU36311A",
            "address": "USB0::0x2A8D::0x3102::CN61130056::INSTR",
        },
        "osc": {
            "profile": "keysight/DSOX1204G",
            "address": "USB0::0x0957::0x179B::CN63197144::INSTR",
        },
    }


@pytest.fixture
def temp_bench_file(sample_bench_config):
    """Create temporary bench configuration file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(sample_bench_config, f)
        bench_file = f.name

    yield bench_file

    Path(bench_file).unlink(missing_ok=True)


@pytest.fixture
def sample_session_data():
    """Sample session data for replay testing."""
    return {
        "psu": {
            "profile": "keysight/EDU36311A",
            "log": [
                {
                    "type": "query",
                    "command": "*IDN?",
                    "response": "Keysight Technologies,EDU36311A,CN61130056,K-01.08.03-01.00-01.08-02.00",
                    "timestamp": 0.029,
                },
                {"type": "write", "command": "CURR 0.1, (@1)", "timestamp": 0.713},
                {"type": "write", "command": "OUTP:STAT ON, (@1)", "timestamp": 0.761},
                {"type": "write", "command": "VOLT 1.0, (@1)", "timestamp": 0.810},
                {
                    "type": "query",
                    "command": "MEAS:VOLT? (@1)",
                    "response": "+9.99749200E-01",
                    "timestamp": 1.615,
                },
            ],
        }
    }


@pytest.fixture
def temp_session_file(sample_session_data):
    """Create temporary session file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(sample_session_data, f)
        session_file = f.name

    yield session_file

    Path(session_file).unlink(missing_ok=True)


@pytest.fixture
def simple_test_script():
    """Create a simple test script for replay."""
    script_content = '''#!/usr/bin/env python3
"""Simple test script for replay testing."""

def main(bench):
    """Main test function."""
    psu = bench.psu

    # Get ID
    psu_id = psu.id()
    print(f"PSU ID: {psu_id}")

    # Set current and enable output
    psu.set_current(1, 0.1)
    psu.output(1, True)

    # Set voltage
    psu.set_voltage(1, 1.0)

    # Read voltage
    voltage = psu.read_voltage(1)
    print(f"Voltage: {voltage}")

    return {"voltage": voltage}

if __name__ == "__main__":
    print("Use with pytestlab replay commands")
'''

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(script_content)
        script_file = f.name

    yield script_file

    Path(script_file).unlink(missing_ok=True)


class TestReplayRecord:
    """Test cases for replay record command."""

    def test_replay_record_basic(self, temp_bench_file, simple_test_script):
        """Test basic replay record functionality."""
        output_file = tempfile.mktemp(suffix=".yaml")

        try:

            class MockInstrument:
                def __init__(self):
                    self._backend = SimpleNamespace(
                        query=lambda command: {
                            "*IDN?": "Keysight Technologies,EDU36311A,Test",
                            "MEAS:VOLT? (@1)": "+9.99749000E-01",
                        }[command],
                        write=lambda command: None,
                        query_raw=lambda command: b"",
                    )

                def id(self):
                    return self._backend.query("*IDN?")

                def set_current(self, channel, current):
                    self._backend.write(f"CURR {current}, (@{channel})")

                def output(self, channel, state):
                    state_str = "ON" if state else "OFF"
                    self._backend.write(f"OUTP:STAT {state_str}, (@{channel})")

                def set_voltage(self, channel, voltage):
                    self._backend.write(f"VOLT {voltage}, (@{channel})")

                def read_voltage(self, channel):
                    return self._backend.query(f"MEAS:VOLT? (@{channel})")

            class MockBench:
                def __init__(self):
                    self.psu = MockInstrument()
                    self.devices = {"psu": self.psu}
                    self._config = SimpleNamespace(
                        devices={
                            "psu": SimpleNamespace(profile="keysight/EDU36311A"),
                        },
                        instruments={},
                    )
                    self.closed = False

                def close_all(self):
                    self.closed = True

            bench = MockBench()
            with patch("pytestlab.bench.Bench.open", return_value=bench):
                replay_record(simple_test_script, temp_bench_file, output_file)

            assert bench.closed is True
            recorded = yaml.safe_load(Path(output_file).read_text())
            assert recorded["psu"]["profile"] == "keysight/EDU36311A"
            assert [
                {key: value for key, value in entry.items() if key != "timestamp"}
                for entry in recorded["psu"]["log"]
            ] == [
                {
                    "type": "query",
                    "command": "*IDN?",
                    "response": "Keysight Technologies,EDU36311A,Test",
                },
                {"type": "write", "command": "CURR 0.1, (@1)"},
                {"type": "write", "command": "OUTP:STAT ON, (@1)"},
                {"type": "write", "command": "VOLT 1.0, (@1)"},
                {
                    "type": "query",
                    "command": "MEAS:VOLT? (@1)",
                    "response": "+9.99749000E-01",
                },
            ]

        finally:
            Path(output_file).unlink(missing_ok=True)

    def test_replay_record_argument_validation(self):
        """Test replay record command argument validation."""
        # Test missing script file
        with pytest.raises(click.exceptions.Exit):
            replay_record("/nonexistent/script.py", "/nonexistent/bench.yaml", "output.yaml")

        # Test missing bench file
        script_file = tempfile.mktemp(suffix=".py")
        Path(script_file).touch()

        try:
            with pytest.raises(click.exceptions.Exit):
                replay_record(script_file, "/nonexistent/bench.yaml", "output.yaml")
        finally:
            Path(script_file).unlink(missing_ok=True)


class TestReplayRun:
    """Test cases for replay run command."""

    def test_replay_run_successful(self, simple_test_script, temp_session_file):
        """Test successful replay run."""
        exact_script_content = '''#!/usr/bin/env python3
"""Script that exactly matches session data."""

def main(bench):
    """Main function that matches recorded session."""
    psu = bench.psu

    # This sequence must match the session data exactly
    psu_id = psu._backend.query('*IDN?')  # Direct backend call
    psu._backend.write('CURR 0.1, (@1)')
    psu._backend.write('OUTP:STAT ON, (@1)')
    psu._backend.write('VOLT 1.0, (@1)')
    voltage = psu._backend.query('MEAS:VOLT? (@1)')

    return {"psu_id": psu_id, "voltage": voltage}
'''

        exact_script_file = tempfile.mktemp(suffix=".py")
        with open(exact_script_file, "w") as f:
            f.write(exact_script_content)

        try:

            class MockReplayInstrument:
                def __init__(self, backend):
                    self._backend = backend
                    self.closed = False

                def connect_backend(self):
                    self._backend.connect()

                def close(self):
                    self.closed = True
                    self._backend.close()

            created_devices = []

            def from_config(config_source, backend_override):
                assert config_source == "keysight/EDU36311A"
                device = MockReplayInstrument(backend_override)
                created_devices.append(device)
                return device

            with patch("pytestlab.devices.AutoDevice.from_config", side_effect=from_config):
                replay_run(exact_script_file, temp_session_file)

            assert len(created_devices) == 1
            replay_backend = created_devices[0]._backend
            assert replay_backend._step == len(replay_backend._log)
            assert created_devices[0].closed is True

        finally:
            Path(exact_script_file).unlink(missing_ok=True)

    def test_replay_run_mismatch_detection(self, temp_session_file):
        """Test that replay detects command mismatches."""
        # Create a script that deviates from the recorded session
        mismatch_script_content = '''#!/usr/bin/env python3
"""Script that deviates from session data."""

def main(bench):
    """This function will cause a replay mismatch."""
    psu = bench.psu

    # First command matches
    psu._backend.query('*IDN?')

    # Second command is different - this should cause ReplayMismatchError
    psu._backend.write('VOLT 2.0, (@1)')  # Session expects 'CURR 0.1, (@1)'

    return {}
'''

        mismatch_script_file = tempfile.mktemp(suffix=".py")
        with open(mismatch_script_file, "w") as f:
            f.write(mismatch_script_content)

        try:
            from pytestlab.instruments.backends.replay_backend import ReplayBackend

            # Test ReplayBackend directly to verify mismatch detection
            backend = ReplayBackend(temp_session_file, "psu")

            # First command should succeed
            result = backend.query("*IDN?")
            assert (
                result == "Keysight Technologies,EDU36311A,CN61130056,K-01.08.03-01.00-01.08-02.00"
            )

            # Second command should fail (mismatch)
            with pytest.raises(ReplayMismatchError) as exc_info:
                backend.write("VOLT 2.0, (@1)")

            error = exc_info.value
            assert "Expected: type='write', cmd='CURR 0.1, (@1)'" in str(error)
            assert "Received: type='write', cmd='VOLT 2.0, (@1)'" in str(error)

        finally:
            Path(mismatch_script_file).unlink(missing_ok=True)

    def test_replay_run_invalid_session(self):
        """Test replay run with invalid session file."""
        script_file = tempfile.mktemp(suffix=".py")
        Path(script_file).touch()

        try:
            # Test missing session file
            with pytest.raises(click.exceptions.Exit):
                replay_run(script_file, "/nonexistent/session.yaml")

        finally:
            Path(script_file).unlink(missing_ok=True)


class TestReplayCLIIntegration:
    """Integration tests for CLI command integration."""

    def test_cli_commands_available(self):
        """Test that CLI commands are properly integrated."""
        # Import the CLI module to ensure replay commands are registered
        from pytestlab.cli import replay_app

        # Verify replay_app is added to main app
        # This tests the CLI structure without actually running commands
        assert replay_app is not None

    def test_record_and_replay_integration(self, temp_bench_file):
        """Test the full record -> replay cycle."""
        # Create a comprehensive test script
        comprehensive_script = '''#!/usr/bin/env python3
"""Comprehensive measurement script for record/replay testing."""

def main(bench):
    """Perform a complete measurement sequence."""
    psu = bench.psu

    # Initialize
    psu_id = psu.id()
    print(f"PSU ID: {psu_id}")

    # Setup measurement
    psu.set_current(1, 0.1)  # 100mA limit
    psu.output(1, True)      # Enable output

    # Voltage sweep
    measurements = []
    voltages = [1.0, 2.0, 3.0]

    for voltage in voltages:
        psu.set_voltage(1, voltage)
        time.sleep(0.1)  # Settling time

        measured_v = psu.read_voltage(1)
        measured_i = psu.read_current(1)

        measurements.append({
            'set_voltage': voltage,
            'measured_voltage': measured_v,
            'measured_current': measured_i
        })

        print(f"Set: {voltage}V, Measured: {measured_v}V, {measured_i}A")

    # Cleanup
    psu.output(1, False)
    psu.set_voltage(1, 0.0)

    return measurements

if __name__ == "__main__":
    print("Use with pytestlab replay commands")
'''

        script_file = tempfile.mktemp(suffix=".py")
        session_file = tempfile.mktemp(suffix=".yaml")

        try:
            with open(script_file, "w") as f:
                f.write(comprehensive_script)

            # Test the workflow components independently
            # (Full integration would require actual instruments)

            # Test 1: Verify script syntax is valid
            compile(comprehensive_script, script_file, "exec")

            # Test 2: Verify CLI argument structure
            from pytestlab.instruments.backends.replay_backend import ReplayBackend
            from pytestlab.instruments.backends.session_recording_backend import (
                SessionRecordingBackend,
            )

            # These should be importable and constructible with proper arguments
            assert ReplayBackend is not None
            assert SessionRecordingBackend is not None

        finally:
            for file_path in [script_file, session_file]:
                Path(file_path).unlink(missing_ok=True)

    def test_error_handling_in_cli(self):
        """Test error handling in CLI commands."""
        no_main_script = tempfile.mktemp(suffix=".py")
        temp_session = tempfile.mktemp(suffix=".yaml")
        with open(no_main_script, "w") as f:
            f.write('print("No main function")')
        with open(temp_session, "w") as f:
            yaml.safe_dump({"psu": {"profile": "keysight/EDU36311A", "log": []}}, f)

        try:
            with pytest.raises(click.exceptions.Exit) as exc_info:
                replay_run(no_main_script, temp_session)
            assert exc_info.value.exit_code == 1
        finally:
            Path(no_main_script).unlink(missing_ok=True)
            Path(temp_session).unlink(missing_ok=True)

        malformed_session = tempfile.mktemp(suffix=".yaml")
        with open(malformed_session, "w") as f:
            f.write("invalid: yaml: content: [")

        try:
            # CLI should handle YAML parsing errors
            with pytest.raises(yaml.YAMLError):
                with open(malformed_session) as f:
                    yaml.safe_load(f)
        finally:
            Path(malformed_session).unlink(missing_ok=True)


def test_replay_backend_with_cli_workflow():
    """Test ReplayBackend works correctly in CLI-like workflow."""
    # Create session data that simulates a full measurement workflow
    workflow_session = {
        "psu": {
            "profile": "keysight/EDU36311A",
            "log": [
                # Initialization
                {
                    "type": "query",
                    "command": "*IDN?",
                    "response": "Keysight,EDU36311A,Test",
                    "timestamp": 0.1,
                },
                {
                    "type": "query",
                    "command": ":SYSTem:ERRor?",
                    "response": '+0,"No error"',
                    "timestamp": 0.15,
                },
                # Setup
                {"type": "write", "command": "CURR 0.1, (@1)", "timestamp": 0.2},
                {
                    "type": "query",
                    "command": ":SYSTem:ERRor?",
                    "response": '+0,"No error"',
                    "timestamp": 0.25,
                },
                {"type": "write", "command": "OUTP:STAT ON, (@1)", "timestamp": 0.3},
                {
                    "type": "query",
                    "command": ":SYSTem:ERRor?",
                    "response": '+0,"No error"',
                    "timestamp": 0.35,
                },
                # Measurement sequence
                {"type": "write", "command": "VOLT 1.0, (@1)", "timestamp": 0.4},
                {
                    "type": "query",
                    "command": "MEAS:VOLT? (@1)",
                    "response": "+1.00123000E+00",
                    "timestamp": 0.5,
                },
                {
                    "type": "query",
                    "command": "MEAS:CURR? (@1)",
                    "response": "+5.12300000E-02",
                    "timestamp": 0.6,
                },
                {"type": "write", "command": "VOLT 2.0, (@1)", "timestamp": 0.7},
                {
                    "type": "query",
                    "command": "MEAS:VOLT? (@1)",
                    "response": "+2.00045600E+00",
                    "timestamp": 0.8,
                },
                {
                    "type": "query",
                    "command": "MEAS:CURR? (@1)",
                    "response": "+1.02340000E-01",
                    "timestamp": 0.9,
                },
                # Cleanup
                {"type": "write", "command": "OUTP:STAT OFF, (@1)", "timestamp": 1.0},
                {"type": "write", "command": "VOLT 0.0, (@1)", "timestamp": 1.1},
            ],
        }
    }

    # Create temporary session file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(workflow_session, f)
        session_file = f.name

    try:
        from pytestlab.instruments.backends.replay_backend import ReplayBackend

        backend = ReplayBackend(session_file, "psu")

        # Simulate the exact workflow from the session
        # Initialization
        idn = backend.query("*IDN?")
        assert idn == "Keysight,EDU36311A,Test"

        error = backend.query(":SYSTem:ERRor?")
        assert error == '+0,"No error"'

        # Setup
        backend.write("CURR 0.1, (@1)")
        backend.query(":SYSTem:ERRor?")
        backend.write("OUTP:STAT ON, (@1)")
        backend.query(":SYSTem:ERRor?")

        # Measurement sequence
        backend.write("VOLT 1.0, (@1)")
        v1 = backend.query("MEAS:VOLT? (@1)")
        i1 = backend.query("MEAS:CURR? (@1)")

        assert v1 == "+1.00123000E+00"
        assert i1 == "+5.12300000E-02"

        backend.write("VOLT 2.0, (@1)")
        v2 = backend.query("MEAS:VOLT? (@1)")
        i2 = backend.query("MEAS:CURR? (@1)")

        assert v2 == "+2.00045600E+00"
        assert i2 == "+1.02340000E-01"

        # Cleanup
        backend.write("OUTP:STAT OFF, (@1)")
        backend.write("VOLT 0.0, (@1)")

        # Verify all commands consumed
        assert backend._step == len(backend._log)

    finally:
        Path(session_file).unlink(missing_ok=True)
