"""
Tests for AutoInstrument backend_override functionality.
"""

import pytest
import tempfile
import yaml
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

from pytestlab.instruments.AutoInstrument import AutoInstrument
from pytestlab.instruments.backends.replay_backend import ReplayBackend


@pytest.fixture
def sample_instrument_profile():
    """Sample instrument profile for testing."""
    return {
        'device_type': 'power_supply',
        'manufacturer': 'Keysight',
        'model': 'EDU36311A',
        'channels': [
            {
                'channel_id': 1,
                'description': 'Channel 1',
                'voltage_range': {
                    'min_val': 0,
                    'max_val': 30.0
                },
                'current_limit_range': {
                    'min_val': 0,
                    'max_val': 5.0
                },
                'accuracy': {
                    'voltage': 0.05,
                    'current': 0.2
                }
            }
        ],
        'total_power': 90,
        'line_regulation': 0.01,
        'load_regulation': 0.01,
        'scpi': {
            'commands': {
                'set_voltage': {
                    'template': 'VOLT {voltage}, (@{channel})',
                    'defaults': {'channel': 1},
                    'validators': {'voltage': {'min': 0, 'max': 30}, 'channel': {'min': 1, 'max': 3}}
                }
            },
            'queries': {
                'identify': {
                    'template': '*IDN?',
                    'response': {'type': 'str'}
                }
            }
        }
    }


@pytest.fixture
def temp_profile_file(sample_instrument_profile):
    """Create temporary profile file."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        yaml.dump(sample_instrument_profile, f)
        profile_file = f.name

    yield profile_file

    Path(profile_file).unlink(missing_ok=True)


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
                    'timestamp': 0.029
                }
            ]
        }
    }


@pytest.fixture
def temp_session_file(sample_session_data):
    """Create temporary session file."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        yaml.dump(sample_session_data, f)
        session_file = f.name

    yield session_file

    Path(session_file).unlink(missing_ok=True)


class MockBackend:
    """Mock backend for testing."""

    def __init__(self, name="mock"):
        self.name = name
        self.queries = []
        self.writes = []

    def query(self, command):
        self.queries.append(command)
        return f"MOCK_RESPONSE_{command}"

    def write(self, command):
        self.writes.append(command)


class TestAutoInstrumentBackendOverride:
    """Test cases for AutoInstrument backend_override functionality."""

    def test_from_config_without_backend_override(self, temp_profile_file):
        """Test normal AutoInstrument.from_config without backend override."""
        config = {
            'profile': temp_profile_file,
            'address': 'USB0::0x2A8D::0x3102::CN61130056::INSTR'
        }

        # Test normal AutoInstrument.from_config without backend override
        # This should work with simulation backends
        instrument = AutoInstrument.from_config(config, simulate=True)
        assert instrument is not None
        assert instrument._backend is not None

    def test_from_config_with_backend_override(self, temp_profile_file):
        """Test AutoInstrument.from_config with backend_override."""
        config = {
            'profile': temp_profile_file,
            'address': 'USB0::0x2A8D::0x3102::CN61130056::INSTR'
        }

        # Create mock backend
        mock_backend = MockBackend("test_backend")

        # Test with backend override
        instrument = AutoInstrument.from_config(config, backend_override=mock_backend)

        # Verify the backend was set correctly
        assert instrument._backend is mock_backend
        assert instrument._backend.name == "test_backend"

    def test_from_config_with_replay_backend_override(self, temp_profile_file, temp_session_file):
        """Test AutoInstrument.from_config with ReplayBackend override."""
        config = {
            'profile': temp_profile_file,
            'address': 'USB0::0x2A8D::0x3102::CN61130056::INSTR'
        }

        # Create ReplayBackend
        replay_backend = ReplayBackend(temp_session_file, 'psu')

        # Test with ReplayBackend override
        instrument = AutoInstrument.from_config(config, backend_override=replay_backend)

        # Verify the backend was set correctly
        assert instrument._backend is replay_backend
        assert isinstance(instrument._backend, ReplayBackend)

    def test_backend_override_takes_precedence(self, temp_profile_file):
        """Test that backend_override takes precedence over profile backend settings."""
        # Create profile with specific backend configuration
        profile_with_backend = {
            'device_type': 'power_supply',
            'manufacturer': 'Keysight',
            'model': 'EDU36311A',
            'channels': [
                {
                    'channel_id': 1,
                    'description': 'Channel 1',
                    'voltage_range': {
                        'min_val': 0,
                        'max_val': 30.0
                    },
                    'current_limit_range': {
                        'min_val': 0,
                        'max_val': 5.0
                    },
                    'accuracy': {
                        'voltage': 0.05,
                        'current': 0.2
                    }
                }
            ],
            'total_power': 90,
            'line_regulation': 0.01,
            'load_regulation': 0.01,
            'scpi': {
                'commands': {
                    'set_voltage': {
                        'template': 'VOLT {voltage}, (@{channel})',
                        'defaults': {'channel': 1},
                        'validators': {'voltage': {'min': 0, 'max': 30}, 'channel': {'min': 1, 'max': 3}}
                    }
                },
                'queries': {
                    'identify': {
                        'template': '*IDN?',
                        'response': {'type': 'str'}
                    }
                }
            }
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(profile_with_backend, f)
            profile_file = f.name

        try:
            config = {
                'profile': profile_file,
                'address': 'USB0::0x2A8D::0x3102::CN61130056::INSTR'
            }

            # Create override backend
            override_backend = MockBackend("override")

            # Create instrument with override
            instrument = AutoInstrument.from_config(config, backend_override=override_backend)

            # Verify override backend is used, not the one from profile
            assert instrument._backend is override_backend
            assert instrument._backend.name == "override"

        finally:
            Path(profile_file).unlink(missing_ok=True)
    def test_instrument_methods_with_backend_override(self, temp_profile_file):
        """Test that instrument methods work with backend override."""
        config = {
            'profile': temp_profile_file,
            'address': 'USB0::0x2A8D::0x3102::CN61130056::INSTR'
        }

        # Create mock backend with specific responses
        mock_backend = MockBackend("functional_test")

        # Create instrument with backend override
        instrument = AutoInstrument.from_config(config, backend_override=mock_backend)

        # Test query method
        result = instrument._backend.query('*IDN?')
        assert result == "MOCK_RESPONSE_*IDN?"
        assert '*IDN?' in mock_backend.queries

        # Test write method
        instrument._backend.write('CURR 0.1')
        assert 'CURR 0.1' in mock_backend.writes
    def test_replay_backend_integration(self, temp_profile_file, temp_session_file):
        """Test complete integration with ReplayBackend."""
        config = {
            'profile': temp_profile_file,
            'address': 'USB0::0x2A8D::0x3102::CN61130056::INSTR'
        }

        # Create ReplayBackend
        replay_backend = ReplayBackend(temp_session_file, 'psu')

        # Create instrument with ReplayBackend
        instrument = AutoInstrument.from_config(config, backend_override=replay_backend)

        # Test that replay works through the instrument
        result = instrument._backend.query('*IDN?')
        expected = 'Keysight Technologies,EDU36311A,CN61130056,K-01.08.03-01.00-01.08-02.00'
        assert result == expected

        # Verify replay backend state
        assert replay_backend._step == 1

    def test_backend_override_none(self, temp_profile_file):
        """Test that backend_override=None works like no override."""
        config = {
            'profile': temp_profile_file,
            'address': 'USB0::0x2A8D::0x3102::CN61130056::INSTR'
        }

        # Test with None override (should behave like normal)
        # This should work with simulation backends
        instrument = AutoInstrument.from_config(config, backend_override=None, simulate=True)
        assert instrument is not None
        assert instrument._backend is not None


class TestBackendOverrideEdgeCases:
    """Test edge cases for backend override functionality."""

    def test_invalid_backend_override(self, temp_profile_file):
        """Test behavior with invalid backend override."""
        config = {
            'profile': temp_profile_file,
            'address': 'USB0::0x2A8D::0x3102::CN61130056::INSTR'
        }

        # Test with invalid backend (not implementing required protocol)
        invalid_backend = "not_a_backend"

        instrument = AutoInstrument.from_config(config, backend_override=invalid_backend)

        # The backend should be set, but using it will fail
        assert instrument._backend == "not_a_backend"

    def test_backend_override_with_missing_profile(self):
        """Test backend override with missing profile file."""
        config = {
            'profile': '/nonexistent/profile.yaml',
            'address': 'USB0::0x2A8D::0x3102::CN61130056::INSTR'
        }

        mock_backend = MockBackend("test")

        # Should raise FileNotFoundError regardless of backend override
        with pytest.raises(FileNotFoundError):
            AutoInstrument.from_config(config, backend_override=mock_backend)

    def test_multiple_instruments_same_backend_override(self, temp_profile_file):
        """Test using same backend override for multiple instruments."""
        config = {
            'profile': temp_profile_file,
            'address': 'USB0::0x2A8D::0x3102::CN61130056::INSTR'
        }

        # Create single backend to share
        shared_backend = MockBackend("shared")

        # Create multiple instruments with same backend
        instrument1 = AutoInstrument.from_config(config, backend_override=shared_backend)
        instrument2 = AutoInstrument.from_config(config, backend_override=shared_backend)

        # Both should reference the same backend
        assert instrument1._backend is shared_backend
        assert instrument2._backend is shared_backend
        assert instrument1._backend is instrument2._backend
    def test_backend_override_state_isolation(self, temp_profile_file):
        """Test that different backend instances maintain separate state."""
        config = {
            'profile': temp_profile_file,
            'address': 'USB0::0x2A8D::0x3102::CN61130056::INSTR'
        }

        # Create separate backend instances
        backend1 = MockBackend("backend1")
        backend2 = MockBackend("backend2")

        # Create instruments with different backends
        instrument1 = AutoInstrument.from_config(config, backend_override=backend1)
        instrument2 = AutoInstrument.from_config(config, backend_override=backend2)

        # Use both instruments
        instrument1._backend.query('CMD1')
        instrument2._backend.query('CMD2')
        instrument1._backend.write('WRITE1')
        instrument2._backend.write('WRITE2')

        # Verify separate state
        assert backend1.queries == ['CMD1']
        assert backend2.queries == ['CMD2']
        assert backend1.writes == ['WRITE1']
        assert backend2.writes == ['WRITE2']
def test_backend_override_with_session_recording():
    """Test backend override with SessionRecordingBackend."""
    from pytestlab.instruments.backends.session_recording_backend import SessionRecordingBackend

    # Create mock underlying backend
    mock_backend = MockBackend("recorded")

    # Create temporary session file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        session_file = f.name

    try:
        # Create SessionRecordingBackend
        recording_backend = SessionRecordingBackend(mock_backend, session_file)

        # Create temporary profile
        profile = {
            'device_type': 'power_supply',
            'manufacturer': 'Test',
            'model': 'TEST001',
            'channels': [
                {
                    'channel_id': 1,
                    'description': 'Channel 1',
                    'voltage_range': {
                        'min_val': 0,
                        'max_val': 30.0
                    },
                    'current_limit_range': {
                        'min_val': 0,
                        'max_val': 5.0
                    }
                }
            ],
            'scpi': {
                'commands': {
                    'set_voltage': {
                        'template': 'VOLT {voltage}, (@{channel})',
                        'defaults': {'channel': 1}
                    }
                },
                'queries': {
                    'identify': {
                        'template': '*IDN?',
                        'response': {'type': 'str'}
                    }
                }
            }
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(profile, f)
            profile_file = f.name

        try:
            config = {
                'profile': profile_file,
                'address': 'TEST::123'
            }

            # Create instrument with recording backend
            instrument = AutoInstrument.from_config(config, backend_override=recording_backend)

            # Use the instrument
            result = instrument._backend.query('*IDN?')
            instrument._backend.write('TEST:CMD 1')

            # Verify recording
            assert result == "MOCK_RESPONSE_*IDN?"
            assert len(recording_backend._command_log) == 2
            assert recording_backend._command_log[0]['command'] == '*IDN?'
            assert recording_backend._command_log[1]['command'] == 'TEST:CMD 1'

            # Verify underlying backend was called
            assert '*IDN?' in mock_backend.queries
            assert 'TEST:CMD 1' in mock_backend.writes

        finally:
            Path(profile_file).unlink(missing_ok=True)

    finally:
        Path(session_file).unlink(missing_ok=True)
