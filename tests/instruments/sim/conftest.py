# tests/instruments/sim/conftest.py
import pytest
from pathlib import Path
from pytestlab.instruments import AutoInstrument, Oscilloscope

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
    # Use the local simulation profile with custom configuration
    # `simulate=True` ensures SimBackend is used
    sim_profile_path = Path(__file__).parent / "keysight" / "DSOX1204G.yaml"
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
