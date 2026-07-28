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
from pytestlab.measurements import MeasurementSession
from pytestlab import DMMFunction

def main():
    with MeasurementSession("Power Supply Test", compliance=False) as session:
        dmm = session.instrument("dmm", "keysight/EDU34450A", simulate=True)
        psu = session.instrument("psu", "keysight/EDU36311A", simulate=True)
        session.parameter("point", [0])

        @session.acquire
        def acquire(dmm, psu):
            psu.channel(1).set(voltage=3.3, current_limit=0.5).on()
            return dmm.measure(DMMFunction.VOLTAGE_DC)

        experiment = session.run(show_progress=False)
        print(experiment.data)

main()
```

---

## Key Features

- **Context Management:** Ensures all resources are properly initialized and cleaned up.
- **Measurement Metadata:** Preserve uncertainty-aware result metadata alongside numeric columns.
- **Result Recording:** Build a Polars table and an `Experiment` from registered acquisitions.
- **Integration:** Works seamlessly with PyTestLab's database and experiment modules.

---

## Step Helpers for Parameters

PyTestLab exposes `pytestlab.measurements.step` helpers so you can succinctly define logarithmic, exponential, geometric, or fully custom sequences for `session.parameter(...)`:

```python
from pytestlab.measurements import MeasurementSession, step

with MeasurementSession() as session:
    session.parameter("freq", step.log(start=1e3, stop=1e6, count=100))
    session.parameter("gain", step.exp(exponent_start=-3, exponent_stop=2, count=25))
    session.parameter("impedance", step.points([1+1j, 1-1j, -1+1j]))
```

Each helper returns a `StepSpec` that lazily generates the final iterable just before the sweep runs, keeping scripts tidy while still supporting exotic sweep shapes.

---

For more advanced usage, see the [Experiments & Sweeps API](experiments.md) and the [10-Minute Tour](../tutorials/10_minute_tour.ipynb).
