# CLI

Install [PyTestLab](installation.md) to get the `ptl` command. Start with a simulated Keysight 34470A multimeter: validate the bench and take a DC voltage reading without connecting an instrument. The bench alias `dmm` lets the same script work on another bench.

| What do you have? | Start here |
| --- | --- |
| A first run without hardware | [Take a first reading](#find-an-instrument-profile) |
| A model number and a measurement you want to make | [Discover operations and valid settings](#discover-operations-and-valid-settings) |
| A bench with named routes and measurements | [Inspect a measurement plan](#inspect-a-measurement-plan) |
| A connected instrument (optional) | [Discover station resources](#discover-station-resources) |
| A station with a camera or moving axes | [Inspect and operate bench devices](#work-with-cameras-and-positioners) |
| A script you want to reproduce | [Record and replay its I/O](#record-and-replay-a-measurement-session) |
| A validation bundle or hardware capture fixture | [Check evidence and digital twins](#generate-validation-evidence) |

## Find an instrument profile

```bash
ptl --version
ptl profile list
ptl profile show keysight/34470A
```

The profile key identifies a driver and its model-specific settings. In this case the profile also defines simulated responses. Run `ptl profile --help` to see the other profile commands.

## Check your bench

Save the [minimal bench.yaml](bench-yaml.md#start-with-one-simulated-meter) in your working directory. It assigns the alias `dmm` to that multimeter. From the same directory, run:

```bash
ptl bench validate bench.yaml --strict
ptl bench ls bench.yaml
```

Validation checks the file and its profile references. Use strict mode for an offline check of profiles, declared rules, required device addresses, and routes. Strict mode does not import third-party device plugins, construct drivers, connect to devices, or run bench hooks. Profiles that name a custom driver or configuration model are rejected in strict mode; use ordinary validation only with trusted profiles and extensions. Strict validation does not verify hardware availability or readiness. The listing should include an instrument named `dmm` with profile `keysight/34470A`.

## Run a measurement

Save this as `read_voltage.py` alongside the bench file. The CLI opens the bench and passes it to `main`.

```python
def main(bench):
    reading = bench.dmm.measure("dc_voltage", uncertainty=False)
    return {"reading": float(reading), "unit": reading.units}
```

```bash
ptl run read_voltage.py --bench bench.yaml --simulate --output reading.yaml
```

Open `reading.yaml` for the simulated reading and its unit. Keep the alias `dmm` when reusing the script with another bench. For physical instruments, configure the appropriate [hardware backend](installation.md#visa-backend-support) separately.

## Discover operations and valid settings

Suppose you need a fixed DC voltage range. Start with the meter profile from the walkthrough. These commands read local metadata and produce JSON:

```bash
ptl instrument list-operations keysight/34470A --supported-only
ptl instrument describe-operation keysight/34470A measure
ptl instrument list-options keysight/34470A measure function
ptl instrument list-options keysight/34470A measure range_val \
  --context '{"function":"dc_voltage"}'
```

`describe-operation` tells you which parameters the operation accepts. For `measure`, the available ranges depend on the selected function. In the final command, look at each record’s `value` and `unit`: the packaged profile includes `"AUTO"` and numeric voltage ranges such as `0.1`. Pass the chosen value to `bench.dmm.measure("dc_voltage", range_val=0.1)`. Add `--include-unsupported` to `list-options` when investigating a missing choice.

On a connected station, `execute-operation` invokes a declared operation directly. This example **takes a live reading**. Set `DMM_RESOURCE` to the meter’s actual local VISA resource first.

```bash
ptl instrument execute-operation keysight/34470A measure \
  --backend visa --address "$DMM_RESOURCE" \
  --params '{"function":"dc_voltage","range_val":0.1}'
```

Live operations can change device state. Use the typed Python method for [Python-only operations](user_guide/cli.md#execute-a-declared-operation). Profile-required `--safety-context` accepts a JSON object.

## Qualify a profile

| Question | Command | What it checks |
| --- | --- | --- |
| Is my YAML valid for this instrument type? | `ptl profile validate-schema my_meter.yaml --device-type multimeter` | File contents against the schema. Use `ptl profile list-schemas` to find supported types. |
| Can the profile build its command mappings? | `ptl instrument check-commands keysight/34470A` | Command construction, offline. |
| Does the profile provide the aliases and parameter metadata its driver needs? | `ptl instrument check-operation-contract keysight/34470A --check-parameters --strict` | Driver contract against the loaded profile. Strict mode gives automation a failing exit status for contract failures. |
| Does a connected instrument implement the profile? | `ptl instrument verify-profile keysight/34470A --address "$DMM_RESOURCE"` | Identity and profile checks, without explicit health probes by default. Routine queries may consume errors. |

`ptl instrument full-test` [checks mappings and eligible live reads](user_guide/cli.md#instrument-validation).

## Inspect a measurement plan

A bench can give a measurement a name and bind it to an instrument, route, and accessories. In a source checkout, the included `examples/auditable_bench.yaml` declares an input-ripple measurement through a scope probe:

```bash
ptl bench validate examples/auditable_bench.yaml --strict
ptl bench routes examples/auditable_bench.yaml
ptl bench route examples/auditable_bench.yaml scope_ch1_to_dut_input
ptl bench measurements examples/auditable_bench.yaml
ptl bench measurement examples/auditable_bench.yaml input_ripple_vpp
```

Use the plural commands to find names, then the singular commands to inspect one declaration. For this example, check that the target is channel 1, the quantity is peak-to-peak voltage, and the accessory is `vin_probe`. Inspection leaves the switch and instruments untouched. The [bench descriptor guide](user_guide/bench_descriptors.md) shows how to run the synthetic measurement and explains when an active switch route needs explicit application.

## Discover station resources

If you are connecting a physical VISA instrument, [set up VISA](installation.md#visa-backend-support), then run `ptl visa list`. Add `--idn` only to query identity on discovered resources. Neither is needed for simulation.

Use `ptl device idn PROFILE --address RESOURCE` to read identity through a profile’s protocol. For a bench device with native status-byte support, `ptl device status-byte ALIAS --bench bench.yaml --json` returns the byte and its hex representation. The first command selects a **profile**, the second a **bench alias**.

## Work with cameras and positioners

The common bench and device commands are:

```text
ptl
|-- bench
|   |-- ls
|   `-- validate
|-- motion
|   |-- position <alias>
|   |-- move <alias>
|   `-- status <alias>
|-- camera
|   `-- capture <alias>
`-- prober
    |-- contact <alias>
    `-- separate <alias>
```

Bench inventory, validation, camera capture, motion, and prober commands resolve the bench in this order: an explicit `--bench PATH`, the `PYTESTLAB_BENCH` environment variable, then the nearest `bench.yaml` or `bench.yml` in this directory or its parents. Inventory and strict validation do not open hardware. Use ordinary validation only with trusted profiles and extensions. Device commands target the named alias and skip experiment hooks. Use a station bench containing the aliases in the following examples.

### Capture with a configured camera

A camera needs its exact bench address even when it is the only camera connected. With a compatible camera already configured, inspect its entry and capture a still image:

```bash
ptl camera list --bench bench.yaml --json
ptl camera info microscope --bench bench.yaml
ptl camera capture microscope /tmp/view.jpg --bench bench.yaml
```

For a series, give `--count 10 --interval 0.5` and an output directory. Each frame gets a JSON metadata sidecar by default. Add `--no-metadata` to omit sidecars or `--json` to print output paths as JSON. For a complete bench and Python example, see [Using a camera or microscope](user_guide/using_camera_microscope.md).

### Check motion and prober declarations

Use the same motion commands for a stage or a prober. These commands read the selected alias through its configured backend:

```bash
ptl motion position prober --bench bench.yaml --units mm
ptl motion status prober --bench bench.yaml
```

Use `--json` for machine-readable output. Position accepts a coordinate `--frame` and output `--units`. Device status and command acknowledgements do not necessarily establish physical completion. Interpret responses using the selected profile.

Inspect prober capabilities and check a recipe before moving hardware:

```bash
ptl prober capabilities prober --bench bench.yaml --json
ptl prober preflight prober --bench bench.yaml --required position --required status --json
```

Capabilities lists profile-declared axes, frames, units, and actions. Preflight checks declarations without connecting. A full preflight checks every recipe requirement and may fail when a profile lacks mapped physical readbacks.

Use `ptl prober contact prober` and `ptl prober separate prober` for those prober-specific operations. Both can actuate the station. Confirm the configured station, travel and interlocks before using them. See [Using a prober](user_guide/using_prober.md) for profile-specific limits and commissioning commands.

`ptl motion move --help` shows how to supply an alias and `axis=value` coordinates. `--wait` needs a completion check declared by the profile. The former top-level motion commands remain available for compatibility.

## Simulation and circuit checks

`ptl sim doctor` checks that the circuit-simulation Python components import and that `ngspice` is available. It exits nonzero when the external simulator is missing. `ptl sim install-ngspice` can print package-manager installation guidance. These commands diagnose the circuit simulator environment. Instrument simulation uses each profile's `simulation` section and is configured through `bench.yaml`.

The [simulated meter](#run-a-measurement) does not need ngspice.

In 0.3.0, `--simulate` overrides per-device live settings and refuses to load the script if the bench has unsupported entries or automation hooks. It cannot synthesize missing responses and does not sandbox the script. Use only trusted Python and simulator inputs. Do not rely on `--simulate` as a force override in 0.2.4.

## Simulation profiles

Use a profile recording when you want reusable responses for one device. A recording script defines `main(device)`. Recording against physical hardware requires an address and runs a supplied script. Review the output before using it because it captures the commands and responses observed during that session.

```bash
ptl sim-profile record keysight/EDU36311A \
  --address "USB0::...::INSTR" \
  --script scripts/record_session.py \
  --output-path profiles/edu36311a-sim.yaml
```

The command can record against a simulated device with `--simulate`, but that only records behavior already provided by the official simulator. `ptl sim-profile diff keysight/EDU36311A` compares an override with the packaged profile. `ptl sim-profile edit keysight/EDU36311A` opens the override in the configured editor, and `reset` removes the override so packaged behavior is used again. Use `ptl sim-profile --help` for exact options.

## Record and replay a measurement session

Recording runs `main(bench)` against the bench in the supplied YAML and creates a session YAML containing the observed instrument exchanges. Replay runs that script against the recorded exchanges through simulated devices. Keep the capture with the script so its expected command sequence is clear.

```bash
ptl replay record read_voltage.py --bench bench.yaml --output session.yaml
ptl replay run read_voltage.py --session session.yaml
```

Recording can communicate with hardware and runs the script’s instrument actions. Replay substitutes the recorded backends; the Python script itself is not sandboxed. Playback requires a compatible recording and script. Use [Record and replay](user_guide/replay_mode.md) to investigate sequence mismatches.

## Generate validation evidence

Run these commands from the PyTestLab source checkout containing `pyproject.toml`. They read repository inputs to generate validation artifacts and a manifest. Give each run its own output directory.

```bash
ptl evidence generate --output artifacts/validation --section jcgm --check
ptl evidence check artifacts/validation
```

The example selects the JCGM section. Use `--section all` for the full bundle. The `--check` option verifies the just-written bundle. Checking a previously generated bundle confirms its files against the current repository state.

## Digital-twin validation

The twin oracle exercises known-truth oscilloscope signals in software. Its report is explicitly software-validation evidence, not a claim that a model has been characterized against hardware.

```bash
ptl twin oracle --output artifacts/scope-oracle --check
```

The twin evidence subcommands also support residual reports from hardware replay fixtures (JSON with expected and observed metrics, distinct from a session YAML) and characterized evidence from a passing independent-parity residual. A fixture generated by replaying a simulator against itself is regression evidence and is not sufficient for hardware-characterization claims. The available paths are:

```bash
ptl twin residual-from-replay capture.json --output artifacts/residual --check
ptl twin characterize-scope artifacts/residual/twin_residual_report.json --output artifacts/characterized-scope --check
```

Use only an accepted independent-parity capture for characterization. Check evidence with `ptl twin check PATH`. See [Digital twins and evidence](user_guide/digital_twin.md) for fixture requirements and evidence interpretation.


## When a command fails

| Symptom | What to check |
| --- | --- |
| The camera or prober alias is missing | Pass `--bench PATH` explicitly and inspect `ptl bench ls PATH`. The alias is the key under `devices`; a model name or resource string selects something different. |
| A DMM setting is unsupported | Re-run `instrument list-options` with the same function and `--include-unsupported`. Read the support reason and use the returned `value`, including its numeric or string type. |
| Replay reports an unexpected command | Compare the first divergent exchange with the capture. Check the script version, profile and order of reads before recording another baseline. |
| A stored bundle fails verification | Check it from the same source revision that generated it. Use a new output directory for a fresh run so the original manifest stays available for comparison. |

The [command index](user_guide/cli.md#command-index) lists every registered command by family.
