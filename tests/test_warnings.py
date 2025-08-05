import pytest
import tempfile
import yaml
from pathlib import Path
from pytestlab.bench import Bench
from pytestlab.instruments.backends.sim_backend import SimBackend


def test_sim_backend_initialization():
    """Verify that a simulated instrument can be initialized without warnings."""
    # Create a minimal profile file for SimBackend
    profile_data = {
        'simulation': {
            'scpi': {
                '*IDN?': 'Test,Instrument,123,1.0'
            }
        }
    }

    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        yaml.dump(profile_data, f)
        profile_path = f.name

    try:
        # Should initialize without warnings
        backend = SimBackend(profile_path)
        assert backend is not None
        backend.close()
    finally:
        Path(profile_path).unlink(missing_ok=True)
