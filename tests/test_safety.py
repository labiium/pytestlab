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


@pytest.mark.skip(reason="Complex scenario, to be implemented later.")
def test_complex_safety_scenario_one():
    """Placeholder for a more complex safety test."""
    pass


@pytest.mark.skip(reason="Complex scenario, to be implemented later.")
def test_complex_safety_scenario_two():
    """Another placeholder for a complex safety test."""
    pass
