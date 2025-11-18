# Command‑Line Interface (CLI)

PyTestLab ships with a comprehensive command‑line interface built with [Typer](https://typer.tiangolo.com/). It helps you explore profiles, validate configs, interact with instruments, manage benches, and capture or replay sessions — all from your terminal.

You invoke it via the `pytestlab` command (installed through the package’s console script).

---

## Quick Start

Show global help and version:

```bash
pytestlab --help
pytestlab --version
```

Each command and subcommand also supports `--help`:

```bash
pytestlab profile --help
pytestlab bench validate --help
```

---

## Top‑Level Commands

### `pytestlab run`
Execute a measurement script against a bench configuration.

```bash
pytestlab run path/to/script.py --bench path/to/bench.yaml [--simulate] [--output results.yaml]
```

- `--bench`: Path to the bench descriptor YAML.
- `--simulate`: Force simulation mode even if bench is real.
- `--output`: Optional path to write the script’s return value (YAML or string).

Common pattern with a `main(bench)` function inside your script:

```python
def main(bench):
    # use bench.instruments[...] here
    return {"ok": True}
```

### `pytestlab list`
List available resources: `profiles`, `benches`, or `examples`.

```bash
pytestlab list profiles
pytestlab list benches
pytestlab list examples
```

---

## Profile Management (`pytestlab profile`)

Explore, validate, and inspect instrument profile schemas.

### `list`
List all built‑in instrument profiles by key (e.g., `keysight/EDU34450A`).

```bash
pytestlab profile list
```

### `show`
Display a profile by key or by direct path.

```bash
pytestlab profile show keysight/DSOX1204G
pytestlab profile show path/to/custom.yaml
```

### `validate`
Validate one profile file or every YAML file in a directory against PyTestLab’s Pydantic models.

```bash
# Validate all YAMLs in a directory
pytestlab profile validate path/to/my_profiles/

# Validate a single file
pytestlab profile validate path/to/profile.yaml
```

### `schema`
Output the JSON Schema for a given instrument type.

```bash
pytestlab profile schema oscilloscope
pytestlab profile schema power_supply --output osc_schema.json
pytestlab profile schema multimeter --no-format
```

### `schema-info`
Show high‑level information about a schema without printing the entire JSON.

```bash
pytestlab profile schema-info waveform_generator
```

### `validate-schema`
Validate a profile YAML against an explicit schema (or auto‑detected from the YAML).

```bash
pytestlab profile validate-schema path/to/profile.yaml
pytestlab profile validate-schema path/to/profile.yaml --instrument-type oscilloscope
```

### `list-schemas`
List supported instrument types and common aliases.

```bash
pytestlab profile list-schemas
```

---

## Instrument Utilities (`pytestlab instrument`)

Quick checks and targeted tests for instrument drivers.

### `idn`
Connect to an instrument and print its `*IDN?` response.

```bash
# Use a built‑in profile key
pytestlab instrument idn keysight/EDU34450A --address USB0::0x2A8D::0x0101::MY12345678::INSTR

# Or run in simulation mode
pytestlab instrument idn keysight/EDU34450A --simulate
```

Options:
- `--address`: VISA address to override the profile.
- `--simulate`: Use simulation backend instead of real hardware.

### `test`
Run selected real‑hardware tests against a profile (skips gracefully if hardware is absent). This command overrides test module constants to target your selected profile.

```bash
# kind: multimeter | psu | oscilloscope | awg | all
pytestlab instrument test multimeter keysight/EDU34450A
pytestlab instrument test all keysight/EDU34450A
```

---

## Bench Management (`pytestlab bench`)

Work with `bench.yaml` descriptors that define multiple instruments.

### `ls`
List the instruments and effective backend settings referenced in a bench file.

```bash
pytestlab bench ls path/to/bench.yaml
```

### `validate`
Validate the bench descriptor and verify that referenced profiles can be loaded.

```bash
pytestlab bench validate path/to/bench.yaml
```

### `id`
Connect to all non‑simulated instruments in the bench and query their `*IDN?` strings.

```bash
pytestlab bench id path/to/bench.yaml
```

### `sim`
Convert a bench descriptor to a fully simulated one. Prints to stdout or writes a file.

```bash
# Print simulated descriptor
pytestlab bench sim path/to/bench.yaml

# Save simulated descriptor
pytestlab bench sim path/to/bench.yaml --output bench.sim.yaml
```

For background on simulation mode, see the [Simulation Guide](simulation.md).

---

## Simulation Profile Tools (`pytestlab sim-profile`)

Create, inspect, and manage simulation profile overrides.

User paths used by these commands:
- Overrides: `~/.config/pytestlab/profiles/<vendor>/<model>.yaml`
- Recorded: `~/.config/pytestlab/recorded_sim_profiles/<vendor>/<model>.yaml`

### `record`
Record instrument interactions and create a simulation profile. You can run a script (with `main(instrument)`) or interactively use a REPL. When no `--output-path` is provided, files are saved under the user cache path above.

```bash
# Record from real hardware
pytestlab sim-profile record keysight/EDU36311A --address TCPIP0::192.168.1.50::INSTR

# Record using simulation (useful for demos)
pytestlab sim-profile record keysight/EDU36311A --simulate --output-path sim_profile.yaml

# Drive recording via a script
pytestlab sim-profile record keysight/EDU36311A --address USB0::... --script scripts/exercise_psu.py
```

Options:
- `--address`: VISA address (required for real instruments).
- `--output-path`: Where to write the YAML profile.
- `--script`: Python script to execute, expected to expose `main(instrument)`.
- `--simulate`: Use a simulated instrument as the source.

### `edit`
Open the user override profile in your default editor, creating it from the official profile if missing.

```bash
pytestlab sim-profile edit keysight/EDU36311A
```

### `reset`
Delete the user override profile to revert to the official one.

```bash
pytestlab sim-profile reset keysight/EDU36311A
```

### `diff`
Show a unified diff between the user override and the official profile.

```bash
pytestlab sim-profile diff keysight/EDU36311A
```

---

## Record & Replay Sessions (`pytestlab replay`)

Capture multi‑instrument sessions and replay them deterministically.

### `record`
Wrap each instrument backend to log I/O while your script runs against a real bench.

```bash
pytestlab replay record scripts/run_measurement.py \
  --bench benches/bench.yaml \
  --output sessions/2025‑05‑12.yaml
```

Your script must define `main(bench)`.

### `run`
Replay a previously recorded session using a simulated bench.

```bash
pytestlab replay run scripts/run_measurement.py --session sessions/2025‑05‑12.yaml
```

---

## Tips, Env Vars, and Exit Codes

- `--help` works at every level: `pytestlab <cmd> [subcmd] --help`.
- Many commands return non‑zero exit codes on validation or runtime errors (useful for CI).
- Environment variable `PYTESTLAB_SIMULATE=true` can influence default simulation mode within the Python API; many CLI commands also offer explicit `--simulate` flags for clarity.
- VISA addresses typically look like `USB0::...::INSTR` or `TCPIP0::host::INSTR`.

---

## Handy One‑Liners

```bash
# Explore built‑in profiles
pytestlab profile list

# Peek at an official profile
pytestlab profile show keysight/EDU36311A

# Validate all your custom profiles
pytestlab profile validate my_profiles/

# Sanity‑check a bench
pytestlab bench validate bench.yaml

# Force an existing bench to run simulated
pytestlab run scripts/sweep.py --bench bench.yaml --simulate

# Get a device IDN fast
pytestlab instrument idn keysight/EDU34450A --address USB0::...::INSTR

# Capture a session, then replay it later
pytestlab replay record scripts/test.py --bench bench.yaml --output run.yaml
pytestlab replay run scripts/test.py --session run.yaml
```

---

For more, see:
- Getting Started: [getting_started.md](getting_started.md)
- Simulation Mode: [simulation.md](simulation.md)
- Record & Replay: [replay_mode.md](replay_mode.md)
