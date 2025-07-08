---
title: Home
hide:
  - navigation
  - toc
---

<p align="center">
  <img src="assets/logo_text.png" alt="PyTestLab Logo with Text" width="600">
</p>

<h2 align="center">A modern, async-first Python toolbox for laboratory test-and-measurement automation, data analysis, and management.</h2>

<div class="grid cards" markdown>

-   :material-flash:{ .lg .middle } **Async by Design**

    ---

    Harness the power of Python's `async/await` for non-blocking instrument I/O, enabling concurrent operations and responsive applications.

    [:octicons-arrow-right-24: Learn about Async](user_guide/async_vs_sync.md)

-   :material-tools:{ .lg .middle } **Unified Driver Layer**

    ---

    A consistent, high-level API for oscilloscopes, PSUs, DMMs, VNAs, AWGs, and more, simplifying instrument control.

    [:octicons-arrow-right-24: Browse Instruments](api/instruments.md)

-   :material-play:{ .lg .middle } **Simulation Mode**

    ---

    Develop and test anywhere using the built-in YAML-driven simulation backend. No hardware required.

    [:octicons-arrow-right-24: Explore Simulation](user_guide/simulation.md)

-   :material-file-document-outline:{ .lg .middle } **Declarative Benches**

    ---

    Define and manage your entire test setup, including safety limits and automation hooks, in a single `bench.yaml` file.

    [:octicons-arrow-right-24: Master Benches](user_guide/bench_descriptors.md)

</div>

## 🚀 Quick Start

### Installation

=== "Core"
    ```bash
    pip install pytestlab
    ```

=== "Full"
    ```bash
    pip install pytestlab[full]  # includes plotting, uncertainties, etc.
    ```

=== "With NI-VISA"
    ```bash
    # Install NI-VISA or Keysight IO Libraries first
    pip install -U pyvisa
    ```

### Hello, Simulated Oscilloscope!

Here's a quick look at PyTestLab's intuitive, asynchronous API.

```python title="Simulated Scope Example"
import asyncio
from pytestlab.instruments import AutoInstrument

async def main():
    # Load a simulated oscilloscope using its profile key
    # `simulate=True` uses the powerful SimBackendV2
    scope = await AutoInstrument.from_config("keysight/DSOX1204G", simulate=True)
    await scope.connect_backend()

    # Configure channels and trigger using a fluent, chainable API
    await scope.channel(1).setup(scale=0.5, offset=0).enable()
    await scope.trigger.setup_edge(source="CH1", level=0.25)

    # Acquire and print waveform data
    result = await scope.read_channels(1)  # Returns a MeasurementResult
    print("Acquired waveform data:")
    print(result.values.head()) # .values is a Polars DataFrame

    await scope.close()

if __name__ == "__main__":
    asyncio.run(main())
```

## 📚 Dive In

- **New to PyTestLab?** Start with our [10-minute tour](../tutorials/10_minute_tour.ipynb)
- **Setting up instruments?** Check the [connection guide](user_guide/connecting.md)
- **Need specific instruments?** Browse the [profile gallery](profiles/gallery.md)
- **Want to contribute?** See our [contributing guide](contributing.md)

-----

!!! tip "Pro Tip"
    Use `pytestlab list-profiles` in your terminal to see all available instrument profiles!