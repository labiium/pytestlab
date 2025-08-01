"""
Shared pytest fixtures for the PyTestLab test suite.
"""
from __future__ import annotations

import builtins
import types
from pathlib import Path

import numpy as np
import pytest

import pytestlab.measurements.session as msession
from pytestlab.instruments import AutoInstrument, Oscilloscope


class _DummyInstrument:
    """Tiny mock that records the last command but does nothing."""
    def __init__(self):  # noqa: D401
        self._closed = False

    def close(self):  # noqa: D401
        self._closed = True

    # generic fall-back: any attr access returns a lambda that swallows args
    def __getattr__(self, item):
        return lambda *a, **k: None


@pytest.fixture(autouse=True)
def _patch_autoinstrument(monkeypatch):
    """
    Auto-Instrument stub – always returns a dummy to avoid VISA calls.
    """
    monkeypatch.setattr(msession, "AutoInstrument", types.SimpleNamespace(from_config=lambda *a, **k: _DummyInstrument()))
    yield


@pytest.fixture()
def tmp_db_file(tmp_path: Path) -> Path:
    """Provides a temporary database file path."""
    return tmp_path / "test_db.db"


@pytest.fixture()
def simple_experiment():
    """Creates a simple experiment for testing."""
    from pytestlab.experiments import Experiment

    exp = Experiment("TestExp", "desc")
    exp.add_parameter("x", "-", "")
    exp.add_trial({"x": [1, 2, 3], "y": [4, 5, 6]})
    return exp


@pytest.fixture(scope="module")
def sim_scope() -> Oscilloscope:
    """
    Provides a module-scoped, simulated Oscilloscope instance.

    This fixture loads the custom simulation profile `DSOX1204G_sim.yaml`
    and initializes the oscilloscope driver with the `SimBackend`.
    The connection is established once and torn down after all tests in the
    module have run, making the test suite efficient.
    """
    # Construct the path to the simulation profile relative to this file
    sim_profile_path = Path(__file__).parent / "instruments" / "sim" / "DSOX1204G_sim.yaml"

    # Instantiate the instrument using the simulation profile
    # `simulate=True` ensures SimBackend is used.
    # The profile path is passed via the `config_source` argument.
    scope = AutoInstrument.from_config(
        config_source=str(sim_profile_path),
        simulate=True
    )

    # Establish the "connection" to the backend
    scope.connect_backend()

    # Yield the instrument to the tests
    yield scope

    # Teardown: close the connection after tests are complete
    scope.close()


@pytest.fixture()
def temp_profile_file(tmp_path):
    """Creates a temporary instrument profile file for testing."""
    import yaml

    profile_data = {
        'info': {
            'manufacturer': 'Test',
            'model': 'TEST001',
            'type': 'test_instrument'
        },
        'connection': {
            'interface': 'visa',
            'address_template': 'USB0::0x2A8D::0x3102::{serial}::INSTR'
        }
    }

    profile_file = tmp_path / "test_profile.yaml"
    with open(profile_file, 'w') as f:
        yaml.dump(profile_data, f)

    return profile_file


@pytest.fixture()
def temp_session_file(tmp_path):
    """Creates a temporary session file for replay testing."""
    import yaml

    session_data = {
        'psu': {
            'profile': 'keysight/EDU36311A',
            'log': [
                {'type': 'query', 'command': '*IDN?', 'response': 'Keysight Technologies,EDU36311A,CN61130056,K-01.08.03-01.00-01.08-02.00', 'timestamp': 0.1},
                {'type': 'query', 'command': ':SYSTem:ERRor?', 'response': '+0,"No error"', 'timestamp': 0.2},
                {'type': 'write', 'command': 'CURR 0.1, (@1)', 'timestamp': 0.3},
                {'type': 'query', 'command': 'MEAS:VOLT? (@1)', 'response': '+9.99749200E-01', 'timestamp': 0.4}
            ]
        }
    }

    session_file = tmp_path / "test_session.yaml"
    with open(session_file, 'w') as f:
        yaml.dump(session_data, f)

    return session_file
