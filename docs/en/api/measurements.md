# Measurement Session

The `MeasurementSession` class in PyTestLab provides a high-level, context-managed interface for orchestrating complex measurement workflows. It is designed to coordinate multiple instruments, manage experiment metadata, and ensure reproducibility and traceability of your measurements.

---

## Overview

A `MeasurementSession` encapsulates:

- The set of instruments involved in a measurement.
- Experiment metadata (operator, DUT, environmental conditions, etc.).
- The sequence of measurement steps and their results.
- Automatic logging and database integration.

This abstraction is ideal for automating multi-instrument experiments, batch measurements, or compliance/audit scenarios.

---

## API Reference

::: pytestlab.measurements.MeasurementSession
    options:
      show_root_heading: true
      show_category_heading: true
      show_if_no_docstring: true

---

## Example Usage

```python
import asyncio
from pytestlab.measurements import MeasurementSession
from pytestlab.instruments import AutoInstrument

async def main():
    # Create instrument instances (simulated for this example)
    dmm = await AutoInstrument.from_config("keysight/EDU34450A", simulate=True)
    psu = await AutoInstrument.from_config("keysight/EDU36311A", simulate=True)
    await dmm.connect_backend()
    await psu.connect_backend()

    # Start a measurement session
    async with MeasurementSession(
        instruments={"dmm": dmm, "psu": psu},
        metadata={"operator": "Alice", "experiment": "Power Supply Test"}
    ) as session:
        # Configure instruments
        await psu.channel(1).set(voltage=3.3, current_limit=0.5).on()
        # Perform measurement
        voltage = await dmm.measure_voltage_dc()
        # Record result in the session
        session.record("dmm_voltage", voltage)

        # ... additional steps ...

    # Session automatically logs results and closes instruments

asyncio.run(main())
```

---

## Key Features

- **Async Context Management:** Ensures all resources are properly initialized and cleaned up.
- **Metadata Tracking:** Attach arbitrary metadata to each session for traceability.
- **Result Recording:** Store and retrieve results by key for later analysis or database storage.
- **Integration:** Works seamlessly with PyTestLab's database and experiment modules.

---

For more advanced usage, see the [Experiments & Sweeps API](experiments.md) and the [10-Minute Tour](../tutorials/10_minute_tour.ipynb).