---
title: Getting Started
---

# Getting Started with PyTestLab

Take a first DC voltage reading with a packaged simulator. No instrument,
device address, or VISA runtime is needed.

## 1. Installation

Follow the [0.3.0 installation guide](../installation.md) and check
`ptl --version` before running this example.

## 2. Your First Measurement (Simulated)

Save this as `first_measurement.py`:

```python
from pytestlab import AutoInstrument

dmm = AutoInstrument.from_preset("keysight/34470A", simulate=True)
try:
    reading = dmm.measure("dc_voltage", range_val=10, uncertainty=False)
    print(f"{float(reading):.3f} V (simulated)")
finally:
    dmm.close()
```

Run `python first_measurement.py`. The output is `0.000 V (simulated)`. This is
a fixture response, not a physical or calibrated measurement.

## 3. Next Steps

- [Put the simulated meter in a bench](../bench-yaml.md#start-with-one-simulated-meter).
- [Run a measurement and save the result from the CLI](../cli.md#run-a-measurement).
- [Connect to a physical instrument](connecting.md#real-instrument) when ready.
