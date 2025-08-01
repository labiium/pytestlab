# Synchronous by Design

PyTestLab is designed with a **synchronous-first** approach to instrument control and data acquisition. This guide explains the benefits of the synchronous design, how it simplifies your workflows, and best practices for using PyTestLab effectively.

---

## Why Synchronous?

Laboratory instrument control involves precise, sequential operations where timing and order matter. A synchronous programming model provides:

- **Simplicity:** No need to understand async/await concepts or event loops
- **Predictability:** Code executes in the order written, making debugging straightforward
- **Clarity:** Stack traces are clean and easy to follow
- **Compatibility:** Works seamlessly with any Python environment or framework

PyTestLab's synchronous API ensures your code is readable, maintainable, and accessible to engineers of all Python skill levels.

---

## Synchronous in PyTestLab

All instrument methods in PyTestLab are **synchronous functions**. You call them directly without special syntax.

### Example: Synchronous Oscilloscope Measurement

```python   
import pytestlab

def measure_waveform():
    # Create and connect to a simulated oscilloscope
    scope = pytestlab.AutoInstrument.from_config(
        "keysight/DSOX1204G",
        simulate=True
    )
    scope.connect_backend()

    # Configure channel and trigger
    scope.channel(1).setup(scale=0.5, offset=0).enable()
    scope.trigger.setup_edge(source="CH1", level=0.25)

    # Acquire waveform
    result = scope.read_channels(1)
    print("Captured waveform data:")
    print(result.values.head())

    scope.close()

if __name__ == "__main__":
    measure_waveform()
```

In this example, every instrument operation (`connect_backend`, `setup`, `read_channels`, etc.) is a direct function call that executes immediately.

---

## Using PyTestLab in Different Environments

### In a Script

Simply define your functions and call them:

```python
import pytestlab

def main():
    # ... your instrument control code ...
    pass

if __name__ == "__main__":
    main()
```

### In a Jupyter Notebook or IPython

Use PyTestLab directly in cells without any special setup:

```python
import pytestlab

scope = pytestlab.AutoInstrument.from_config("keysight/DSOX1204G", simulate=True)
scope.connect_backend()
scope.channel(1).setup(scale=0.2).enable()
result = scope.read_channels(1)
print(result.values.head())
scope.close()
```

### In Test Suites

PyTestLab works seamlessly with pytest and other testing frameworks:

```python
import pytest
import pytestlab

def test_instrument_connection():
    scope = pytestlab.AutoInstrument.from_config("keysight/DSOX1204G", simulate=True)
    scope.connect_backend()
    
    # Test operations
    scope.channel(1).setup(scale=0.5).enable()
    result = scope.read_channels(1)
    
    assert result is not None
    scope.close()
```

---

## Performance and Efficiency

### Optimized Communication

PyTestLab's synchronous design doesn't sacrifice performance:

- **Intelligent Batching:** Related commands are automatically batched for efficiency
- **Connection Pooling:** Instruments maintain persistent connections
- **Caching:** Frequently accessed instrument state is cached
- **Direct Execution:** No event loop overhead or coroutine management

### Example: Efficient Batch Operations

```python
# This automatically batches related operations for optimal performance
scope.channel(1).setup(scale=0.5, offset=0, coupling="DC").enable()
scope.channel(2).setup(scale=1.0, offset=0, coupling="DC").enable()
scope.trigger.setup_edge(source="CH1", level=0.2)

# Single efficient data acquisition
data = scope.read_channels([1, 2])
```

---

## Best Practices

### 1. Use Context Managers

Always use context managers for automatic resource cleanup:

```python
from pytestlab import Bench

def measurement_with_safety():
    with Bench.open("config.yaml") as bench:
        # All instruments are automatically managed
        voltage = bench.dmm.measure_voltage_dc()
        bench.psu.channel(1).set_voltage(3.3)
        
        # Automatic cleanup happens here
```

### 2. Leverage Facade Patterns

Use PyTestLab's chainable facade methods for readable code:

```python
# Power supply configuration
psu.channel(1).set(voltage=3.3, current_limit=0.5).on()

# Oscilloscope setup
scope.channel(1).setup(scale=0.5, coupling="DC").enable()
scope.trigger.setup_edge(source="CH1", level=0.2)

# Waveform generator configuration
wgen.channel(1).setup_sine(frequency=1e3, amplitude=1.0).enable()
```

### 3. Use Measurement Sessions for Complex Experiments

For parameter sweeps and structured data collection:

```python
from pytestlab.measurements import MeasurementSession

def iv_characterization():
    with MeasurementSession("Diode IV Curve") as session:
        session.parameter("voltage", range(0, 3, 0.1), unit="V")
        
        @session.acquire
        def measure_current(psu, dmm, voltage):
            psu.channel(1).set_voltage(voltage)
            return {"current": dmm.measure_current_dc()}
        
        results = session.run()
        return results.data
```

---

## Migration from Async Code

If you have existing async instrument control code, migration is straightforward:

### Before (Generic Async Pattern)
```python
import asyncio

async def old_measurement():
    instrument = await some_async_connect()
    await instrument.configure()
    result = await instrument.measure()
    await instrument.close()

asyncio.run(old_measurement())
```

### After (PyTestLab Synchronous)
```python
import pytestlab

def new_measurement():
    instrument = pytestlab.AutoInstrument.from_config("profile", simulate=True)
    instrument.connect_backend()
    instrument.configure()
    result = instrument.measure()
    instrument.close()

new_measurement()
```

**Migration Steps:**
1. Remove `async`/`await` keywords
2. Remove `asyncio` imports and `asyncio.run()` calls
3. Replace async instrument libraries with PyTestLab equivalents
4. Update function definitions to be synchronous

---

## Error Handling

Synchronous code makes error handling straightforward:

```python
def robust_measurement():
    instruments = []
    try:
        # Setup instruments
        scope = pytestlab.AutoInstrument.from_config("keysight/DSOX1204G", simulate=True)
        scope.connect_backend()
        instruments.append(scope)
        
        psu = pytestlab.AutoInstrument.from_config("keysight/E36311A", simulate=True)
        psu.connect_backend()
        instruments.append(psu)
        
        # Perform measurements
        psu.channel(1).set_voltage(3.3)
        scope.trigger.single()
        data = scope.read_channels(1)
        
        return data
        
    except Exception as e:
        print(f"Measurement failed: {e}")
        return None
        
    finally:
        # Cleanup
        for instrument in instruments:
            try:
                instrument.close()
            except Exception as e:
                print(f"Cleanup error: {e}")
```

---

## FAQ

### Is synchronous code slower than async?

For typical lab automation, **no**. PyTestLab's synchronous design includes optimizations like command batching and connection pooling that ensure excellent performance. The elimination of async overhead often makes it faster.

### Can I still do parallel operations?

Yes! Use Python's standard libraries:
- **Threading:** For I/O-bound parallel operations
- **Multiprocessing:** For CPU-bound parallel tasks
- **Concurrent.futures:** For managed parallel execution

```python
from concurrent.futures import ThreadPoolExecutor
import pytestlab

def measure_channel(channel_num):
    scope = pytestlab.AutoInstrument.from_config("keysight/DSOX1204G", simulate=True)
    scope.connect_backend()
    result = scope.read_channels(channel_num)
    scope.close()
    return result

# Parallel measurements
with ThreadPoolExecutor() as executor:
    futures = [executor.submit(measure_channel, ch) for ch in [1, 2, 3, 4]]
    results = [f.result() for f in futures]
```

### What about real-time applications?

PyTestLab's synchronous design is excellent for real-time applications because:
- Predictable execution timing
- No event loop scheduling delays
- Direct hardware communication
- Deterministic resource management

---

## Summary

PyTestLab's synchronous design provides:

✅ **Simplicity** - Easy to learn and use  
✅ **Reliability** - Predictable execution and error handling  
✅ **Performance** - Optimized communication without async overhead  
✅ **Compatibility** - Works in any Python environment  
✅ **Maintainability** - Clean, readable code that's easy to debug  

For more practical examples, see the [10-Minute Tour](../tutorials/10_minute_tour.ipynb) and the [Getting Started Guide](getting_started.md).