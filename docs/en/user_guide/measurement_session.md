# Measurement Sessions

The `MeasurementSession` class is the core builder for orchestrating complex measurement workflows in PyTestLab. It provides a high-level, declarative API for defining parameter sweeps, registering measurement functions, and running both sequential and parallel (concurrent) acquisition tasks.

---

## Overview

A `MeasurementSession` manages:

- **Parameters:** Variables to sweep or control (e.g., voltage, frequency, temperature).
- **Instruments:** Devices under test, loaded from a `Bench` or individually.
- **Measurement Functions:** Functions that acquire data from instruments.
- **Background Tasks:** Functions (e.g., stimulus generation) running in parallel with data acquisition.

Sessions can be run as **parameter sweeps** (classic grid search) or in **parallel mode** (continuous acquisition with background tasks).

---

## Basic Usage

### 1. Create a Session

You can create a session directly (no bench required), or (recommended) inherit instruments from a `Bench`:

### Without a Bench (standalone instruments)

```python
from pytestlab.measurements import MeasurementSession

def main():
    with MeasurementSession() as session:
        # Register instruments directly
        psu = session.instrument("psu", "keysight/EDU36311A", simulate=True)
        dmm = session.instrument("dmm", "keysight/34470A", simulate=True)

        # ... define parameters and measurements ...
        pass

main()
```

### With a Bench

```python
from pytestlab import Bench
from pytestlab.measurements import MeasurementSession

def main():
    with Bench.open("bench.yaml") as bench:
        with MeasurementSession(bench=bench) as session:
            # ... define parameters and measurements ...
            pass

main()
```

### 2. Define Parameters

Parameters define the sweep axes for your experiment:

```python
session.parameter("voltage", [1.0, 2.0, 3.0], unit="V", notes="Supply voltage")
session.parameter("current", [0.1, 0.5, 1.0], unit="A")
```

#### Step helpers for non-linear sweeps

When you need logarithmic, exponential, or any custom stepping you can use the declarative helpers exposed as `pytestlab.measurements.step`:

```python
from pytestlab.measurements import step

session.parameter("frequency", step.log(start=1e3, stop=1e6, count=200))
session.parameter("gain", step.exp(exponent_start=-3, exponent_stop=2, count=25))
session.parameter("impedance", step.points([1+1j, 1-1j, -1+1j, -1-1j]))
```

Each helper returns a `StepSpec`, which is resolved just before the sweep starts. The `step.custom(...)` helper lets you wrap any generator function so you can describe arbitrary sequences (chirps, lookup tables, etc.) without precomputing them manually.

### 3. Register Measurement Functions

Measurement functions are synchronous functions that return either a dictionary of
results or one `MeasurementResult`. Use the `@session.acquire` decorator:

```python
@session.acquire
def measure_voltage(psu, dmm, voltage, current):
    psu.channel(1).set(voltage=voltage, current_limit=current).on()
    try:
        result = dmm.measure("dc_voltage")
        return {"measured_voltage": result.values}
    finally:
        psu.channel(1).off()
```

- **Arguments:** Instrument aliases and parameter values as individual arguments.
- **Return:** A mapping of result names to values, or one `MeasurementResult`.
  Uncertainty-aware values remain numeric in the main column and receive a
  `<column>__measurement` JSON metadata column for lossless reconstruction.

### Store a waveform or sweep with each trial

In an ordinary non-compliance session, keep the entire table attached to its sweep
parameters by returning a table-valued `MeasurementResult`. For example, if
`bench.yaml` defines the alias `scope`:

```python
from pytestlab import Bench, MeasurementSession

with Bench.open("bench.yaml") as bench, MeasurementSession(bench=bench, compliance=False) as session:
    session.parameter("repeat", [1, 2])

    @session.acquire
    def waveform(scope):
        return {"waveform": scope.read_channels(1, 2)}

    experiment = session.run()

first_waveform = experiment.measurements["waveform"][0].values
```

One row per trial retains sample order and types. Use consistent columns
and types across trials. `waveform__measurement` retains instrument, units,
timestamp, sampling rate, and envelope. Parquet and the configured bench
database keep both columns. One-dimensional NumPy booleans, standard-width
integers, `float32`, and `float64` are typed lists. A missing capture is `None` at its original trial index. Use Polars nulls for masked samples. This does not sign each sample.

Return a VNA sweep, spectrum capture, RF power reading, or impedance sweep
directly. In a session opened with `compliance=False`, for example:

```python
@session.acquire
def s_parameters(vna):
    return vna.get_s_parameter_data()
```

Read captured samples and metadata with `experiment.measurements["s_parameters"][0]`. Native RF
results work in ordinary sessions, not active signed, audited, or timestamped
sessions. Storing them does not evaluate measurement uncertainty.

### 4. Run the Session

Run the session to perform the sweep:

```python
experiment = session.run()
print(experiment.data)
```

---

## Parameter Sweep Mode

In sweep mode, the session iterates over all combinations of parameter values, calling each registered measurement function at every point.

**Example:**

#### Without a Bench

```python
from pytestlab.measurements import MeasurementSession

def main():
    with MeasurementSession() as session:
        psu = session.instrument("psu", "keysight/EDU36311A", simulate=True)
        dmm = session.instrument("dmm", "keysight/34470A", simulate=True)

        session.parameter("voltage", [1.0, 2.0, 3.0])
        session.parameter("current", [0.1, 0.5, 1.0])

        @session.acquire
        def measure(psu, dmm, voltage, current):
            psu.channel(1).set(voltage=voltage, current_limit=current).on()
            try:
                result = dmm.measure("dc_voltage")
                return {"v_measured": result.values}
            finally:
                psu.channel(1).off()

        experiment = session.run()
        print(experiment.data)

main()
```

#### With a Bench

The standalone PSU and DMM above have independent returns, not a connected circuit.
For a configured bench with aliases `psu` and `dmm`, place the following inside
a `MeasurementSession(bench=bench)` context.

```python
session.parameter("voltage", [1.0, 2.0, 3.0])
session.parameter("current", [0.1, 0.5, 1.0])

@session.acquire
def measure(psu, dmm, voltage, current):
    psu.channel(1).set(voltage=voltage, current_limit=current).on()
    try:
        result = dmm.measure("dc_voltage")
        return {"v_measured": result.values}
    finally:
        psu.channel(1).off()

experiment = session.run()
print(experiment.data)
```

- The resulting data is a table (Polars DataFrame) with columns for each parameter and measurement.

---

## Parallel Mode

For dynamic experiments—such as stress tests, real-time monitoring, or when stimulus and acquisition must run in parallel—use **parallel mode** with the `@session.task` decorator.

### Background Tasks with @session.task

Use the `@session.task` decorator to register background functions that run in parallel with data acquisition:

```python
import time
from pytestlab.measurements import MeasurementSession

def main():
    with MeasurementSession() as session:
        psu = session.instrument("psu", "keysight/EDU36311A", simulate=True)

        @session.task
        def psu_ramp(psu, stop_event):
            """Background task that ramps PSU voltage while acquisition runs."""
            while not stop_event.is_set():
                for v in [1.0, 2.0, 3.0]:
                    if stop_event.is_set():
                        break
                    psu.channel(1).set(voltage=v)
                    time.sleep(0.5)

        # The task will automatically start when session.run() is called
        # (see below for full example)
```

### Acquisition Function

Register at least one `@session.acquire` function for data collection:

```python
@session.acquire
def measure(psu):
    return {"psu_voltage": psu.channel(1).get_voltage()}
```

### Running in Parallel Mode

When you have registered `@session.task` functions, call `session.run()` with `duration` and `interval`:

```python
experiment = session.run(duration=10.0, interval=0.2)
```

- **duration:** Total time (seconds) to run the session.
- **interval:** Time between acquisitions (seconds).

All background tasks run concurrently with the acquisition loop. When the duration elapses, tasks are automatically signaled to stop.

---

## Complete Example: Parallel Measurement

The source checkout includes a complete offline example with two simulated
power supplies, background tasks, and synthetic ripple data:

```bash
python examples/parallel/parallel_sweep_example.py
```

It reads `examples/parallel/bench_parallel.yaml`. The generated ripple
values demonstrate the acquisition schedule; they are not scope data or
the output of a circuit simulator.

## API Reference

### `session.parameter(name, values, unit=None, notes="")`

- **name:** Parameter name (str)
- **values:** Iterable of values (list, numpy array, etc.)
- **unit:** Optional unit string
- **notes:** Optional description

You can also pass a `StepSpec` from `pytestlab.measurements.step.*` helpers for non-linear sequences (logarithmic, exponential, geometric, or arbitrary generators).

### `@session.acquire`

Decorator for synchronous measurement functions. Functions return a mapping or
one `MeasurementResult`.

### `session.run(...)`

- **Sweep mode:** No arguments needed (runs over parameter grid).
- **Parallel mode:** Use `duration` (seconds) and `interval` (seconds).

Returns an `Experiment` object with `.data` (Polars DataFrame).

---

## Best Practices

- Always use `with` for context management to ensure proper cleanup.
- Use clear, descriptive parameter and measurement names.
- For parallel mode, use `@session.task` decorator for background operations that run concurrently with acquisition.
- Task functions should accept a `stop_event` parameter to enable graceful shutdown.
- Use simulation mode for development and testing.
- Background tasks are automatically managed by the session - no manual thread handling required.

---

## See Also

- [Working with Benches](bench_descriptors.md)
- [Connecting to Instruments](connecting.md)
- [Error Handling](errors.md)
- [10-Minute Tour](../tutorials/10_minute_tour.ipynb)

---
