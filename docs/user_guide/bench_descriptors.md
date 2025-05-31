# Bench Descriptors

Bench Descriptors provide a powerful way to define and manage a collection of laboratory instruments as a single, cohesive unit called a "Bench". This is particularly useful for complex experimental setups where multiple instruments need to be configured and controlled together.

The configuration for a bench is defined in a YAML file, typically named `bench.yaml`.

## Creating a `bench.yaml` File

A `bench.yaml` file has the following structure:

```yaml
bench_name: "My RF Test Bench"
description: "Bench for S-parameter measurements and signal analysis."
simulate: false # Global simulation flag (optional, default: false)
backend_defaults: # Optional global backend settings
  type: "visa" # Default backend type ("visa", "lamb", "sim")
  timeout_ms: 5000 # Default communication timeout in milliseconds

instruments:
  vna: # Alias for the instrument (must be a valid Python identifier)
    profile: "keysight/E5071C_VNA" # Profile key or path to a custom profile YAML
    address: "TCPIP0::K-E5071C-12345::inst0::INSTR" # VISA resource string, Lamb ID, or "sim"
    # backend: # Optional: Override global backend settings for this instrument
    #   type: "visa"
    #   timeout_ms: 10000
    # simulate: false # Optional: Override global simulate flag for this instrument

  sa:
    profile: "keysight/N9000A_SA"
    address: "TCPIP0::K-N9000A-67890::inst0::INSTR"
    # simulate: true # This specific instrument will be simulated

  source1:
    profile: "my_custom_profiles/custom_signal_generator.yaml" # Path to a custom profile
    address: "lamb::SG001" # Example Lamb identifier
    backend:
      type: "lamb"
      # Lamb-specific settings might go here in the future

  sim_psu:
    profile: "keysight/EDU36311A"
    # Address defaults to "sim" if not provided
    # simulate: true # Can also be explicitly set
```

**Key Fields:**

*   `bench_name` (required): A descriptive name for your bench.
*   `description` (optional): A longer description of the bench's purpose.
*   `simulate` (optional, boolean): A global flag to run all instruments in simulation mode. Defaults to `false`. This can be overridden per instrument.
*   `backend_defaults` (optional): Default settings for instrument backends.
    *   `type` (optional, string): The default backend type. Can be `"visa"`, `"lamb"`, or `"sim"`. Defaults to `"visa"`.
    *   `timeout_ms` (optional, integer): Default communication timeout in milliseconds. Defaults to `5000`.
*   `instruments` (required, dictionary): A dictionary where each key is an **alias** for an instrument and the value contains the instrument's configuration.
    *   **Alias** (e.g., `vna`, `sa`, `source1`): This is how you will refer to the instrument in your Python code (e.g., `bench.vna`). It must be a valid Python identifier (letters, numbers, underscores, not starting with a number).
    *   `profile` (required, string): Specifies the instrument profile. This can be:
        *   A profile key (e.g., `"keysight/E5071C_VNA"`) which refers to a built-in profile.
        *   A relative or absolute path to a custom instrument profile YAML file (e.g., `"my_custom_profiles/custom_sg.yaml"`).
    *   `address` (optional, string): The communication address for the instrument.
        *   For VISA instruments: The VISA resource string (e.g., `"TCPIP0::K-E5071C-12345::inst0::INSTR"`).
        *   For Lamb instruments: The Lamb device identifier (e.g., `"lamb::SG001"`).
        *   For simulated instruments: Can be explicitly set to `"sim"`.
        *   **If `address` is not provided, it defaults to `"sim"`, and the instrument will be simulated unless `simulate: false` is set for that specific instrument.**
    *   `backend` (optional, dictionary): Allows overriding the global `backend_defaults` for this specific instrument.
        *   `type` (optional, string): Specific backend type for this instrument.
        *   `timeout_ms` (optional, integer): Specific timeout for this instrument.
    *   `simulate` (optional, boolean): Overrides the global `simulate` flag for this specific instrument. If `true`, this instrument runs in simulation mode. If `false`, it attempts a real connection (unless the global `simulate` is `true` and this is not set). If not provided, the global `simulate` flag (or its default `false`) is used.

## Using Bench Descriptors

### Python API

The `pytestlab.bench.Bench` class provides the primary interface for working with bench configurations in Python.

**Opening a Bench (Asynchronous):**

The recommended way to load and initialize a bench is using the asynchronous `Bench.open()` class method. This method loads the YAML configuration, validates it, and then asynchronously initializes and connects to all the instruments defined in the bench.

```python
import asyncio
import pytestlab

async def main():
    try:
        # Bench.open() is an async factory method
        bench = await pytestlab.Bench.open("path/to/your/bench.yaml")
        print(f"Successfully opened bench: {bench.config.bench_name}")

        # Access instruments by their alias
        if hasattr(bench, 'vna'):
            idn_response = await bench.vna.id() # Assuming vna is not simulated
            print(f"VNA IDN: {idn_response}")

        if hasattr(bench, 'sa'):
            # Example: Perform an action with the spectrum analyzer
            # await bench.sa.set_center_frequency(1e9) # Fictional method
            print(f"SA profile: {bench.config.instruments['sa'].profile}")

        # Instruments are automatically closed when the 'bench' object goes out of scope
        # if using 'async with', or by explicitly calling bench.close_all()
    except Exception as e:
        print(f"Error opening or using bench: {e}")
    finally:
        if 'bench' in locals() and bench:
            await bench.close_all() # Ensure instruments are closed

if __name__ == "__main__":
    asyncio.run(main())
```

**Asynchronous Context Manager:**

The `Bench` class also supports the asynchronous context manager protocol, which ensures that `close_all()` is called automatically.

```python
import asyncio
import pytestlab

async def main():
    try:
        async with await pytestlab.Bench.open("path/to/your/bench.yaml") as bench:
            print(f"Successfully opened bench: {bench.config.bench_name}")

            if hasattr(bench, 'vna'):
                idn_response = await bench.vna.id()
                print(f"VNA IDN: {idn_response}")
            # ... other operations ...
        # Instruments are automatically closed here
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
```

**Accessing Instruments:**

Once the bench is initialized (e.g., via `Bench.open()`), instruments are accessible as attributes of the `Bench` instance, using their defined aliases:

```python
# Assuming 'bench' is an initialized Bench instance
# and 'dmm1' was an alias in bench.yaml
voltage = await bench.dmm1.measure_voltage_dc()
```

**Closing Instruments:**

*   If using the `async with` statement, instruments are closed automatically when exiting the block.
*   Otherwise, you should explicitly call `await bench.close_all()` to disconnect from all instruments and release resources.

### Command Line Interface (CLI)

PyTestLab provides CLI commands to manage and inspect bench configurations.

*   **List Instruments in a Bench:**
    ```bash
    pytestlab bench ls path/to/your/bench.yaml
    ```
    This command parses the `bench.yaml` file and displays a table of the configured instruments, their profiles, addresses, and simulation status.

*   **Validate a Bench Configuration:**
    ```bash
    pytestlab bench validate path/to/your/bench.yaml
    ```
    This command validates the structure of your `bench.yaml` file against the Pydantic schema and also attempts to load the profiles specified for each instrument. It reports any errors found.

*   **Identify Instruments in a Bench (IDN Query):**
    ```bash
    pytestlab bench id path/to/your/bench.yaml
    ```
    This command attempts to connect to all non-simulated instruments in the bench and queries their `*IDN?` string. For simulated instruments, it will indicate they are simulated.

*   **Convert Bench to Simulation Mode:**
    ```bash
    pytestlab bench sim path/to/your/bench.yaml
    ```
    This command reads an existing `bench.yaml` file and outputs a new version of it with all instruments configured for simulation mode (`simulate: true` globally and for each instrument, with address set to `"sim"`).
    You can save the output to a new file:
    ```bash
    pytestlab bench sim path/to/your/bench.yaml --output-path path/to/your/bench.sim.yaml
    ```

This system allows for flexible and reproducible management of your test setups, whether they involve real or simulated instruments.