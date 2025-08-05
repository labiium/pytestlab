# pytestlab/tests/test_safety.py

import pytest
import yaml
import tempfile
from pathlib import Path
from pytestlab.instruments import PowerSupply
from pytestlab.bench import SafetyLimitError
from pytestlab.config.loader import load_profile


@pytest.fixture
def psu_config():
    """Create a temporary profile file for the power supply."""
    profile = {
        'device_type': 'power_supply',
        'manufacturer': 'Keysight',
        'model': 'EDU36311A',
        'channels': [
            {
                'channel_id': 1,
                'description': 'Channel 1',
                'voltage_range': {'min_val': 0, 'max_val': 6},
                'current_limit_range': {'min_val': 0, 'max_val': 5},
                'accuracy': {'voltage': 0.05, 'current': 0.2}
            }
        ],
        'scpi': {
            '*IDN?': 'dummy_idn'
        }
    }
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        yaml.dump(profile, f)
        profile_file = f.name

    yield {
        'profile': profile_file,
        'address': 'USB0::0x2A8D::0x3102::CN61130056::INSTR'
    }

    Path(profile_file).unlink(missing_ok=True)


@pytest.fixture
def psu(psu_config):
    """A power supply with a simulated backend."""
    config = load_profile(psu_config['profile'])
    return PowerSupply(config=config, backend="sim")


def test_apply_safety_limits(psu):
    """Verify that safety limits are correctly applied to instruments."""
    psu.voltage_limit = 5.0
    psu.current_limit = 1.0
    assert psu.voltage_limit == 5.0
    assert psu.current_limit == 1.0


def test_safety_limit_exceeded(psu):
    """Ensure that a SafetyLimitError is raised when a safety limit is exceeded."""
    psu.voltage_limit = 5.0
    with pytest.raises(SafetyLimitError):
        psu.voltage = 6.0


def test_complex_safety_scenario_one(psu):
    """Test multiple safety limit interactions and cascading effects."""
    # Set initial limits
    psu.voltage_limit = 4.0
    psu.current_limit = 2.0

    # Test that setting voltage within limits works
    psu.voltage = 3.5
    assert psu.voltage == 3.5

    # Test that reducing voltage limit below current setting raises error
    with pytest.raises(SafetyLimitError):
        psu.voltage_limit = 3.0  # Below current voltage of 3.5

    # Test that current limit enforcement works
    with pytest.raises(SafetyLimitError):
        psu.current = 2.5  # Above current limit of 2.0


def test_complex_safety_scenario_two(psu):
    """Test safety limit persistence and validation edge cases."""
    # Test setting limits at boundary values
    psu.voltage_limit = 6.0  # Max allowed from profile
    psu.current_limit = 5.0  # Max allowed from profile

    # Test that setting voltage at the limit works
    psu.voltage = 6.0
    assert psu.voltage == 6.0

    # Test that exceeding by small amount still raises error
    with pytest.raises(SafetyLimitError):
        psu.voltage = 6.001

    # Test that negative limits are rejected
    with pytest.raises(SafetyLimitError):
        psu.voltage_limit = -1.0

    with pytest.raises(SafetyLimitError):
        psu.current_limit = -0.5
