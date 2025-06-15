import pytest
from pytestlab.bench import Bench
from pytestlab.instruments.backends.sim_backend import SimBackend


def test_sim_backend_warning():
    """Verify that a warning is raised when a simulated instrument is initialized."""
    with pytest.warns(UserWarning, match="Instrument is running in simulation mode."):
        SimBackend(profile={})


@pytest.mark.asyncio
async def test_safety_wrapper_warning(tmp_path):
    """Verify that a warning is raised when an instrument is wrapped with a safety wrapper."""
    bench_yaml = """
    instruments:
      psu1:
        profile: 'keysight/E36313A'
        address: 'TCPIP0::localhost::inst0::INSTR'
        safety_limits:
          channels:
            1:
              voltage: {max: 5.0}
    """
    bench_file = tmp_path / "bench.yaml"
    bench_file.write_text(bench_yaml)

    with pytest.warns(UserWarning, match="Instrument 'psu1' is running with a safety wrapper."):
        await Bench.open(bench_file)