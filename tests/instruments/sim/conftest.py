# tests/instruments/sim/conftest.py
import pytest
from pathlib import Path
from pytestlab.instruments import AutoInstrument, Oscilloscope

@pytest.fixture(scope="module")
async def sim_scope() -> Oscilloscope:
    """
    Provides a module-scoped, simulated Oscilloscope instance.

    This fixture loads the custom simulation profile `DSOX1204G_sim.yaml`
    and initializes the oscilloscope driver with the `SimBackendV2`.
    The connection is established once and torn down after all tests in the
    module have run, making the test suite efficient.
    """
    # Construct the path to the simulation profile relative to this file
    sim_profile_path = Path(__file__).parent / "DSOX1204G_sim.yaml"

    # Instantiate the instrument using the simulation profile
    # `simulate=True` ensures SimBackendV2 is used.
    # The profile path is passed via the `config_source` argument.
    scope = await AutoInstrument.from_config(
        config_source=str(sim_profile_path),
        simulate=True
    )
    
    # Establish the "connection" to the backend
    await scope.connect_backend()

    # Yield the instrument to the tests
    yield scope

    # Teardown: close the connection after tests are complete
    await scope.close()