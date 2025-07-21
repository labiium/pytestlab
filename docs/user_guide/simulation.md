# Simulation Mode

Using PyTestLab in simulation mode allows you to develop and test When simulation is enabled for an instrument with this profile, the `SimBackend` will automatically respond to commands based on the `simulation` entries.our code without needing to connect to physical instruments. This is useful for writing tests, developing new features, and running CI/CD pipelines.

## Enabling Simulation Mode

You can enable simulation mode by setting the `simulation` flag to `True` in your bench configuration file.

```yaml
instruments:
  - type: "power_supply"
    id: "psu1"
    simulation: True
```

## YAML-Driven Simulation

PyTestLab uses a powerful YAML-driven simulation backend that provides realistic simulation behavior through instrument profiles. The simulation behavior is defined declaratively in the `simulation` section of the instrument's profile YAML file.

### Example: Profile with Simulation

```yaml
# In your instrument profile (e.g., profiles/keysight/DSOX1204G.yaml)
simulation:
  scpi:
    "*IDN?": "Keysight Technologies,DSOX1204G,SIM12345,1.0"
    ":TIMebase:SCALe?": "lambda: state.get('timebase_scale', 1e-3)"
    ":TIMebase:SCALe (.+)":
      action: "set"
      target: "timebase_scale"  
      value: "float(groups[0])"
    ":MEASure:VOLTage:DC?": "lambda: random.uniform(4.95, 5.05)"
  state:
    timebase_scale: 1e-3
    voltage_offset: 0.0
```

### Creating Custom Simulation Profiles

For testing, you can create temporary simulation profiles:

```python
import pytest
import yaml
from pathlib import Path
from pytestlab.instruments import AutoInstrument

@pytest.fixture
def custom_dmm_profile(tmp_path: Path) -> str:
    """Create a custom simulation profile for testing."""
    profile_content = {
        "device_type": "multimeter",
        "model": "TestDMM",
        "simulation": {
            "scpi": {
                "*IDN?": "PyTestLab,TestDMM,SIM001,1.0",
                ":MEASure:VOLTage:DC?": "5.001",
                ":MEASure:CURRent:DC?": "0.1",
            }
        }
    }
    profile_path = tmp_path / "test_dmm.yaml"
    with open(profile_path, "w") as f:
        yaml.dump(profile_content, f)
    return str(profile_path)

async def test_custom_simulation(custom_dmm_profile):
    """Test using a custom simulation profile."""
    dmm = AutoInstrument.from_config(custom_dmm_profile, simulate=True)
    await dmm.connect_backend()
    
    # The simulated instrument will respond as defined in the YAML
    voltage = await dmm.query(":MEASure:VOLTage:DC?")
    assert voltage == "5.001"
    
    await dmm.close()
```
  - command: "*IDN?"
    response: "Keysight Technologies,DSOX1204G,MY57233199,02.42.2018082300"
  - command: "WAV:SOUR?"
    response: "CHAN1"
  - command: "WAV:FORM?"
    response: "WORD"
```

When simulation is enabled for an instrument with this profile, `SimBackend` will automatically respond to commands based on the `simulation` entries.

## How to Record a Simulation Profile

You can automatically generate a simulation profile by recording the interaction with a real instrument. This is useful for creating a high-fidelity simulation of a specific instrument's behavior.

### Step-by-Step Guide

1.  **Connect to the real instrument** you want to profile.

2.  **Run the `pytestlab sim-profile record` command:**

    ```bash
    pytestlab sim-profile record <instrument_name>
    ```

    Replace `<instrument_name>` with the name of the instrument as defined in your `bench.yaml`.

3.  **Interact with the instrument** through your tests or application code. All commands and responses will be recorded.

4.  **Stop the recording** by pressing `Ctrl+C`. The recorded profile will be saved to a user-specific location.

## Managing User-Specific Profiles

PyTestLab provides commands to manage your recorded simulation profiles.

### `edit`

Opens the user-specific profile for the specified instrument in your default text editor.

```bash
pytestlab sim-profile edit <instrument_name>
```

### `reset`

Deletes the user-specific profile, reverting to the default profile.

```bash
pytestlab sim-profile reset <instrument_name>
```

### `diff`

Shows the differences between the user-specific profile and the default profile.

```bash
pytestlab sim-profile diff <instrument_name>
```