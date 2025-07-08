# Working with Benches

Bench Descriptors provide a powerful way to define and manage a collection of laboratory instruments as a single, cohesive unit called a **"Bench"**. This is particularly useful for complex experimental setups where multiple instruments need to be configured and controlled together.

The configuration for a bench is defined in a YAML file.

## The `bench.yaml` File

A `bench.yaml` file is a declarative way to describe your entire test setup. It can include instrument definitions, safety limits, automation scripts, and metadata for traceability.

```yaml title="bench.yaml"
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

  source1:
    profile: "my_custom_profiles/custom_signal_generator.yaml"
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
-   `automation` (dict): A place to define scripts or commands to run before (`pre_experiment`) or after (`post_experiment`) your main script.
-   `traceability` (dict): A section for metadata about your test, such as calibration dates or information about the Device Under Test (DUT).

---

## Using a Bench in Python

The `pytestlab.Bench` class is the primary way to work with bench configurations. The recommended way to load a bench is with the `async with` statement, which handles instrument connection and cleanup automatically.

```python
import asyncio
import pytestlab

async def main():
    # Bench.open() loads the YAML, validates it, and connects to all instruments.
    # The async with statement ensures instruments are closed properly.
    try:
        async with await pytestlab.Bench.open("path/to/your/bench.yaml") as bench:
            print(f"✅ Bench '{bench.config.bench_name}' loaded successfully.")
            print(f"🔬 Testing DUT: {bench.config.traceability.dut.description}")

            # Access instruments by their alias.
            # The API is the same as using a standalone instrument.
            await bench.psu.channel(1).set(voltage=3.3, current_limit=0.5).on()
            
            # Perform a measurement with the DMM.
            dc_voltage = await bench.dmm.measure_voltage_dc()
            print(f"Measured Voltage: {dc_voltage.values:.4f} V")

        # Post-experiment hooks are run automatically upon exiting the 'async with' block.
        print("✅ Bench closed successfully.")

    except Exception as e:
        print(f"❌ An error occurred: {e}")

if __name__ == "__main__":
    asyncio.run(main())
```

### Safety Limits

When `safety_limits` are defined in `bench.yaml`, PyTestLab wraps the instrument driver with a safety layer. If you attempt to send a command that exceeds a defined limit, a `SafetyLimitError` is raised *before* the command is sent to the instrument.

```python
try:
    # This will fail because the safety limit in our YAML is 5.5V
    await bench.psu.set_voltage(1, 6.0)
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