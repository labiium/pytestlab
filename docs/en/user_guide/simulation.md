# Simulation Mode

PyTestLab’s YAML-driven simulation backend (`SimBackend`) returns fixture-defined instrument responses without hardware. Use circuit simulation or a recorded trace when the outcome must depend on a circuit or on measured behavior.

## How Simulation Works

The behavior of a simulated instrument is defined in the `simulation` section of its profile YAML file. This section maps SCPI commands (using exact matches or regex patterns) to specific responses or state changes.

### Example: Profile with Simulation Logic

Save the following simulator fixture as `sim_supply.yaml`. It holds one
voltage setting in memory and reads it back. It is not a profile of a real
supply.

```yaml
manufacturer: example
model: SimulatedSupply
device_type: power_supply
simulation:
  initial_state:
    voltage: "0.0"
  scpi:
    "*IDN?": "Example,SimulatedSupply,SIM,1.0"
    'SET:VOLT ([-+]?[0-9]*\.?[0-9]+)':
      set:
        voltage: "$1"
    "MEAS:VOLT?":
      get: voltage
```

```python
from pytestlab.instruments.backends.sim_backend import SimBackend

sim = SimBackend("sim_supply.yaml")
try:
    sim.connect()
    sim.write("SET:VOLT 2.5")
    print(sim.query("MEAS:VOLT?"))  # 2.5
finally:
    sim.close()
```

## Enabling Simulation

There are several ways to enable simulation mode:

1. **Globally in `bench.yaml`**: Set `simulate: true` at the top level of your bench file.
2. **Per-instrument in `bench.yaml`**: Add `simulate: true` to a specific instrument's definition.
3. **In `AutoInstrument`**: Pass `simulate=True` with a profile that defines a compatible simulator.

Not every hardware profile defines simulation behaviour. PyTestLab rejects explicit
simulation if no suitable fixture is available rather than connecting to hardware.
The [simulated multimeter quickstart](getting_started.md#2-your-first-measurement-simulated)
uses a regular instrument profile with simulator behavior already defined.

## Recording a Simulation Profile

You can automatically generate a simulation profile by recording the interaction with a real instrument. This is useful for creating a high-fidelity simulation of a specific instrument's behavior.

### Step-by-Step Guide

1. **Connect to the real instrument** you want to profile.

2. **Run the `sim-profile record` command**, providing the profile key and VISA address.

    ```bash
    pytestlab sim-profile record keysight/EDU36311A --address "TCPIP0::..."
    ```

3. **Interact with the instrument** in the interactive REPL that appears. All commands and responses will be recorded. You can also point the command to a Python script to run automatically.

4. **Stop the recording** by pressing `Ctrl+D` or typing `exit()`. The recorded YAML profile will be saved to your user configuration directory (e.g., `~/.config/pytestlab/recorded_sim_profiles/`).

See the [CLI Reference](cli.md) for more `sim-profile` commands like `edit`, `reset`, and `diff`.

---

## Advanced Simulation Features

- **Stateful Simulation:** The simulation backend can maintain internal state (e.g., voltages, counters) and update it in response to commands.
- **Python Expressions:** Use `py:` or `lambda:` in responses to compute dynamic values.
- **Regex Matching:** SCPI command patterns can use regular expressions for flexible matching and parameter extraction.
- **Deterministic Testing:** Fixed responses and deterministic state transitions make tests repeatable.

---

## When to Use Simulation

- **Development:** Write and test your automation scripts without hardware.
- **Continuous Integration:** Run your test suite in CI pipelines without requiring lab instruments.
- **Education:** Teach instrument automation concepts without needing physical devices.
- **Prototyping:** Quickly prototype new measurement flows and experiment logic.

---

## Limitations

- Simulation is only as accurate as the profile and recorded logic. For high-fidelity simulation, record real instrument sessions.
- Not all edge cases or error conditions may be covered by default profiles.

---

## Further Reading

- [Creating Profiles](../profiles/creating.md)
- [Working with Benches](bench_descriptors.md)
- [Command-Line Interface Reference](cli.md)
