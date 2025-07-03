import asyncio
import os
from pathlib import Path
import yaml
import pytest
from pytestlab.instruments import AutoInstrument
from pytestlab.instruments.backends.recording_backend import RecordingBackend

@pytest.mark.asyncio
async def test_recording_backend_psu(tmp_path):
    # Set up output path for the simulation profile
    sim_profile_path = tmp_path / "psu_sim.yaml"

    # Instantiate the PSU instrument (simulate mode for test safety)
    psu = await AutoInstrument.from_config("keysight/EDU36311A", simulate=True)
    await psu.connect_backend()

    # Wrap the backend with RecordingBackend (use _backend)
    recording_backend = RecordingBackend(psu._backend, str(sim_profile_path))
    psu._backend = recording_backend

    # Perform some basic operations
    idn = await psu.id()
    await psu.set_voltage(1, 1.5)
    await psu.set_current(1, 0.1)
    await psu.output(1, True)
    await psu.output(1, False)

    # Close the instrument (should trigger profile write)
    await psu.close()

    # Check that the simulation profile file was created
    assert sim_profile_path.exists(), f"Simulation profile not created at {sim_profile_path}"

    # Load and check the YAML contents
    with open(sim_profile_path) as f:
        data = yaml.safe_load(f)
    assert "simulation" in data, "Simulation key missing in profile YAML"
    assert isinstance(data["simulation"], list), "Simulation log should be a list"
    assert any(entry.get("type") == "query" for entry in data["simulation"]), "No query entries in simulation log"
    assert any(entry.get("type") == "write" for entry in data["simulation"]), "No write entries in simulation log"
