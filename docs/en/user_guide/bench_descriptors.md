# Working with Benches

Bench Descriptors provide a powerful way to define and manage a collection of laboratory instruments as a single, cohesive unit called a **"Bench"**. This is particularly useful for complex experimental setups where multiple instruments need to be configured and controlled together.

The configuration for a bench is defined in a YAML file.

## The `bench.yaml` File

A `bench.yaml` file is a declarative way to describe your entire test setup. It can include instrument definitions, non-instrument devices, safety limits, route declarations, accessory chains, automation scripts, and metadata for traceability.

Start with this complete, offline example. Save it as `bench.yaml`:

```yaml
bench_name: Simulated voltage check
simulate: true
instruments:
  psu:
    profile: keysight/EDU36311A
    safety_limits:
      channels:
        1:
          voltage: {max: 5.5}
          current: {max: 1.0}
  dmm:
    profile: keysight/34470A
```

The PSU and meter use separate instrument simulators, not an electrically
connected circuit. Changing the simulated PSU setpoint does not change what
the simulated meter reads. See [circuit simulation](circuit_simulation.md) for
a simulation of connected components.

For a larger offline declaration, the source checkout includes
`examples/auditable_bench.yaml` with a synthetic scope, a named route, a
probe, and an executable measurement plan. For a real station, set the
backend and exact address for each device. Do not reuse assumed addresses or
limits. A local profile can be named by its path relative to the descriptor.

**Key Fields:**

-   `bench_name` (string): A descriptive name for your bench.
-   `simulate` (boolean): The default simulation flag for configured instruments and devices. Individual entries can override it. Use `ptl run --simulate` to force supported built-in simulation or reject the bench before loading the script.
-   `backend_defaults` (dict): Default settings for instrument backends (e.g., `type`, `timeout_ms`).
-   `instruments` (dict): A dictionary where each key is an **alias** for an instrument.
    -   **Alias** (e.g., `psu`, `dmm`): How you will refer to the instrument in your Python code (e.g., `bench.psu`).
    -   `profile` (string): The instrument profile to use (e.g., `"keysight/EDU36311A"`).
    -   `address` (string): The VISA resource string or other connection identifier.
    -   `safety_limits` (dict): Constrains supported driver operations. It does not replace hardware limits, interlocks, or station commissioning.
-   `devices` (dict): Non-instrument automatable resources. Use this for switch matrices, gantries, cameras, fixture controllers, and custom hardware. Each LAMB camera needs an explicit `address` copied from `ptl camera discover`; the server's camera count does not select the device.
-   `accessories` (dict): Passive probes, cables, leads, shunts, attenuators, and similar correction sources. PyTestLab does not assume instrument-default probes.
-   `routes` (dict): Dry-run physical path declarations. Routes describe endpoints, switch paths, route accessories, and settling metadata. They can be validated and described before hardware use. Routes are not applied implicitly by `bench.measure()`.
-   `measurement_plan` (list): Named executable or descriptive measurements. Executable entries use `target:` and can reference a route with `route:`. For v1 auditable measurements, a referenced route's `accessories:` list must match the measurement's `accessories:` list in order.
-   `automation` (dict): A place to define scripts or commands to run before (`pre_experiment`) or after (`post_experiment`) your main script.
-   `traceability` (dict): A section for metadata about your test, such as calibration dates or information about the Device Under Test (DUT).

---

## Using a Bench in Python

The `pytestlab.Bench` class is the primary way to work with bench configurations. The recommended way to load a bench is with the `with` statement, which handles instrument connection and cleanup automatically.

The default `Bench.open()` initializes devices and can run configured
experiment hooks. For a lazy session that skips those hooks, pass
`start_experiment=False`. It can still open hardware when you issue I/O to a
live alias. `ptl bench ls` and `ptl bench validate --strict` are the offline
inspection commands.

```python
from pytestlab import Bench

with Bench.open("bench.yaml") as bench:
    supply = bench.psu.channel(1)
    supply.set(voltage=3.3, current_limit=0.5).on()
    try:
        reading = bench.dmm.measure("dc_voltage", uncertainty=False)
        print(f"{float(reading):.3f} V (independent simulated meter)")
    finally:
        supply.off()
```

To execute the named measurement in the source checkout:

```python
from pytestlab import Bench

with Bench.open("examples/auditable_bench.yaml") as bench:
    print(bench.route("scope_ch1_to_dut_input").describe())
    print(bench.measurement("input_ripple_vpp").describe())
    print(bench.measure("input_ripple_vpp"))
```

This route describes a passive connection. A route that includes an active
switch is not applied by `measure()`: review the path and station-specific
requirements before applying it explicitly.

### Safety Limits

On supported device roles, `safety_limits` check typed settings such as PSU
voltage and current before a write. Guarded handles block raw commands, but
the limits do not check every action or guarantee DUT safety.

```python
from pytestlab import Bench
from pytestlab.bench import SafetyLimitError

with Bench.open("bench.yaml") as bench:
    try:
        bench.psu.set_voltage(1, 6.0)  # The configured limit is 5.5 V.
    except SafetyLimitError as exc:
        print(f"Caught expected safety error: {exc}")
```

---

### Command-Line Interface

PyTestLab provides CLI commands to manage and inspect bench configurations.

-   **List instruments in a bench:**
    ```bash
    ptl bench ls path/to/bench.yaml
    ```
-   **Validate a bench configuration:**
    ```bash
    ptl bench validate path/to/bench.yaml --strict
    ```
-   **List and describe declared routes without touching hardware:**
    ```bash
    ptl bench routes path/to/bench.yaml
    ptl bench route path/to/bench.yaml scope_ch1_to_dut_input
    ```
-   **List and describe executable measurements:**
    ```bash
    ptl bench measurements path/to/bench.yaml
    ptl bench measurement path/to/bench.yaml input_ripple_vpp
    ```
-   **Query live instrument identities without startup reset or hooks:**
    ```bash
    ptl bench id path/to/bench.yaml
    ```
-   **Export a built-in simulation-only descriptor, or reject unsupported entries:**
    ```bash
    ptl bench sim path/to/bench.yaml --output-path bench.sim.yaml
    ```

For more information, see the [CLI Reference](cli.md).

---

This system allows for flexible and reproducible management of your test setups, whether they involve real or simulated instruments.
