---
title: Getting Started
---

# Getting Started with PyTestLab

Welcome to PyTestLab! This guide will walk you through the essential first steps to get up and running with the toolbox.

The best way to get started is with our interactive **10-Minute Tour**. This Jupyter Notebook will guide you through:

- Creating and using a simulated instrument.
- Using the synchronous, facade-based API for instrument control.
- Performing a simple measurement.
- Storing results in a database.

[➡️ **Start the 10-Minute Tour**](../tutorials/10_minute_tour.ipynb)

---

## 1. Installation

Before you begin, make sure you have PyTestLab installed. If not, see the [Installation Guide](../installation.md).

```bash
pip install pytestlab
```

For full functionality (plotting, uncertainty, etc.), use:

```bash
pip install pytestlab[full]
```

---

## 2. Your First Instrument (Simulated)

PyTestLab uses a clean synchronous API that's easy to understand and use. All instrument operations are straightforward function calls.

Here's how to create a simulated oscilloscope and acquire data. PyTestLab opens the simulated backend automatically when the first instrument command runs:

```python
from pytestlab import AutoInstrument

def main():
    # Create a simulated oscilloscope
    scope = AutoInstrument.from_config("keysight/DSOX1204G", simulate=True)

    # Configure channel and trigger
    scope.channel(1).setup(scale=0.5, offset=0).enable()
    scope.trigger.setup_edge(source="CH1", level=0.25)

    # Acquire waveform data
    result = scope.read_channels(1)
    print("Acquired waveform data:")
    print(result.values.head())  # .values is a Polars DataFrame

    scope.close()

main()
```

---

## 3. Next Steps

- **Explore the [10-Minute Tour](../tutorials/10_minute_tour.ipynb)** for a hands-on walkthrough.
- See how to [Connect to real instruments](connecting.md).
- Browse the [Profile Gallery](../profiles/gallery.md) for supported devices.
- Read about [Simulation Mode](simulation.md) for hardware-free development.

---

## 4. Need Help?

- Check the [User Guide](../index.md) for more topics.
- Join the community or open an issue on GitHub if you get stuck.

---

Happy testing and measuring!
