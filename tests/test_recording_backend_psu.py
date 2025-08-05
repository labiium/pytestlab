import os
from pathlib import Path
import yaml
import pytest
from pytestlab.instruments import AutoInstrument
from pytestlab.instruments.backends.recording_backend import RecordingBackend
def test_recording_backend_psu(tmp_path):
    # Set up output path for the simulation profile
    sim_profile_path = tmp_path / "psu_sim.yaml"

    # Instantiate the PSU instrument (simulate mode for test safety)
    psu = AutoInstrument.from_config("keysight/EDU36311A", simulate=True)
    psu.connect_backend()

    # Wrap the backend with RecordingBackend (use _backend)
    recording_backend = RecordingBackend(psu._backend, str(sim_profile_path))
    psu._backend = recording_backend

    # Perform some basic operations
    idn = psu.id()
    psu.set_voltage(1, 1.5)
    psu.set_current(1, 0.1)
    psu.output(1, True)
    psu.output(1, False)

    # Close the instrument (should trigger profile write)
    psu.close()

    # Check that the simulation profile file was created
    assert sim_profile_path.exists(), f"Simulation profile not created at {sim_profile_path}"

    # Load and check the YAML contents
    with open(sim_profile_path) as f:
        data = yaml.safe_load(f)
    assert "simulation" in data, "Simulation key missing in profile YAML"
    assert "scpi" in data["simulation"], "SCPI section missing in simulation profile"
    assert isinstance(data["simulation"]["scpi"], dict), "SCPI section should be a dict"

    # Check for expected SCPI commands
    scpi_commands = data["simulation"]["scpi"]
    assert "*IDN?" in scpi_commands, "Missing *IDN? command in SCPI profile"
    assert "VOLT 1.5, (@1)" in scpi_commands, "Missing voltage set command in SCPI profile"
    assert "CURR 0.1, (@1)" in scpi_commands, "Missing current set command in SCPI profile"
    assert "OUTP:STAT ON, (@1)" in scpi_commands, "Missing output on command in SCPI profile"
    assert "OUTP:STAT OFF, (@1)" in scpi_commands, "Missing output off command in SCPI profile"
