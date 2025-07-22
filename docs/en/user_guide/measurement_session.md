# Measurement Sessions

The `MeasurementSession` class is the core builder for orchestrating complex measurement workflows in PyTestLab. It provides a high-level, declarative API for defining parameter sweeps, registering measurement functions, and running both sequential and parallel (concurrent) acquisition tasks.

---

## Overview

A `MeasurementSession` manages:

- **Parameters:** Variables to sweep or control (e.g., voltage, frequency, temperature).
- **Instruments:** Devices under test, loaded from a `Bench` or individually.
- **Measurement Functions:** Async functions that acquire data from instruments.
- **Parallel Tasks:** Background coroutines (e.g., stimulus generation) running concurrently with data acquisition.

Sessions can be run as **parameter sweeps** (classic grid search) or in **parallel mode** (continuous acquisition with background tasks).

---

## Basic Usage

### 1. Create a Session

You can create a session directly (no bench required), or (recommended) inherit instruments from a `Bench`:

### Without a Bench (standalone instruments)

```python
import asyncio
from pytestlab import Measurement

async def main():
    async with Measurement() as session:
        # Register instruments directly
        psu = await session.instrument("psu", "keysight/EDU36311A", simulate=True)
        dmm = await session.instrument("dmm", "keysight/34470A", simulate=True)

        # ... define parameters and measurements ...
        pass

asyncio.run(main())
```

### With a Bench

```python
import asyncio
from pytestlab import Bench, Measurement

async def main():
    async with await Bench.open("bench.yaml") as bench:
        async with Measurement(bench=bench) as session:
            # ... define parameters and measurements ...
            pass

asyncio.run(main())
```

### 2. Define Parameters

Parameters define the sweep axes for your experiment:

```python
session.parameter("voltage", [1.0, 2.0, 3.0], unit="V", notes="Supply voltage")
session.parameter("current", [0.1, 0.5, 1.0], unit="A")
```

### 3. Register Measurement Functions

Measurement functions are async coroutines that return a dictionary of results. Use the `@session.acquire` decorator:

```python
@session.acquire
async def measure_voltage(psu, dmm, ctx):
    await psu.channel(1).set(voltage=ctx["voltage"], current_limit=ctx["current"]).on()
    result = await dmm.measure_voltage_dc()
    return {"measured_voltage": result.values}
```

- **Arguments:** Instrument aliases and an optional `ctx` dictionary with current parameter values.
- **Return:** A mapping of result names to values.

### 4. Run the Session

Run the session to perform the sweep:

```python
experiment = await session.run()
print(experiment.data)
```

---

## Parameter Sweep Mode

In sweep mode, the session iterates over all combinations of parameter values, calling each registered measurement function at every point.

**Example:**

#### Without a Bench

```python
import asyncio
from pytestlab import Measurement

async def main():
    async with Measurement() as session:
        psu = await session.instrument("psu", "keysight/EDU36311A", simulate=True)
        dmm = await session.instrument("dmm", "keysight/34470A", simulate=True)

        session.parameter("voltage", [1.0, 2.0, 3.0])
        session.parameter("current", [0.1, 0.5, 1.0])

        @session.acquire
        async def measure(psu, dmm, ctx):
            await psu.channel(1).set(voltage=ctx["voltage"], current_limit=ctx["current"]).on()
            result = await dmm.measure_voltage_dc()
            return {"v_measured": result.values}

        experiment = await session.run()
        print(experiment.data)

asyncio.run(main())
```

#### With a Bench

```python
session.parameter("voltage", [1.0, 2.0, 3.0])
session.parameter("current", [0.1, 0.5, 1.0])

@session.acquire
async def measure(psu, dmm, ctx):
    await psu.channel(1).set(voltage=ctx["voltage"], current_limit=ctx["current"]).on()
    result = await dmm.measure_voltage_dc()
    return {"v_measured": result.values}

experiment = await session.run()
print(experiment.data)
```

- The resulting data is a table (Polars DataFrame) with columns for each parameter and measurement.

---

## Parallel (Concurrent) Mode

For dynamic experiments—such as stress tests, real-time monitoring, or when stimulus and acquisition must run in parallel—use **parallel mode**.

### Registering Background Tasks

Use `@session.task` to register async background coroutines (e.g., ramping a power supply, pulsing a load):

#### Without a Bench

```python
import asyncio
from pytestlab import Measurement

async def main():
    async with Measurement() as session:
        psu = await session.instrument("psu", "keysight/EDU36311A", simulate=True)

        @session.task
        async def psu_ramp(psu):
            while True:
                for v in [1.0, 2.0, 3.0]:
                    await psu.channel(1).set(voltage=v)
                    await asyncio.sleep(0.5)

        # ... define acquisition and run session ...
        # (see below for full example)

asyncio.run(main())
```

#### With a Bench

```python
@session.task
async def psu_ramp(psu):
    while True:
        for v in [1.0, 2.0, 3.0]:
            await psu.channel(1).set(voltage=v)
            await asyncio.sleep(0.5)
```

### Acquisition Function

Register at least one `@session.acquire` function for data collection:

```python
@session.acquire
async def measure(scope):
    await scope._send_command(":SINGle")
    await asyncio.sleep(0.05)
    result = await scope.read_channels(1)
    return {"vpp": result.values}
```

### Running in Parallel Mode

Call `session.run()` with `duration` and `interval`:

```python
experiment = await session.run(duration=10.0, interval=0.2)
```

- **duration:** Total time (seconds) to run the session.
- **interval:** Time between acquisitions (seconds).

All background tasks run concurrently with the acquisition loop. When the duration elapses, tasks are cancelled and the session ends.

---

## Complete Example: Parallel Measurement

### Without a Bench

```python
import asyncio
import numpy as np
from pytestlab import Measurement

async def main():
    async with Measurement() as session:
        psu = await session.instrument("psu", "keysight/EDU36311A", simulate=True)
        load = await session.instrument("load", "keysight/EL33133A", simulate=True)
        scope = await session.instrument("scope", "keysight/DSOX1204G", simulate=True)

        # Background task: PSU voltage ramp
        @session.task
        async def psu_ramp(psu):
            while True:
                for v in np.linspace(1.0, 5.0, 10):
                    await psu.channel(1).set(voltage=v)
                    await asyncio.sleep(0.2)
                for v in np.linspace(5.0, 1.0, 10):
                    await psu.channel(1).set(voltage=v)
                    await asyncio.sleep(0.2)

        # Background task: Pulsed load
        @session.task
        async def load_pulse(load):
            await load.set_mode("CC")
            await load.enable_input(True)
            try:
                while True:
                    await load.set_load(1.0)
                    await asyncio.sleep(0.5)
                    await load.set_load(0.1)
                    await asyncio.sleep(0.5)
            except asyncio.CancelledError:
                await load.enable_input(False)

        # Acquisition: Oscilloscope measurement
        @session.acquire
        async def measure_ripple(scope):
            await scope._send_command(":SINGle")
            await asyncio.sleep(0.05)
            vpp = await scope.measure_voltage_peak_to_peak(1)
            return {"vpp_ripple": vpp.values}

        # Run for 5 seconds, acquire every 250 ms
        experiment = await session.run(duration=5.0, interval=0.25)
        print(experiment.data)

asyncio.run(main())
```

### With a Bench

```python
import asyncio
import numpy as np
from pytestlab import Bench, Measurement

async def main():
    async with await Bench.open("bench_parallel.yaml") as bench:
        async with Measurement(bench=bench) as session:
            # Background task: PSU voltage ramp
            @session.task
            async def psu_ramp(psu):
                while True:
                    for v in np.linspace(1.0, 5.0, 10):
                        await psu.channel(1).set(voltage=v)
                        await asyncio.sleep(0.2)
                    for v in np.linspace(5.0, 1.0, 10):
                        await psu.channel(1).set(voltage=v)
                        await asyncio.sleep(0.2)

            # Background task: Pulsed load
            @session.task
            async def load_pulse(load):
                await load.set_mode("CC")
                await load.enable_input(True)
                try:
                    while True:
                        await load.set_load(1.0)
                        await asyncio.sleep(0.5)
                        await load.set_load(0.1)
                        await asyncio.sleep(0.5)
                except asyncio.CancelledError:
                    await load.enable_input(False)

            # Acquisition: Oscilloscope measurement
            @session.acquire
            async def measure_ripple(scope):
                await scope._send_command(":SINGle")
                await asyncio.sleep(0.05)
                vpp = await scope.measure_voltage_peak_to_peak(1)
                return {"vpp_ripple": vpp.values}

            # Run for 5 seconds, acquire every 250 ms
            experiment = await session.run(duration=5.0, interval=0.25)
            print(experiment.data)

asyncio.run(main())
```

---

## API Reference

### `session.parameter(name, values, unit=None, notes="")`

- **name:** Parameter name (str)
- **values:** Iterable of values (list, numpy array, etc.)
- **unit:** Optional unit string
- **notes:** Optional description

### `@session.acquire`

Decorator for async measurement functions. Functions must return a mapping.

### `@session.task`

Decorator for async background tasks (coroutines). Only available in parallel mode.

### `await session.run(...)`

- **Sweep mode:** No arguments needed (runs over parameter grid).
- **Parallel mode:** Use `duration` (seconds) and `interval` (seconds).

Returns an `Experiment` object with `.data` (Polars DataFrame).

---

## Best Practices

- Always use `async with` for context management to ensure proper cleanup.
- Use clear, descriptive parameter and measurement names.
- For parallel mode, ensure all background tasks are async and handle `asyncio.CancelledError` for graceful shutdown.
- Use simulation mode for development and testing.

---

## See Also

- [Async vs. Sync Programming](async_vs_sync.md)
- [Working with Benches](bench_descriptors.md)
- [Connecting to Instruments](connecting.md)
- [Error Handling](errors.md)
- [10-Minute Tour](../tutorials/10_minute_tour.ipynb)

---