# Welcome to PyTestLab

**PyTestLab** is a modern, async-first Python toolbox for laboratory test-and-measurement automation, data management and analysis.

<div class="grid cards" markdown>

-   :material-flash:{ .lg .middle } **Async by Design**

    ---

    Non-blocking instrument I/O with modern `async/await` patterns.

    [:octicons-arrow-right-24: Getting started](user_guide/getting_started.md)

-   :material-tools:{ .lg .middle } **Unified Driver Layer**

    ---

    Consistent high-level API across oscilloscopes, PSUs, DMMs, VNAs, AWGs, and more.

    [:octicons-arrow-right-24: API Reference](api/instruments.md)

-   :material-play:{ .lg .middle } **Simulation Mode**

    ---

    Develop anywhere using the built-in SimBackend - no hardware required.

    [:octicons-arrow-right-24: Learn about simulation](user_guide/simulation.md)

-   :material-database:{ .lg .middle } **Rich Database**

    ---

    Compressed storage of experiments with full-text search and analysis tools.

    [:octicons-arrow-right-24: Explore experiments](api/experiments.md)

</div>

## :rocket: Quick Start

### Installation

=== "Core Package"

    ```bash
    pip install pytestlab
    ```

=== "Full Installation"

    ```bash
    pip install pytestlab[full]  # includes plotting, uncertainties, etc.
    ```

=== "With VISA Support"

    ```bash
    # Install NI-VISA or Keysight IO Libraries first
    pip install pytestlab pyvisa
    ```

### Hello Oscilloscope

Here's a simple example using a simulated oscilloscope:

```python
import asyncio
from pytestlab.instruments import AutoInstrument

async def main():
    # Create a simulated oscilloscope
    scope = AutoInstrument.from_config("keysight/DSOX1204G", simulate=True)
    await scope.connect_backend()

    # Configure channels and trigger
    await scope.channel(1).setup(scale=0.5).enable()
    await scope.trigger.setup_edge(source="CH1", level=0.2)

    # Read data
    trace = await scope.read_channels(1)  # Returns Polars DataFrame
    print(f"Captured {len(trace)} points")
    print(trace.head())

    await scope.close()

asyncio.run(main())
```

### Bench Configuration

Create a multi-instrument setup using YAML configuration:

```yaml title="bench.yaml"
bench_name: "Power Amplifier Test Setup"
simulate: false  # Set to true for simulation mode

instruments:
  psu:
    profile: "keysight/EDU36311A"
    address: "TCPIP0::172.22.1.5::inst0::INSTR"
    safety_limits:
      channels:
        1: 
          voltage: {max: 6.0}
          current: {max: 3.0}
  
  dmm:
    profile: "keysight/34470A"
    address: "USB0::0x0957::0x1B07::MY56430012::INSTR"
    
  scope:
    profile: "keysight/DSOX1204G"
    address: "USB0::0x0957::0x179B::MY56123456::INSTR"
```

```python
import asyncio
import pytestlab

async def run_bench():
    async with await pytestlab.Bench.open("bench.yaml") as bench:
        # Set power supply voltage
        await bench.psu.set_voltage(1, 3.3)
        await bench.psu.output(1, True)
        
        # Measure with DMM
        voltage = await bench.dmm.measure_voltage_dc()
        print(f"Measured: {voltage.values:.3f} {voltage.units}")
        
        # Capture scope trace
        trace = await bench.scope.read_channels([1, 2])
        print(f"Scope captured {len(trace)} points")

asyncio.run(run_bench())
```

## :books: What's Next?

- **New to PyTestLab?** Start with our [10-minute tour](tutorials/10_minute_tour.ipynb)
- **Setting up instruments?** Check the [connection guide](user_guide/connecting.md)
- **Need specific instruments?** Browse the [profile gallery](profiles/gallery.md)
- **Want to contribute?** See our [contributing guide](contributing.md)

---

!!! tip "Pro Tip"
    Use `pytestlab list-profiles` in your terminal to see all available instrument profiles!