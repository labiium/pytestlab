"""
Shared pytest fixtures for the PyTestLab test suite.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest

from pytestlab import AutoInstrument
from pytestlab.instruments.instrument import Instrument


@pytest.fixture(autouse=True)
def _patch_autoinstrument(monkeypatch):
    """
    Auto-Instrument stub – always returns a dummy to avoid VISA calls.
    """
    monkeypatch.setattr(
        "pytestlab.instruments.AutoInstrument.__init__",
        lambda *a, **k: None,
    )
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
def sim_scope() -> Generator[Instrument[Any], None, None]:
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
    scope = AutoInstrument.from_config(config_source=str(sim_profile_path), simulate=True)

    # Establish the "connection" to the backend
    scope.connect_backend()

    # Yield the instrument to the tests
    yield scope

    # Teardown: close the connection after tests are complete
    scope.close()
