# Working with Benches

Bench Descriptors provide a powerful way to define and manage a collection of laboratory instruments as a single, cohesive unit called a **"Bench"**. This is particularly useful for complex experimental setups where multiple instruments need to be configured and controlled together.

The configuration for a bench is defined in a YAML file.

## The `bench.yaml` File

A `bench.yaml` file is a declarative way to describe your entire test setup. It can include instrument definitions, non-instrument devices, safety limits, route declarations, accessory chains, automation scripts, and metadata for traceability.

```yaml
bench_name: "Power Amplifier Characterization"
description: "A bench for testing the gain and efficiency of a power amplifier."
version: "1.0"

experiment:
  title: "PA Gain Compression Test"
  operator: "Lab User"

simulate: false  # Global flag. Set to true to run the entire bench in simulation mode.

backend_defaults:
  type: "visa"      # Default backend for all instruments ("visa", "lamb", or "sim").
  timeout_ms: 10000

instruments:
  # Each key under 'instruments' is an alias used to access it in Python (e.g., bench.psu)
  vna:
    profile: "keysight/E5071C_VNA"
    address: "TCPIP0::K-E5071C-12345::inst0::INSTR"

  psu:
    profile: "keysight/EDU36311A"
    address: "TCPIP0::172.22.1.5::inst0::INSTR"
    safety_limits:  # Optional safety limits
      channels:
        1: { voltage: { max: 5.5 }, current: { max: 1.0 } }
        2: { voltage: { max: 12.0 }, current: { max: 0.5 } }

  sa:
    profile: "keysight/N9000A_SA"
    address: "TCPIP0::K-N9000A-67890::inst0::INSTR"

  dmm:
    profile: "keysight/34470A"
    address: "USB0::0x0957::0x1B07::MY56430012::INSTR"

  scope:
    profile: "keysight/DSOX1204G"
    address: "TCPIP0::172.22.1.20::inst0::INSTR"

  source1:
    file: "my_custom_profiles/custom_signal_generator.yaml"
    address: "lamb::SG001"
    backend:
      type: "lamb"

  awg:
    profile: "keysight/EDU33212A"
    address: "USB0::0x2A8D::0x2A01::MY57701234::INSTR"
    simulate: true  # Individual instruments can override the global simulate flag

  sim_psu:
    profile: "keysight/EDU36311A"
    # Address defaults to "sim" if not provided
    # simulate: true

devices:
  # Devices are automatable lab resources that are not necessarily instruments.
  # Examples: switch matrices, cameras, gantries, fixtures, safety controllers.
  matrix:
    file: "./devices/matrix.yaml"
    role: switching
    simulate: false

accessories:
  vin_probe:
    profile: keysight/N2142A
    serial_number: MY1234

routes:
  scope_ch1_to_dut_input:
    description: "Scope CH1 is physically connected to DUT input."
    device: matrix
    connects:
      - from: scope.CH1
        to: dut.input
        path: [M1.C1, M1.R5]
    accessories: [vin_probe]
    settling_time_s: 0.1

measurement_plan:
  - name: input_ripple_vpp
    description: "Input ripple through the declared probe and route."
    instrument: scope
    route: scope_ch1_to_dut_input
    target:
      kind: oscilloscope_channel
      channel: 1
      measurement: vpp
    accessories: [vin_probe]

automation:
  pre_experiment:
    - "psu: output all OFF"
    - "python scripts/setup_environment.py"
  post_experiment:
    - "psu: output all OFF"
    - "python scripts/save_results.py"

traceability:
  dut:
    serial_number: "PA-SN-042"
    description: "Power Amplifier Prototype Rev C"
```

**Key Fields:**

-   `bench_name` (string): A descriptive name for your bench.
-   `simulate` (boolean): A global flag to run all instruments in simulation mode. Can be overridden per instrument.
-   `backend_defaults` (dict): Default settings for instrument backends (e.g., `type`, `timeout_ms`).
-   `instruments` (dict): A dictionary where each key is an **alias** for an instrument.
    -   **Alias** (e.g., `psu`, `dmm`): How you will refer to the instrument in your Python code (e.g., `bench.psu`).
    -   `profile` (string): The instrument profile to use (e.g., `"keysight/EDU36311A"`).
    -   `address` (string): The VISA resource string or other connection identifier.
    -   `safety_limits` (dict): Defines maximum voltage/current to prevent accidental damage.
-   `devices` (dict): Non-instrument automatable resources. Use this for switch matrices, gantries, cameras, fixture controllers, and custom hardware.
-   `accessories` (dict): Passive probes, cables, leads, shunts, attenuators, and similar correction sources. PyTestLab does not assume instrument-default probes.
-   `routes` (dict): Dry-run physical path declarations. Routes describe endpoints, switch paths, route accessories, and settling metadata. They can be validated and described before hardware use. Routes are not applied implicitly by `bench.measure()`.
-   `measurement_plan` (list): Named executable or descriptive measurements. Executable entries use `target:` and can reference a route with `route:`. For v1 auditable measurements, a referenced route's `accessories:` list must match the measurement's `accessories:` list in order.
-   `automation` (dict): A place to define scripts or commands to run before (`pre_experiment`) or after (`post_experiment`) your main script.
-   `traceability` (dict): A section for metadata about your test, such as calibration dates or information about the Device Under Test (DUT).

---

## Using a Bench in Python

The `pytestlab.Bench` class is the primary way to work with bench configurations. The recommended way to load a bench is with the `with` statement, which handles instrument connection and cleanup automatically.

```python
import pytestlab

def main():
    # Bench.open() loads the YAML, validates it, and connects to all instruments.
    # The with statement ensures instruments are closed properly.
    try:
        with pytestlab.Bench.open("path/to/your/bench.yaml") as bench:
            print(f"✅ Bench '{bench.config.bench_name}' loaded successfully.")
            print(f"🔬 Testing DUT: {bench.config.traceability.dut.description}")

            # Access instruments by their alias.
            # The API is the same as using a standalone instrument.
            bench.psu.channel(1).set(voltage=3.3, current_limit=0.5).on()

            # Perform a measurement with the DMM.
            dc_voltage = bench.dmm.measure(pytestlab.DMMFunction.VOLTAGE_DC)
            print(f"Measured Voltage: {dc_voltage.values:.4f} V")

            # Review and execute a declared route/accessory-aware measurement.
            print(bench.route("scope_ch1_to_dut_input").describe())
            print(bench.measurement("input_ripple_vpp").describe())
            # Routes are never applied implicitly by measure().
            # If the route uses an active switch matrix, apply it deliberately:
            bench.route("scope_ch1_to_dut_input").apply()
            ripple = bench.measure("input_ripple_vpp")

        # Post-experiment hooks are run automatically upon exiting the 'with' block.
        print("✅ Bench closed successfully.")

    except Exception as e:
        print(f"❌ An error occurred: {e}")

if __name__ == "__main__":
    main()
```

### Safety Limits

When `safety_limits` are defined in `bench.yaml`, PyTestLab wraps the instrument driver with a safety layer. If you attempt to send a command that exceeds a defined limit, a `SafetyLimitError` is raised *before* the command is sent to the instrument.

```python
try:
    # This will fail because the safety limit in our YAML is 5.5V
    bench.psu.set_voltage(1, 6.0)
except SafetyLimitError as e:
    print(f"Caught expected safety error: {e}")
```

---

### Command-Line Interface

PyTestLab provides CLI commands to manage and inspect bench configurations.

-   **List instruments in a bench:**
    ```bash
    pytestlab bench ls path/to/bench.yaml
    ```
-   **Validate a bench configuration:**
    ```bash
    pytestlab bench validate path/to/bench.yaml
    ```
-   **List and describe declared routes without touching hardware:**
    ```bash
    pytestlab bench routes path/to/bench.yaml
    pytestlab bench route path/to/bench.yaml scope_ch1_to_dut_input
    ```
-   **List and describe executable measurements:**
    ```bash
    pytestlab bench measurements path/to/bench.yaml
    pytestlab bench measurement path/to/bench.yaml input_ripple_vpp
    ```
-   **Identify instruments in a bench (IDN query):**
    ```bash
    pytestlab bench id path/to/bench.yaml
    ```
-   **Convert a bench to simulation mode:**
    ```bash
    pytestlab bench sim path/to/bench.yaml --output-path bench.sim.yaml
    ```

For more information, see the [CLI Reference](cli.md).

---

This system allows for flexible and reproducible management of your test setups, whether they involve real or simulated instruments.
