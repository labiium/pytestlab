"""
Tests for ReplayBackend functionality.
"""

import pytest
import asyncio
import tempfile
import yaml
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from pytestlab.instruments.backends.replay_backend import ReplayBackend, ReplayMismatchError


@pytest.fixture
def sample_session_data():
    """Sample session data for testing."""
    return {
        'psu': {
            'profile': 'keysight/EDU36311A',
            'log': [
                {
                    'type': 'query',
                    'command': '*IDN?',
                    'response': 'Keysight Technologies,EDU36311A,CN61130056,K-01.08.03-01.00-01.08-02.00',
                    'timestamp': 0.029241038020700216
                },
                {
                    'type': 'query',
                    'command': ':SYSTem:ERRor?',
                    'response': '+0,"No error"',
                    'timestamp': 0.05952404800336808
                },
                {
                    'type': 'write',
                    'command': 'CURR 0.1, (@1)',
                    'timestamp': 0.7136540680075996
                },
                {
                    'type': 'query',
                    'command': 'MEAS:VOLT? (@1)',
                    'response': '+9.99749200E-01',
                    'timestamp': 1.614894539990928
                },
            ]
        }
    }


@pytest.fixture
def temp_session_file(sample_session_data):
    """Create a temporary session file for testing."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        yaml.dump(sample_session_data, f)
        temp_file = f.name
    
    yield temp_file
    
    # Cleanup
    Path(temp_file).unlink(missing_ok=True)


@pytest.fixture
def replay_backend(temp_session_file):
    """Create a ReplayBackend instance for testing."""
    return ReplayBackend(temp_session_file, 'psu')


class TestReplayBackend:
    """Test cases for ReplayBackend."""
    
    @pytest.mark.asyncio
    async def test_initialization(self, temp_session_file, sample_session_data):
        """Test ReplayBackend initialization."""
        backend = ReplayBackend(temp_session_file, 'psu')
        
        assert backend.session_file == temp_session_file
        assert backend.profile_key == 'psu'
        assert backend.session_data == sample_session_data
        assert backend._log_index == 0
        assert len(backend._command_log) == 4
    
    @pytest.mark.asyncio
    async def test_successful_query_sequence(self, replay_backend):
        """Test successful query command sequence replay."""
        # First query - *IDN?
        result = await replay_backend.query('*IDN?')
        assert result == 'Keysight Technologies,EDU36311A,CN61130056,K-01.08.03-01.00-01.08-02.00'
        
        # Second query - :SYSTem:ERRor?
        result = await replay_backend.query(':SYSTem:ERRor?')
        assert result == '+0,"No error"'
    
    @pytest.mark.asyncio
    async def test_successful_write_command(self, replay_backend):
        """Test successful write command replay."""
        # Skip to write command
        await replay_backend.query('*IDN?')  # First query
        await replay_backend.query(':SYSTem:ERRor?')  # Second query
        
        # Write command should succeed without exception
        await replay_backend.write('CURR 0.1, (@1)')
    
    @pytest.mark.asyncio
    async def test_query_command_mismatch(self, replay_backend):
        """Test ReplayMismatchError on wrong query command."""
        with pytest.raises(ReplayMismatchError) as exc_info:
            await replay_backend.query('*TST?')  # Wrong command
        
        error = exc_info.value
        assert "Expected command '*IDN?', but got '*TST?'" in str(error)
        assert error.expected_command == '*IDN?'
        assert error.actual_command == '*TST?'
        assert error.log_index == 0
    
    @pytest.mark.asyncio
    async def test_write_command_mismatch(self, replay_backend):
        """Test ReplayMismatchError on wrong write command."""
        # Skip to write command
        await replay_backend.query('*IDN?')
        await replay_backend.query(':SYSTem:ERRor?')
        
        with pytest.raises(ReplayMismatchError) as exc_info:
            await replay_backend.write('VOLT 1.0, (@1)')  # Wrong command
        
        error = exc_info.value
        assert "Expected command 'CURR 0.1, (@1)', but got 'VOLT 1.0, (@1)'" in str(error)
    
    @pytest.mark.asyncio
    async def test_query_type_mismatch(self, replay_backend):
        """Test ReplayMismatchError when query used instead of write."""
        # Skip to write command position
        await replay_backend.query('*IDN?')
        await replay_backend.query(':SYSTem:ERRor?')
        
        with pytest.raises(ReplayMismatchError) as exc_info:
            await replay_backend.query('CURR 0.1, (@1)')  # Should be write, not query
        
        error = exc_info.value
        assert "Expected command type 'write', but got 'query'" in str(error)
    
    @pytest.mark.asyncio
    async def test_write_type_mismatch(self, replay_backend):
        """Test ReplayMismatchError when write used instead of query."""
        with pytest.raises(ReplayMismatchError) as exc_info:
            await replay_backend.write('*IDN?')  # Should be query, not write
        
        error = exc_info.value
        assert "Expected command type 'query', but got 'write'" in str(error)
    
    @pytest.mark.asyncio
    async def test_commands_exhausted(self, replay_backend):
        """Test ReplayMismatchError when all commands are exhausted."""
        # Execute all commands in sequence
        await replay_backend.query('*IDN?')
        await replay_backend.query(':SYSTem:ERRor?')
        await replay_backend.write('CURR 0.1, (@1)')
        await replay_backend.query('MEAS:VOLT? (@1)')
        
        # Try to execute one more command
        with pytest.raises(ReplayMismatchError) as exc_info:
            await replay_backend.query('*TST?')
        
        error = exc_info.value
        assert "No more commands in replay log" in str(error)
    
    @pytest.mark.asyncio
    async def test_missing_profile_key(self, temp_session_file):
        """Test error when profile key doesn't exist in session."""
        with pytest.raises(KeyError) as exc_info:
            ReplayBackend(temp_session_file, 'nonexistent_instrument')
        
        assert "'nonexistent_instrument' not found in session data" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_invalid_session_file(self):
        """Test error when session file doesn't exist."""
        with pytest.raises(FileNotFoundError):
            ReplayBackend('/nonexistent/file.yaml', 'psu')
    
    @pytest.mark.asyncio
    async def test_async_lock_behavior(self, replay_backend):
        """Test that async operations are properly locked."""
        # This test ensures thread safety in async environments
        async def concurrent_query():
            return await replay_backend.query('*IDN?')
        
        # Start concurrent operations
        tasks = [concurrent_query() for _ in range(3)]
        
        # Only one should succeed (the first one), others should fail due to sequence mismatch
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # First result should succeed
        assert results[0] == 'Keysight Technologies,EDU36311A,CN61130056,K-01.08.03-01.00-01.08-02.00'
        
        # Others should fail with ReplayMismatchError
        for result in results[1:]:
            assert isinstance(result, ReplayMismatchError)
    
    @pytest.mark.asyncio
    async def test_complete_successful_sequence(self, replay_backend):
        """Test complete successful replay sequence."""
        # Execute all commands in correct order
        idn_result = await replay_backend.query('*IDN?')
        assert idn_result == 'Keysight Technologies,EDU36311A,CN61130056,K-01.08.03-01.00-01.08-02.00'
        
        error_result = await replay_backend.query(':SYSTem:ERRor?')
        assert error_result == '+0,"No error"'
        
        await replay_backend.write('CURR 0.1, (@1)')
        
        volt_result = await replay_backend.query('MEAS:VOLT? (@1)')
        assert volt_result == '+9.99749200E-01'
        
        # Verify all commands consumed
        assert replay_backend._log_index == len(replay_backend._command_log)


@pytest.mark.asyncio
async def test_replay_mismatch_error_attributes():
    """Test ReplayMismatchError custom attributes."""
    error = ReplayMismatchError(
        message="Test error",
        expected_command="*IDN?",
        actual_command="*TST?",
        log_index=5
    )
    
    assert str(error) == "Test error"
    assert error.expected_command == "*IDN?"
    assert error.actual_command == "*TST?"
    assert error.log_index == 5


class TestReplayBackendEdgeCases:
    """Test edge cases and error conditions."""
    
    @pytest.fixture
    def empty_session_data(self):
        """Session data with empty log."""
        return {
            'psu': {
                'profile': 'keysight/EDU36311A',
                'log': []
            }
        }
    
    @pytest.fixture
    def empty_log_session_file(self, empty_session_data):
        """Create session file with empty log."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(empty_session_data, f)
            temp_file = f.name
        
        yield temp_file
        Path(temp_file).unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_empty_command_log(self, empty_log_session_file):
        """Test behavior with empty command log."""
        backend = ReplayBackend(empty_log_session_file, 'psu')
        assert len(backend._command_log) == 0
        
        # Any command should fail immediately
        with pytest.raises(ReplayMismatchError) as exc_info:
            await backend.query('*IDN?')
        
        assert "No more commands in replay log" in str(exc_info.value)
    
    @pytest.fixture
    def malformed_session_data(self):
        """Session data with malformed entries."""
        return {
            'psu': {
                'profile': 'keysight/EDU36311A',
                'log': [
                    {'type': 'query', 'command': '*IDN?'},  # Missing response
                    {'command': 'CURR 0.1, (@1)', 'timestamp': 1.0},  # Missing type
                    {'type': 'invalid_type', 'command': 'TEST'},  # Invalid type
                ]
            }
        }
    
    @pytest.fixture 
    def malformed_session_file(self, malformed_session_data):
        """Create session file with malformed data."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(malformed_session_data, f)
            temp_file = f.name
        
        yield temp_file
        Path(temp_file).unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_malformed_log_entries(self, malformed_session_file):
        """Test handling of malformed log entries."""
        backend = ReplayBackend(malformed_session_file, 'psu')
        
        # First entry missing response - should handle gracefully
        result = await backend.query('*IDN?')
        assert result == ""  # Should return empty string for missing response
        
        # Second entry missing type - should cause error
        with pytest.raises((KeyError, ReplayMismatchError)):
            await backend.write('CURR 0.1, (@1)')
