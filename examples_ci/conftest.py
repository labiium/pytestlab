# examples_ci/conftest.py
import pytest
import yaml
from pathlib import Path

@pytest.fixture
def simulated_dmm_profile(tmp_path: Path) -> str:
    """
    Creates a temporary YAML profile for a simulated DMM that provides
    a predictable response for the sweep test.
    """
    profile_content = {
        "device_type": "multimeter",
        "model": "SimDMMCI",
        "simulation": {
            "scpi": {
                "*IDN?": "PyTestLab,SimulatedDMM-CI,1.0",
                ":MEASure:VOLTage:DC?": "5.001",
            }
        }
    }
    profile_path = tmp_path / "sim_dmm_ci.yaml"
    with open(profile_path, "w") as f:
        yaml.dump(profile_content, f)
    return str(profile_path)

@pytest.fixture  
def simulated_psu_profile(tmp_path: Path) -> str:
    """
    Creates a temporary YAML profile for a simulated PSU for CI testing.
    """
    profile_content = {
        "device_type": "power_supply",
        "model": "SimPSUCI", 
        "channels": [{"channel_id": 1}],
        "simulation": {
            "scpi": {
                "*IDN?": "PyTestLab,SimulatedPSU-CI,1.0",
                ":OUTP1:STAT ON": "",  # Write commands can have empty responses
                ":SOUR1:VOLT 5.0": ""
            }
        }
    }
    profile_path = tmp_path / "sim_psu_ci.yaml" 
    with open(profile_path, "w") as f:
        yaml.dump(profile_content, f)
    return str(profile_path)
