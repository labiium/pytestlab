# Command‑Line Interface (CLI)

PyTestLab ships with a comprehensive command‑line interface built with [Typer](https://typer.tiangolo.com/). It helps you explore profiles, validate configs, interact with instruments, manage benches, and capture or replay sessions — all from your terminal.

Start with the [simulated meter walkthrough](../cli.md#check-your-bench), or use the [command index](#command-index). Hardware is optional.

---

## Quick Start

Show global help and version:

```bash
ptl --help
ptl --version
```

Use group help to browse commands, or request help for a specific bench operation:

```bash
ptl profile --help
ptl bench validate --help
```

---

## Command index

| Prefix | Available commands |
| --- | --- |
| `ptl` | `run`, `list` |
| `ptl bench` | `id`, `ls`, `measurement`, `measurements`, `route`, `routes`, `sim`, `validate` |
| `ptl camera` | `capture`, `discover`, `info`, `list` |
| `ptl device` | `idn`, `status-byte` |
| `ptl evidence` | `check`, `generate`, `hardware-parity`, `scope-oracle`, `scope-twin` |
| `ptl instrument` | `check-commands`, `check-operation-contract`, `describe-operation`, `execute-operation`, `full-test`, `idn`, `list-operations`, `list-options`, `test`, `verify-profile` |
| `ptl lamb` | `list`, `verify-scopes` |
| `ptl motion` | `position`, `move`, `status` |
| `ptl prober` | `contact`, `separate` |
| `ptl profile` | `list`, `list-schemas`, `schema`, `schema-info`, `show`, `validate`, `validate-schema` |
| `ptl replay` | `record`, `run` |
| `ptl sim` | `doctor`, `install-ngspice` |
| `ptl sim-profile` | `diff`, `edit`, `record`, `reset` |
| `ptl twin` | `characterize-scope`, `check`, `oracle`, `residual-from-replay` |
| `ptl visa` | `list` |

## Top‑Level Commands

### `ptl run`
Execute a measurement script against a bench configuration.

```bash
ptl run read_voltage.py --bench bench.yaml --simulate --output reading.yaml
```

- `--bench`: Path to the bench descriptor YAML.
- `--simulate` (0.3.0): Force a supported built-in simulator for every configured device, even if an entry sets `simulate: false`. The command rejects hooks, unsupported devices, and custom backends before loading the measurement script. This does not sandbox Python. Run only trusted scripts and simulator inputs. In 0.2.4, per-device settings could override this flag; do not rely on it to prevent live I/O.
- `--output`: Optional path to write the script’s return value (YAML or string).

Common pattern with a `main(bench)` function inside your script:

```python
def main(bench):
    # access a configured alias, e.g. bench.dmm
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
ptl profile validate-schema path/to/profile.yaml --device-type oscilloscope
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

# Inspect identity-query options
ptl instrument idn --help
```

Options:
- `--address`: VISA address to override the profile.
- `--simulate`: Use simulation backend instead of real hardware.

### `verify-profile`
Verify that a real instrument actually adheres to a profile YAML, not just that the YAML is schema-valid.

The report covers schema, connection, identity, SCPI, and device-specific checks. Default `read-only` mode skips explicit health checks and query smoke tests; routine driver queries can still consume error entries. `safe-write` adds those probes. Setter-style and output-affecting checks require a separate opt-in.

```bash
# Default: skip explicit health and smoke probes
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

---

### `test`
Run the source checkout's driver-specific real-hardware pytest suite. The profile's validated `device_type` selects the suite; the tests are not included in installed wheels.

```bash
ptl instrument test keysight/EDU34450A
ptl instrument test keysight/EDU36311A

# Legacy kind/profile syntax remains accepted when the kind matches the profile.
ptl instrument test psu keysight/EDU36311A
```

### Semantic operation discovery

These commands inspect local/package profile metadata without creating a
simulator, opening an instrument backend, or sending a query. Selectable values
are accepted directly by the corresponding Python methods.

```bash
ptl instrument list-operations keysight/EDU34450A --supported-only
ptl instrument list-operations keysight/EDU34450A --grouped --supported-only
ptl instrument describe-operation keysight/EDU34450A measure
ptl instrument list-options keysight/EDU34450A measure function
ptl instrument list-options keysight/EDU34450A measure range_val \
  --context '{"function":"dc_voltage"}'
```

**JSON is the default output**, for both results and errors. A capable interactive
terminal gets syntax highlighting; redirected or piped output is plain JSON with
no ANSI codes. Highlighting does not reflow long strings or interpret JSON string
contents as terminal markup. Unicode units are printed directly.

There is no format-selection flag. Set `NO_COLOR` to disable highlighting.

Use `--include-unsupported` to inspect disabled choices and their reasons.
`--context` must be a JSON object; dependent parameters such as a DMM
range require their function context. Invalid profiles, operations, parameters,
contexts, or unresolved metadata exit with status 1 and a structured JSON error
on stdout. Diagnostics remain on stderr.

`list-operations` returns IDs by default. `--grouped` returns complete
operation descriptions keyed by semantic group. `--group GROUP` and
`--scope family|model` filter this grouped view. `--supported-only` limits
either view to operations supported by the loaded profile.

Python applications use `list_operations()`, `describe_operations()`,
`describe_operation()`, and `list_operation_options()` directly on the
instrument; they do not need to invoke the CLI or parse JSON.

### Execute a declared operation

```bash
ptl instrument execute-operation keysight/EDU34450A measure \
  --params '{"function":"dc_voltage"}' --backend visa --address "$DMM_RESOURCE"
```

This optional hardware example takes a real reading. Set `DMM_RESOURCE` to the meter’s VISA address. If `describe-operation` reports `python_only`, call the typed Python method; the CLI will not run it.

### Instrument validation

`check-commands` builds mappings offline. `full-test` reports mappings,
live reads, and skips separately. Bench mode uses the selected alias and its
limits. Profile/address mode can send eligible single queries. Custom profiles
stay offline. Queries may acquire data or consume diagnostic entries.

`--include-writes` requests guarded writes; none currently qualify. Raw
writes, resets, triggers, and output enables are not sampled. EDU36311A reads
are measured values checked against upper and absolute caps, not setpoint
verification or proof of DUT safety. PSU setpoints are not changed.

```bash
ptl instrument check-commands keysight/EDU34450A
ptl instrument full-test psu --bench bench.yaml

ptl instrument full-test keysight/EDU34450A --address "$DMM_RESOURCE"
```

These are explicit profile-development and hardware-validation workflows. They
do not change the semantic Python API or require application code to know the
underlying transport syntax.

---

## VISA Discovery (`ptl visa`)

Find VISA resource strings before adding instruments to a script or `bench.yaml`.

### `list`
List resources visible to PyVISA.

```bash
ptl visa list
```

Probe each discovered resource with `*IDN?` to identify which instrument is which:

```bash
ptl visa list --idn
```

Copy the resource string into `bench.yaml`:

```yaml
instruments:
  scope:
    profile: "keysight/MXR404A"
    address: "TCPIP0::192.168.0.42::inst0::INSTR"
```

Options:
- `--idn`: Query `*IDN?` for each discovered resource.
- `--timeout-ms`: Timeout for `--idn` probes.

## Bench Management (`ptl bench`)

Work with `bench.yaml` descriptors that define multiple instruments.

### `ls`
List the aliases and declared bindings in the bench without opening hardware. An undeclared address is not a simulation indicator. Use `ptl bench ls --json` for a machine-readable inventory; it does not verify that a configured device is connected or ready.

```bash
ptl bench ls
```

### `validate`
Validate the descriptor and its profile and measurement-plan references. Use ordinary validation only with trusted profiles and extensions. Add `--strict` for offline checks of built-in profiles, custom validation rules, required device addresses, and declared routes. Strict mode does not import third-party drivers or configuration models, open hardware, or run hooks. Profiles that need those extensions are rejected in strict mode. Neither form verifies hardware readiness. Both `ls` and `validate` accept a positional path or `--bench PATH`. With neither, they use `PYTESTLAB_BENCH` or the nearest `bench.yaml`/`bench.yml`.

```bash
ptl bench validate
```

### Inspect routes and measurements

`ptl bench routes FILE` and `ptl bench measurements FILE` list named declarations. Pass a name to `ptl bench route FILE NAME` or `ptl bench measurement FILE NAME` to inspect its connections, device, and accessories before applying a route or acquiring data. Try the [worked route inspection](../cli.md#inspect-a-measurement-plan).

### `id`
Open the bench and query the identity of non-simulated instruments. This is a live operation, but it skips bench hooks and startup resets. For offline inventory, use `ptl bench ls`.

```bash
ptl bench id path/to/bench.yaml
```

### `sim`
Export a simulation-only descriptor (0.3.0). Uses the same eligibility checks as `ptl run --simulate` and rejects a bench it cannot fully simulate. Input paths are resolved against the original descriptor, so the export contains local file references.

```bash
# Print simulated descriptor
ptl bench sim path/to/bench.yaml

# Save simulated descriptor
ptl bench sim path/to/bench.yaml --output-path bench.sim.yaml
```

For background on simulation mode, see the [Simulation Guide](simulation.md).

---

## Camera, motion, and prober commands

The default bench is resolved from `--bench PATH`, `PYTESTLAB_BENCH`, or a nearby `bench.yaml`/`bench.yml`.

### Cameras

```bash
ptl camera list --json
ptl camera info microscope
ptl camera capture microscope /tmp/view.jpg
ptl camera capture microscope /tmp/series --count 5 --interval 0.5
```

A configured camera needs its exact bench `address`. List and info inspect configured resources. Capture requires an explicit alias. Omitting it or providing an unknown alias does not select another camera. A valid capture opens the configured resource and writes image files, plus metadata sidecars by default. See [Using a camera or microscope](using_camera_microscope.md).

### Motion

```bash
ptl motion position stage
ptl motion status stage
ptl motion move --help
```

`position` and `status` query the configured alias. Add `--json` for scripts. `move` can actuate hardware; confirm axis units, travel, interlocks, and target alias first. Earlier root-level motion routes remain callable for compatibility.

### Probers

```bash
ptl motion position prober
ptl motion status prober
ptl prober contact --help
ptl prober separate --help
```

Position and status connect to the selected controller. Contact and separation can physically move the station. Profile-declared readbacks are required to confirm contact or settling. See [Using a prober](using_prober.md) for PA200 limits and commissioning commands.

### Device identity and status

`ptl device idn PROFILE --address RESOURCE` reads the selected device's identity. `ptl device status-byte ALIAS --bench FILE --json` reads its native status byte and returns decimal and hexadecimal values.

### Circuit simulation

```bash
ptl sim doctor
```

Doctor checks the circuit-simulation dependencies. `ptl sim install-ngspice` detects a package manager and can run a user-space install with confirmation; for system managers it prints the install command. Review `ptl sim install-ngspice --help` before using it.

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

## Validation evidence and digital twins

| Command | Input and result |
| --- | --- |
| `evidence generate` / `evidence check` | Write a validation bundle to `--output DIR`; verify an existing directory against the current repository. |
| `evidence scope-twin` / `evidence scope-oracle` / `twin oracle` | Generate the software oscilloscope oracle bundle. Use `--check` to validate the generated artifacts. |
| `evidence hardware-parity` | Compare a hardware replay fixture against expected measurements, using the chosen coverage factor. |
| `twin residual-from-replay` | Convert a hardware replay fixture JSON into `twin_residual_report.json`. |
| `twin characterize-scope` | Turn an eligible passing residual report into characterized scope evidence. |
| `twin check` | Validate the payload hash and claims of a residual or twin evidence JSON file. |

See the [CLI evidence walkthrough](../cli.md#generate-validation-evidence) for command sequences.

## Tips, Env Vars, and Exit Codes

- Bench-aware station commands resolve `--bench`, then `PYTESTLAB_BENCH`, then the nearest `bench.yaml` or `bench.yml`. An explicit invalid path is an error.
- Operation discovery returns JSON on stdout. When a dependent option is missing, supply `--context` as one quoted JSON object and check the process exit status.

- Use group help for replay and simulation-profile recording: `ptl replay --help` and `ptl sim-profile --help`.
- Many commands return non‑zero exit codes on validation or runtime errors (useful for CI).
- For standalone Python instrument construction, `PYTESTLAB_SIMULATE=true` can set the default. It is not a blanket prohibition on live I/O. Use a simulation-only bench or `ptl run --simulate` to require supported built-in simulation.
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
