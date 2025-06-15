# Simulation Mode

Using PyTestLab in simulation mode allows you to develop and test your code without needing to connect to physical instruments. This is useful for writing tests, developing new features, and running CI/CD pipelines.

## Enabling Simulation Mode

You can enable simulation mode by setting the `simulation` flag to `True` in your bench configuration file.

```yaml
instruments:
  - type: "power_supply"
    id: "psu1"
    simulation: True
```

## Custom Scripted Responses

The simulation backend supports custom scripted responses, allowing you to define specific return values for commands. This is particularly useful for testing how your code reacts to different instrument responses.

You can set a custom response using the `set_sim_response` method on the simulation backend.

### Example

Here's an example of how to use `set_sim_response` in a test:

```python
import pytest
from pytestlab import PowerSupply

@pytest.fixture
def simulated_psu():
    psu = PowerSupply(simulation=True)
    yield psu
    psu.disconnect()

def test_custom_idn_response(simulated_psu):
    # Get the simulation backend
    backend = simulated_psu.get_backend()

    # Set a custom response for the *IDN? query
    custom_idn = "MyCustomInstrument,Model-X,SN12345,FW-1.0"
    backend.set_sim_response("*IDN?", custom_idn)

    # Verify that the instrument returns the custom response
    assert simulated_psu.query("*IDN?") == custom_idn
```

In this example, we create a simulated `PowerSupply` and then get its backend. We use `set_sim_response` to specify that any time the `*IDN?` command is sent to the instrument, it should return our custom string. The test then verifies that this is the case.

## YAML-Driven Simulation (SimBackendV2)

PyTestLab also offers a more powerful YAML-driven simulation backend, `SimBackendV2`. This backend uses instrument profiles to provide realistic simulation behavior without requiring you to script every response.

The simulation behavior is defined in the `simulation` section of the instrument's profile YAML file.

### Example: Profile with Simulation

```yaml
# In your instrument profile (e.g., profiles/keysight/DSOX1204G.yaml)
simulation:
  - command: "*IDN?"
    response: "Keysight Technologies,DSOX1204G,MY57233199,02.42.2018082300"
  - command: "WAV:SOUR?"
    response: "CHAN1"
  - command: "WAV:FORM?"
    response: "WORD"
```

When simulation is enabled for an instrument with this profile, `SimBackendV2` will automatically respond to commands based on the `simulation` entries.

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