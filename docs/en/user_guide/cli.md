# Command-Line Interface

PyTestLab includes a powerful command-line interface (CLI) built with [Typer](https://typer.tiangolo.com/) for managing profiles, instruments, and benches. You can access it via the `pytestlab` command.

---

## General Usage

To see all available commands and sub-commands, use the `--help` flag:

```bash
pytestlab --help
```

---

## Profile Management (`pytestlab profile`)

Commands for inspecting and validating instrument profiles.

### `list`

Lists all available built-in instrument profiles.

```bash
pytestlab profile list
```

### `show`

Displays the contents of a specific profile YAML file.

```bash
pytestlab profile show keysight/DSOX1204G
```

### `validate`

Validates one or more profiles against their Pydantic models to ensure they are well-formed.

```bash
pytestlab profile validate path/to/my_custom_profiles/
```

---

## Bench Management (`pytestlab bench`)

Commands for working with `bench.yaml` files.

### `ls`

Lists the instruments defined in a bench configuration file.

```bash
pytestlab bench ls path/to/bench.yaml
```

### `validate`

Validates the structure of a `bench.yaml` file and checks that all specified profiles can be loaded.

```bash
pytestlab bench validate path/to/bench.yaml
```

### `id`

Connects to all non-simulated instruments in a bench and queries their `*IDN?` string.

```bash
pytestlab bench id path/to/bench.yaml
```

### `sim`

Converts an existing `bench.yaml` file into a new one configured entirely for simulation mode.

```bash
# Print the simulated config to the console
pytestlab bench sim path/to/bench.yaml

# Save the simulated config to a new file
pytestlab bench sim path/to/bench.yaml --output-path bench.sim.yaml
```

For more details on simulation, see the [Simulation Guide](simulation.md).

---

## Simulation Profile Tools (`pytestlab sim-profile`)

Commands for recording, editing, and managing simulation profiles.

### `record`

Interactively record a simulation profile by proxying commands to a real instrument and saving the responses.

```bash
pytestlab sim-profile record keysight/EDU36311A --address "TCPIP0::..."
```

### `edit`

Opens the user-specific simulation profile for the specified instrument in your default text editor.

```bash
pytestlab sim-profile edit keysight/EDU36311A
```

### `reset`

Deletes the user-specific simulation profile, reverting to the default profile.

```bash
pytestlab sim-profile reset keysight/EDU36311A
```

### `diff`

Shows the differences between the user-specific simulation profile and the default profile.

```bash
pytestlab sim-profile diff keysight/EDU36311A
```

---

## Other Useful Commands

- `pytestlab --version`  
  Print the installed version of PyTestLab.

- `pytestlab profile list`  
  List all available instrument profiles.

- `pytestlab bench validate`  
  Validate your bench configuration before running experiments.

---

## Tips

- Use `pytestlab --help` and `pytestlab <subcommand> --help` for detailed usage and options.
- The CLI is ideal for quick validation, automation, and scripting in CI/CD pipelines.
- For advanced scripting, combine CLI commands with Python scripts using the PyTestLab API.

---

For more information, see the [User Guide](getting_started.md) and the [Simulation Guide](simulation.md).