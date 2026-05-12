# Command‑Line Interface (CLI)

PyTestLab ships with a comprehensive command‑line interface built with [Typer](https://typer.tiangolo.com/). It helps you explore profiles, validate configs, interact with instruments, manage benches, and capture or replay sessions — all from your terminal.

You invoke it via the `ptl` command (installed through the package’s console script).

---

## Quick Start

Show global help and version:

```bash
ptl --help
ptl --version
```

Each command and subcommand also supports `--help`:

```bash
ptl profile --help
ptl bench validate --help
```

---

## Top‑Level Commands

### `ptl run`
Execute a measurement script against a bench configuration.

```bash
ptl run path/to/script.py --bench path/to/bench.yaml [--simulate] [--output results.yaml]
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

### `ptl list`
List available resources: `profiles`, `benches`, or `examples`.

```bash
ptl list profiles
ptl list benches
ptl list examples
```

---

## Profile Management (`ptl profile`)

Explore, validate, and inspect instrument profile schemas.

### `list`
List all built‑in instrument profiles by key (e.g., `keysight/EDU34450A`).

```bash
ptl profile list
```

### `show`
Display a profile by key or by direct path.

```bash
ptl profile show keysight/DSOX1204G
ptl profile show path/to/custom.yaml
```

### `validate`
Validate one profile file or every YAML file in a directory against PyTestLab’s Pydantic models.

```bash
# Validate all YAMLs in a directory
ptl profile validate path/to/my_profiles/

# Validate a single file
ptl profile validate path/to/profile.yaml
```

### `schema`
Output the JSON Schema for a given instrument type.

```bash
ptl profile schema oscilloscope
ptl profile schema power_supply --output osc_schema.json
ptl profile schema multimeter --no-format
```

### `schema-info`
Show high‑level information about a schema without printing the entire JSON.

```bash
ptl profile schema-info waveform_generator
```

### `validate-schema`
Validate a profile YAML against an explicit schema (or auto‑detected from the YAML).

```bash
ptl profile validate-schema path/to/profile.yaml
ptl profile validate-schema path/to/profile.yaml --instrument-type oscilloscope
```

### `list-schemas`
List supported instrument types and common aliases.

```bash
ptl profile list-schemas
```

---

## Instrument Utilities (`ptl instrument`)

Quick checks and targeted tests for instrument drivers.

### `idn`
Connect to an instrument and print its `*IDN?` response.

```bash
# Use a built‑in profile key
ptl instrument idn keysight/EDU34450A --address USB0::0x2A8D::0x0101::MY12345678::INSTR

# Or run in simulation mode
ptl instrument idn keysight/EDU34450A --simulate
```

Options:
- `--address`: VISA address to override the profile.
- `--simulate`: Use simulation backend instead of real hardware.

### `verify-profile`
Verify that a real instrument actually adheres to a profile YAML, not just that the YAML is schema-valid.

The verifier prints a colored terminal report with schema, connection, identity, SCPI, and instrument-specific checks. By default it avoids state-changing probes and does not run health checks that may clear an instrument error queue. Health checks and generic SCPI query smoke tests are only enabled in `safe-write` mode. Setter-style and output-affecting checks stay disabled unless you explicitly allow them.

```bash
# Conservative default: no state-changing probes
ptl instrument verify-profile keysight/EDU34450A --address USB0::...::INSTR

# Allow health checks and SCPI query smoke tests
ptl instrument verify-profile keysight/EDU36311A --address USB0::...::INSTR --probe-mode safe-write

# Allow setter-style and output-affecting checks where supported
ptl instrument verify-profile keysight/EDU33212A --address USB0::...::INSTR --probe-mode safe-write --allow-output-enable
```

Options:
- `--address`: VISA address to override the profile.
- `--probe-mode`: `read-only` or `safe-write`. `safe-write` may reapply current settings and may clear error queues through health checks.
- `--allow-output-enable`: Permit setter-style and output-affecting checks for devices such as PSUs and AWGs.
- `--timeout-ms`: Override the backend communication timeout.
- `--fail-fast`: Stop after the first failed verification check.

### `test`
Run selected real‑hardware tests against a profile (skips gracefully if hardware is absent). This command overrides test module constants to target your selected profile.

```bash
# kind: multimeter | psu | oscilloscope | awg | all
ptl instrument test multimeter keysight/EDU34450A
ptl instrument test all keysight/EDU34450A
```

---

## Bench Management (`ptl bench`)

Work with `bench.yaml` descriptors that define multiple instruments.

### `ls`
List the instruments and effective backend settings referenced in a bench file.

```bash
ptl bench ls path/to/bench.yaml
```

### `validate`
Validate the bench descriptor and verify that referenced profiles can be loaded.

```bash
ptl bench validate path/to/bench.yaml
```

### `id`
Connect to all non‑simulated instruments in the bench and query their `*IDN?` strings.

```bash
ptl bench id path/to/bench.yaml
```

### `sim`
Convert a bench descriptor to a fully simulated one. Prints to stdout or writes a file.

```bash
# Print simulated descriptor
ptl bench sim path/to/bench.yaml

# Save simulated descriptor
ptl bench sim path/to/bench.yaml --output bench.sim.yaml
```

For background on simulation mode, see the [Simulation Guide](simulation.md).

---

## Simulation Profile Tools (`ptl sim-profile`)

Create, inspect, and manage simulation profile overrides.

User paths used by these commands:
- Overrides: `~/.config/pytestlab/profiles/<vendor>/<model>.yaml`
- Recorded: `~/.config/pytestlab/recorded_sim_profiles/<vendor>/<model>.yaml`

### `record`
Record instrument interactions and create a simulation profile. You can run a script (with `main(instrument)`) or interactively use a REPL. When no `--output-path` is provided, files are saved under the user cache path above.

```bash
# Record from real hardware
ptl sim-profile record keysight/EDU36311A --address TCPIP0::192.168.1.50::INSTR

# Record using simulation (useful for demos)
ptl sim-profile record keysight/EDU36311A --simulate --output-path sim_profile.yaml

# Drive recording via a script
ptl sim-profile record keysight/EDU36311A --address USB0::... --script scripts/exercise_psu.py
```

Options:
- `--address`: VISA address (required for real instruments).
- `--output-path`: Where to write the YAML profile.
- `--script`: Python script to execute, expected to expose `main(instrument)`.
- `--simulate`: Use a simulated instrument as the source.

### `edit`
Open the user override profile in your default editor, creating it from the official profile if missing.

```bash
ptl sim-profile edit keysight/EDU36311A
```

### `reset`
Delete the user override profile to revert to the official one.

```bash
ptl sim-profile reset keysight/EDU36311A
```

### `diff`
Show a unified diff between the user override and the official profile.

```bash
ptl sim-profile diff keysight/EDU36311A
```

---

## Record & Replay Sessions (`ptl replay`)

Capture multi‑instrument sessions and replay them deterministically.

### `record`
Wrap each instrument backend to log I/O while your script runs against a real bench.

```bash
ptl replay record scripts/run_measurement.py \
  --bench benches/bench.yaml \
  --output sessions/2025‑05‑12.yaml
```

Your script must define `main(bench)`.

### `run`
Replay a previously recorded session using a simulated bench.

```bash
ptl replay run scripts/run_measurement.py --session sessions/2025‑05‑12.yaml
```

---

## Tips, Env Vars, and Exit Codes

- `--help` works at every level: `ptl <cmd> [subcmd] --help`.
- Many commands return non‑zero exit codes on validation or runtime errors (useful for CI).
- Environment variable `PYTESTLAB_SIMULATE=true` can influence default simulation mode within the Python API; many CLI commands also offer explicit `--simulate` flags for clarity.
- VISA addresses typically look like `USB0::...::INSTR` or `TCPIP0::host::INSTR`.

---

## Handy One‑Liners

```bash
# Explore built‑in profiles
ptl profile list

# Peek at an official profile
ptl profile show keysight/EDU36311A

# Validate all your custom profiles
ptl profile validate my_profiles/

# Sanity‑check a bench
ptl bench validate bench.yaml

# Force an existing bench to run simulated
ptl run scripts/sweep.py --bench bench.yaml --simulate

# Get a device IDN fast
ptl instrument idn keysight/EDU34450A --address USB0::...::INSTR

# Capture a session, then replay it later
ptl replay record scripts/test.py --bench bench.yaml --output run.yaml
ptl replay run scripts/test.py --session run.yaml
```

---

For more, see:
- Getting Started: [getting_started.md](getting_started.md)
- Simulation Mode: [simulation.md](simulation.md)
- Record & Replay: [replay_mode.md](replay_mode.md)
