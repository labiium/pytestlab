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

### 3. Register Measurement Functions

Measurement functions are synchronous functions that return a dictionary of results. Use the `@session.acquire` decorator:

```python
@session.acquire
def measure_voltage(psu, dmm, voltage, current):
    psu.channel(1).set(voltage=voltage, current_limit=current).on()
    result = dmm.measure_voltage_dc()
    return {"measured_voltage": result.values}
```

- **Arguments:** Instrument aliases and parameter values as individual arguments.
- **Return:** A mapping of result names to values.

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
            result = dmm.measure_voltage_dc()
            return {"v_measured": result.values}

        experiment = session.run()
        print(experiment.data)

main()
```

#### With a Bench

```python
session.parameter("voltage", [1.0, 2.0, 3.0])
session.parameter("current", [0.1, 0.5, 1.0])

@session.acquire
def measure(psu, dmm, voltage, current):
    psu.channel(1).set(voltage=voltage, current_limit=current).on()
    result = dmm.measure_voltage_dc()
    return {"v_measured": result.values}

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
                    psu.channel(1).set_voltage(v)
                    time.sleep(0.5)

        # The task will automatically start when session.run() is called
        # (see below for full example)
```

### Acquisition Function

Register at least one `@session.acquire` function for data collection:

```python
@session.acquire
def measure(scope):
    scope._send_command(":SINGle")
    time.sleep(0.05)
    result = scope.read_channels(1)
    return {"vpp": result.values}
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

### Without a Bench

```python
import time
import numpy as np
from pytestlab.measurements import MeasurementSession

def main():
    with MeasurementSession() as session:
        psu = session.instrument("psu", "keysight/EDU36311A", simulate=True)
        load = session.instrument("load", "keysight/EL33133A", simulate=True)
        scope = session.instrument("scope", "keysight/DSOX1204G", simulate=True)

        # Background task: PSU voltage ramp
        @session.task
        def psu_ramp(psu, stop_event):
            while not stop_event.is_set():
                for v in np.linspace(1.0, 5.0, 10):
                    if stop_event.is_set():
                        break
                    psu.channel(1).set_voltage(v)
                    time.sleep(0.2)
                for v in np.linspace(5.0, 1.0, 10):
                    if stop_event.is_set():
                        break
                    psu.channel(1).set_voltage(v)
                    time.sleep(0.2)

        # Background task: Pulsed load
        @session.task
        def load_pulse(load, stop_event):
            load.set_mode("CC")
            load.enable_input(True)
            try:
                while not stop_event.is_set():
                    load.set_load(1.0)
                    time.sleep(0.5)
                    if stop_event.is_set():
                        break
                    load.set_load(0.1)
                    time.sleep(0.5)
            finally:
                load.enable_input(False)

        # Acquisition: Oscilloscope measurement
        @session.acquire
        def measure_ripple(scope):
            scope._send_command(":SINGle")
            time.sleep(0.05)
            vpp = scope.measure_voltage_peak_to_peak(1)
            return {"vpp_ripple": vpp.values}

        # Run for 5 seconds, acquire every 250 ms
        # Background tasks start automatically and stop when duration expires
        experiment = session.run(duration=5.0, interval=0.25)
        print(experiment.data)

main()
```

### With a Bench

```python
import time
import numpy as np
from pytestlab import Bench
from pytestlab.measurements import MeasurementSession

def main():
    with Bench.open("bench_parallel.yaml") as bench:
        with MeasurementSession(bench=bench) as session:
            # Background task: PSU voltage ramp
            @session.task
            def psu_ramp(psu, stop_event):
                while not stop_event.is_set():
                    for v in np.linspace(1.0, 5.0, 10):
                        if stop_event.is_set():
                            break
                        psu.channel(1).set_voltage(v)
                        time.sleep(0.2)
                    for v in np.linspace(5.0, 1.0, 10):
                        if stop_event.is_set():
                            break
                        psu.channel(1).set_voltage(v)
                        time.sleep(0.2)

            # Background task: Pulsed load
            @session.task
            def load_pulse(load, stop_event):
                load.set_mode("CC")
                load.enable_input(True)
                try:
                    while not stop_event.is_set():
                        load.set_load(1.0)
                        time.sleep(0.5)
                        if stop_event.is_set():
                            break
                        load.set_load(0.1)
                        time.sleep(0.5)
                finally:
                    load.enable_input(False)

            # Acquisition: Oscilloscope measurement
            @session.acquire
            def measure_ripple(scope):
                scope._send_command(":SINGle")
                time.sleep(0.05)
                vpp = scope.measure_voltage_peak_to_peak(1)
                return {"vpp_ripple": vpp.values}

            # Run for 5 seconds, acquire every 250 ms
            # Background tasks start automatically and stop when duration expires
            experiment = session.run(duration=5.0, interval=0.25)
            print(experiment.data)

main()
```

---

## API Reference

### `session.parameter(name, values, unit=None, notes="")`

- **name:** Parameter name (str)
- **values:** Iterable of values (list, numpy array, etc.)
- **unit:** Optional unit string
- **notes:** Optional description

### `@session.acquire`

Decorator for synchronous measurement functions. Functions must return a mapping.

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

- [Synchronous Design](async_vs_sync.md)
- [Working with Benches](bench_descriptors.md)
- [Connecting to Instruments](connecting.md)
- [Error Handling](errors.md)
- [10-Minute Tour](../tutorials/10_minute_tour.ipynb)

---