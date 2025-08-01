"""
Tests for SessionRecordingBackend functionality
"""

import time
import pytest
import tempfile
import yaml
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from pytestlab.instruments.backends.session_recording_backend import SessionRecordingBackend


class MockBackend:
    """Mock backend for testing SessionRecordingBackend."""

    def __init__(self):
        self.query_responses = {}
        self.write_commands = []

    def query(self, command):
        """Mock query method."""
        if command in self.query_responses:
            return self.query_responses[command]
        return f"MOCK_RESPONSE_{command}"

    def write(self, command):
        """Mock write method."""
        self.write_commands.append(command)


@pytest.fixture
def mock_backend():
    """Create a mock backend for testing."""
    backend = MockBackend()
    backend.query_responses = {
        '*IDN?': 'Keysight Technologies,EDU36311A,CN61130056,K-01.08.03-01.00-01.08-02.00',
        ':SYSTem:ERRor?': '+0,"No error"',
        'MEAS:VOLT? (@1)': '+1.50000000E+00',
    }
    return backend


@pytest.fixture
def temp_output_file():
    """Create a temporary output file for recording."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        temp_file = f.name

    yield temp_file

    # Cleanup
    Path(temp_file).unlink(missing_ok=True)


@pytest.fixture
def recording_backend(mock_backend, temp_output_file):
    """Create a SessionRecordingBackend for testing."""
    return SessionRecordingBackend(mock_backend, temp_output_file, 'psu')


class TestSessionRecordingBackend:
    """Test cases for SessionRecordingBackend."""
    def test_initialization(self, mock_backend, temp_output_file):
        """Test SessionRecordingBackend initialization."""
        backend = SessionRecordingBackend(mock_backend, temp_output_file, 'psu')

        assert backend.backend is mock_backend
        assert backend.output_file == temp_output_file
        assert backend.profile_key == 'psu'
        assert backend._command_log == []
    def test_query_recording(self, recording_backend, temp_output_file):
        """Test query command recording."""
        # Execute a query
        result = recording_backend.query('*IDN?')

        # Check response
        assert result == 'Keysight Technologies,EDU36311A,CN61130056,K-01.08.03-01.00-01.08-02.00'

        # Check log entry
        assert len(recording_backend._command_log) == 1
        log_entry = recording_backend._command_log[0]
        assert log_entry['type'] == 'query'
        assert log_entry['command'] == '*IDN?'
        assert log_entry['response'] == 'Keysight Technologies,EDU36311A,CN61130056,K-01.08.03-01.00-01.08-02.00'
        assert 'timestamp' in log_entry
    def test_write_recording(self, recording_backend):
        """Test write command recording."""
        # Execute a write
        recording_backend.write('CURR 0.1, (@1)')

        # Check log entry
        assert len(recording_backend._command_log) == 1
        log_entry = recording_backend._command_log[0]
        assert log_entry['type'] == 'write'
        assert log_entry['command'] == 'CURR 0.1, (@1)'
        assert 'response' not in log_entry  # Write commands don't have responses
        assert 'timestamp' in log_entry
    def test_mixed_command_sequence(self, recording_backend):
        """Test recording a sequence of mixed commands."""
        # Execute sequence
        idn_result = recording_backend.query('*IDN?')
        recording_backend.write('CURR 0.1, (@1)')
        error_result = recording_backend.query(':SYSTem:ERRor?')
        volt_result = recording_backend.query('MEAS:VOLT? (@1)')
        recording_backend.write('OUTP:STAT ON, (@1)')

        # Verify responses
        assert idn_result == 'Keysight Technologies,EDU36311A,CN61130056,K-01.08.03-01.00-01.08-02.00'
        assert error_result == '+0,"No error"'
        assert volt_result == '+1.50000000E+00'

        # Verify log sequence
        assert len(recording_backend._command_log) == 5

        # Check each log entry
        entries = recording_backend._command_log

        # Entry 1: Query *IDN?
        assert entries[0]['type'] == 'query'
        assert entries[0]['command'] == '*IDN?'
        assert entries[0]['response'] == 'Keysight Technologies,EDU36311A,CN61130056,K-01.08.03-01.00-01.08-02.00'

        # Entry 2: Write CURR
        assert entries[1]['type'] == 'write'
        assert entries[1]['command'] == 'CURR 0.1, (@1)'
        assert 'response' not in entries[1]

        # Entry 3: Query error
        assert entries[2]['type'] == 'query'
        assert entries[2]['command'] == ':SYSTem:ERRor?'
        assert entries[2]['response'] == '+0,"No error"'

        # Entry 4: Query voltage
        assert entries[3]['type'] == 'query'
        assert entries[3]['command'] == 'MEAS:VOLT? (@1)'
        assert entries[3]['response'] == '+1.50000000E+00'

        # Entry 5: Write output
        assert entries[4]['type'] == 'write'
        assert entries[4]['command'] == 'OUTP:STAT ON, (@1)'
        assert 'response' not in entries[4]
    def test_session_file_creation(self, recording_backend, temp_output_file):
        """Test that session file is created with correct format."""
        # Record some commands
        recording_backend.query('*IDN?')
        recording_backend.write('CURR 0.1, (@1)')
        recording_backend.query(':SYSTem:ERRor?')

        # Save session
        recording_backend.save_session('keysight/EDU36311A')

        # Verify file exists and has correct content
        assert Path(temp_output_file).exists()

        with open(temp_output_file, 'r') as f:
            session_data = yaml.safe_load(f)

        # Check structure
        assert 'psu' in session_data
        assert 'profile' in session_data['psu']
        assert 'log' in session_data['psu']

        assert session_data['psu']['profile'] == 'keysight/EDU36311A'
        assert len(session_data['psu']['log']) == 3

        # Verify log entries
        log = session_data['psu']['log']
        assert log[0]['type'] == 'query'
        assert log[0]['command'] == '*IDN?'
        assert log[1]['type'] == 'write'
        assert log[1]['command'] == 'CURR 0.1, (@1)'
        assert log[2]['type'] == 'query'
        assert log[2]['command'] == ':SYSTem:ERRor?'
    def test_timestamp_ordering(self, recording_backend):
        """Test that timestamps are monotonically increasing."""
        # Record commands with small delays
        recording_backend.query('*IDN?')
        time.sleep(0.001)  # Small delay
        recording_backend.write('CURR 0.1, (@1)')
        time.sleep(0.001)
        recording_backend.query(':SYSTem:ERRor?')

        # Check timestamps
        timestamps = [entry['timestamp'] for entry in recording_backend._command_log]

        # Should be monotonically increasing
        for i in range(1, len(timestamps)):
            assert timestamps[i] > timestamps[i-1], f"Timestamp {i} ({timestamps[i]}) should be > timestamp {i-1} ({timestamps[i-1]})"
    def test_backend_error_propagation(self, temp_output_file):
        """Test that backend errors are properly propagated."""
        # Create a backend that raises exceptions
        class ErrorBackend:
            def query(self, command):
                if command == 'ERROR_CMD':
                    raise RuntimeError("Backend error")
                return "OK"

            def write(self, command):
                if command == 'ERROR_CMD':
                    raise ValueError("Write error")

        error_backend = ErrorBackend()
        recording_backend = SessionRecordingBackend(error_backend, temp_output_file, 'test')

        # Test query error propagation
        with pytest.raises(RuntimeError, match="Backend error"):
            recording_backend.query('ERROR_CMD')

        # Test write error propagation
        with pytest.raises(ValueError, match="Write error"):
            recording_backend.write('ERROR_CMD')

        # Test successful commands still work
        result = recording_backend.query('GOOD_CMD')
        assert result == "OK"
    def test_multiple_profile_keys(self, mock_backend, temp_output_file):
        """Test recording multiple instruments to same session file."""
        # Create two recording backends for different instruments
        psu_backend = SessionRecordingBackend(mock_backend, temp_output_file, 'psu')
        osc_backend = SessionRecordingBackend(mock_backend, temp_output_file, 'osc')

        # Record commands for PSU
        psu_backend.query('*IDN?')
        psu_backend.write('CURR 0.1, (@1)')
        psu_backend.save_session('keysight/EDU36311A')

        # Record commands for oscilloscope
        osc_backend.query('*IDN?')
        osc_backend.write(':CHANnel1:SCALe 1.0')
        osc_backend.save_session('keysight/DSOX1204G')

        # Verify both instruments are in the session file
        with open(temp_output_file, 'r') as f:
            session_data = yaml.safe_load(f)

        assert 'psu' in session_data
        assert 'osc' in session_data
        assert session_data['psu']['profile'] == 'keysight/EDU36311A'
        assert session_data['osc']['profile'] == 'keysight/DSOX1204G'
        assert len(session_data['psu']['log']) == 2
        assert len(session_data['osc']['log']) == 2


class TestSessionRecordingBackendEdgeCases:
    """Test edge cases and error conditions."""
    def test_empty_command_sequence(self, recording_backend, temp_output_file):
        """Test saving session with no recorded commands."""
        # Save without recording any commands
        recording_backend.save_session('test/profile')

        # Verify file structure
        with open(temp_output_file, 'r') as f:
            session_data = yaml.safe_load(f)

        assert 'psu' in session_data
        assert session_data['psu']['profile'] == 'test/profile'
        assert session_data['psu']['log'] == []
    def test_invalid_output_file_path(self, mock_backend):
        """Test error handling for invalid output file path."""
        invalid_path = '/nonexistent/directory/output.yaml'
        backend = SessionRecordingBackend(mock_backend, invalid_path, 'psu')

        # Recording should work
        backend.query('*IDN?')

        # But saving should fail gracefully
        with pytest.raises(FileNotFoundError):
            backend.save_session('test/profile')
    def test_sequential_recording(self, recording_backend):
        """Test sequential command recording."""
        def record_commands(start_index):
            for i in range(5):
                recording_backend.query(f'CMD_{start_index}_{i}?')
                recording_backend.write(f'SET_{start_index}_{i} VALUE')

        # Run recording tasks sequentially (no longer using asyncio)
        record_commands(1)
        record_commands(2)
        record_commands(3)

        # Verify all commands were recorded
        assert len(recording_backend._command_log) == 30  # 3 sequences × 5 commands × 2 (query+write)

        # Verify timestamps are still properly ordered
        timestamps = [entry['timestamp'] for entry in recording_backend._command_log]
        sorted_timestamps = sorted(timestamps)
        assert timestamps == sorted_timestamps, "Timestamps should be monotonically increasing"
def test_session_recording_backend_integration():
    """Integration test with more realistic backend behavior."""

    class RealisticMockBackend:
        """More realistic mock backend with delays and variable responses."""

        def __init__(self):
            self.voltage = 0.0
            self.current_limit = 0.1
            self.output_enabled = False

        def query(self, command):
            # Simulate some delay
            time.sleep(0.001)

            if command == '*IDN?':
                return 'Test Instruments,PSU-1000,12345,1.0.0'
            elif command == ':SYSTem:ERRor?':
                return '+0,"No error"'
            elif command.startswith('MEAS:VOLT?'):
                return f'+{self.voltage:.8E}'
            elif command.startswith('MEAS:CURR?'):
                return f'+{0.001:.8E}'  # Small current
            else:
                return 'UNKNOWN_COMMAND'

        def write(self, command):
            time.sleep(0.001)

            if 'VOLT' in command and ',(' in command:
                # Extract voltage value
                parts = command.split()
                self.voltage = float(parts[1].rstrip(','))
            elif 'CURR' in command:
                # Extract current value
                parts = command.split()
                self.current_limit = float(parts[1].rstrip(','))
            elif 'OUTP:STAT ON' in command:
                self.output_enabled = True
            elif 'OUTP:STAT OFF' in command:
                self.output_enabled = False

    # Create realistic test scenario
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        temp_file = f.name

    try:
        mock_backend = RealisticMockBackend()
        recording_backend = SessionRecordingBackend(mock_backend, temp_file, 'psu')

        # Simulate a realistic measurement sequence
        idn = recording_backend.query('*IDN?')
        assert 'Test Instruments' in idn

        recording_backend.query(':SYSTem:ERRor?')
        recording_backend.write('CURR 0.1, (@1)')
        recording_backend.write('OUTP:STAT ON, (@1)')

        # Voltage sweep
        for voltage in [1.0, 2.0, 3.0]:
            recording_backend.write(f'VOLT {voltage}, (@1)')
            measured_v = recording_backend.query('MEAS:VOLT? (@1)')
            measured_i = recording_backend.query('MEAS:CURR? (@1)')

            # Verify measurements match set values
            assert f'{voltage:.8E}' in measured_v

        recording_backend.write('OUTP:STAT OFF, (@1)')
        recording_backend.write('VOLT 0.0, (@1)')

        # Save the session
        recording_backend.save_session('test/realistic_psu')

        # Verify saved session
        with open(temp_file, 'r') as f:
            session_data = yaml.safe_load(f)

        # Should have recorded all commands
        log = session_data['psu']['log']
        assert len(log) >= 12  # At least 12 commands in the sequence

        # Verify structure
        query_count = sum(1 for entry in log if entry['type'] == 'query')
        write_count = sum(1 for entry in log if entry['type'] == 'write')

        assert query_count >= 8  # At least 8 queries
        assert write_count >= 4   # At least 4 writes

    finally:
        Path(temp_file).unlink(missing_ok=True)
