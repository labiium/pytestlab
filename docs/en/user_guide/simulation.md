# Simulation Mode

PyTestLab features a powerful, YAML-driven simulation backend (`SimBackend`) that provides realistic and deterministic behavior for your instruments.

## How Simulation Works

The behavior of a simulated instrument is defined in the `simulation` section of its profile YAML file. This section maps SCPI commands (using exact matches or regex patterns) to specific responses or state changes.

### Example: Profile with Simulation Logic

```yaml title="pytestlab/profiles/pytestlab/virtual_instrument.yaml"
manufacturer: PyTestLab
model: Virtual-Instrument-1
device_type: virtual_instrument

simulation:
  initial_state:
    voltage: 0.0
    current: 0.0
    counter: 0

  scpi:
    # Simple query with a static response
    "*IDN?": "PyTestLab,Virtual-Instrument-1,0,1.0"

    # Command that changes state using regex capture group ($1)
    "SET:VOLT ([-+]?[0-9]*\\.?[0-9]+)":
      set:
        voltage: "py:float(g1)" # Use a python expression to cast

    # Query that retrieves a value from the state
    "MEAS:VOLT?":
      get: "voltage"

    # Command with state manipulation
    "COUNT:INC":
      inc:
        counter: 1

    # Query with a dynamic Python lambda expression
    "DYNAMIC:RAND?":
      response: "lambda: str(random.randint(1, 100))"
```

## Enabling Simulation

There are several ways to enable simulation mode:

1. **Globally in `bench.yaml`**: Set `simulate: true` at the top level of your bench file.
2. **Per-instrument in `bench.yaml`**: Add `simulate: true` to a specific instrument's definition.
3. **In `AutoInstrument`**: Pass `simulate=True` when creating an instrument instance.
    ```python
    import pytestlab
    scope = pytestlab.AutoInstrument.from_config("keysight/DSOX1204G", simulate=True)
    scope.connect_backend()
    ```

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
- **Deterministic Testing:** Simulation ensures repeatable results for CI/CD and development.

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