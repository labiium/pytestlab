# PyTestLab Migration Guide: Async to Sync

This guide provides a comprehensive migration path from PyTestLab's async API to the new synchronous API. The synchronous API offers simplified usage patterns while maintaining all the powerful features you rely on.

## Table of Contents

1. [Overview](#overview)
2. [Quick Reference](#quick-reference)
3. [Step-by-Step Migration](#step-by-step-migration)
4. [Common Patterns](#common-patterns)
5. [API Changes](#api-changes)
6. [Performance Considerations](#performance-considerations)
7. [Testing Your Migration](#testing-your-migration)
8. [Troubleshooting](#troubleshooting)

## Overview

### What Changed

- **No more `async`/`await`**: All PyTestLab methods are now synchronous
- **No more `asyncio`**: Remove all asyncio imports and `asyncio.run()` calls
- **Simplified context managers**: Use `with` instead of `async with`
- **Direct function calls**: Call methods directly without `await`

### What Stayed the Same

- **All functionality preserved**: Instruments, measurements, safety limits, and data handling
- **Same method names**: API surface remains identical (just sync)
- **Same configuration**: YAML configs, instrument profiles, and addresses unchanged
- **Same data structures**: DataFrames, measurement results, and error handling unchanged

## Quick Reference

### Before (Async)
```python
import asyncio
import pytestlab

async def main():
    async with await pytestlab.Bench.open("config.yaml") as bench:
        result = await bench.dmm.measure_voltage_dc()
        await bench.psu.channel(1).set_voltage(5.0)

asyncio.run(main())
```

### After (Sync)
```python
import pytestlab

def main():
    with pytestlab.Bench.open("config.yaml") as bench:
        result = bench.dmm.measure_voltage_dc()
        bench.psu.channel(1).set_voltage(5.0)

main()
```

## Step-by-Step Migration

### Step 1: Remove Asyncio Imports

**Before:**
```python
import asyncio
import pytestlab
```

**After:**
```python
import pytestlab
```

### Step 2: Convert Function Definitions

**Before:**
```python
async def run_experiment():
    # experiment code
```

**After:**
```python
def run_experiment():
    # experiment code
```

### Step 3: Update Context Managers

**Before:**
```python
async with await pytestlab.Bench.open("config.yaml") as bench:
    # work with bench
```

**After:**
```python
with pytestlab.Bench.open("config.yaml") as bench:
    # work with bench
```

### Step 4: Remove Await Keywords

**Before:**
```python
voltage = await bench.dmm.measure_voltage_dc()
await bench.psu.channel(1).set_voltage(5.0)
data = await scope.read_channels([1, 2])
```

**After:**
```python
voltage = bench.dmm.measure_voltage_dc()
bench.psu.channel(1).set_voltage(5.0)
data = scope.read_channels([1, 2])
```

### Step 5: Replace asyncio.run() Calls

**Before:**
```python
asyncio.run(main())
```

**After:**
```python
main()
```

### Step 6: Update Measurement Sessions

**Before:**
```python
async def run_sweep():
    async with MeasurementSession("IV Curve") as meas:
        @meas.acquire
        async def measure_current(dmm, psu, voltage):
            await psu.set_voltage(voltage)
            return await dmm.measure_current_dc()
        
        results = await meas.run()
```

**After:**
```python
def run_sweep():
    with MeasurementSession("IV Curve") as meas:
        @meas.acquire
        def measure_current(dmm, psu, voltage):
            psu.set_voltage(voltage)
            return dmm.measure_current_dc()
        
        results = meas.run()
```

## Common Patterns

### Pattern 1: Instrument Connection and Usage

**Before:**
```python
async def test_instrument():
    scope = AutoInstrument.from_config("keysight/DSOX1204G", simulate=True)
    await scope.connect_backend()
    
    await scope.channel(1).setup(scale=0.5).enable()
    await scope.trigger.setup_edge(source="CH1", level=0.2)
    
    trace = await scope.read_channels(1)
    await scope.close()
```

**After:**
```python
def test_instrument():
    scope = AutoInstrument.from_config("keysight/DSOX1204G", simulate=True)
    scope.connect_backend()
    
    scope.channel(1).setup(scale=0.5).enable()
    scope.trigger.setup_edge(source="CH1", level=0.2)
    
    trace = scope.read_channels(1)
    scope.close()
```

### Pattern 2: Bench Configuration with Safety Limits

**Before:**
```python
async def bench_test():
    async with await pytestlab.Bench.open("bench.yaml") as bench:
        try:
            await bench.psu.channel(1).set_voltage(7.0)  # Above safety limit
        except SafetyLimitError as e:
            print(f"Safety limit enforced: {e}")
        
        voltage = await bench.dmm.measure_voltage_dc()
        print(f"Measured: {voltage.values:.4f} {voltage.units}")
```

**After:**
```python
def bench_test():
    with pytestlab.Bench.open("bench.yaml") as bench:
        try:
            bench.psu.channel(1).set_voltage(7.0)  # Above safety limit
        except SafetyLimitError as e:
            print(f"Safety limit enforced: {e}")
        
        voltage = bench.dmm.measure_voltage_dc()
        print(f"Measured: {voltage.values:.4f} {voltage.units}")
```

### Pattern 3: Complex Parameter Sweeps

**Before:**
```python
async def parameter_sweep():
    async with MeasurementSession("MOSFET Characterization") as meas:
        meas.instrument("psu", "keysight/EDU36311A", address="...")
        meas.instrument("dmm", "keysight/34470A", address="...")
        
        meas.parameter("v_gate", range(0, 5, 0.5), unit="V")
        meas.parameter("v_drain", [0.1, 1.0, 5.0], unit="V")
        
        @meas.acquire
        async def drain_current(psu, dmm, v_gate, v_drain):
            await psu.channel(1).set_voltage(v_gate)
            await psu.channel(2).set_voltage(v_drain)
            return await dmm.measure_current_dc()
        
        results = await meas.run()
        analysis = await meas.analyze()
        await meas.save("mosfet_iv_data.h5")
```

**After:**
```python
def parameter_sweep():
    with MeasurementSession("MOSFET Characterization") as meas:
        meas.instrument("psu", "keysight/EDU36311A", address="...")
        meas.instrument("dmm", "keysight/34470A", address="...")
        
        meas.parameter("v_gate", range(0, 5, 0.5), unit="V")
        meas.parameter("v_drain", [0.1, 1.0, 5.0], unit="V")
        
        @meas.acquire
        def drain_current(psu, dmm, v_gate, v_drain):
            psu.channel(1).set_voltage(v_gate)
            psu.channel(2).set_voltage(v_drain)
            return dmm.measure_current_dc()
        
        results = meas.run()
        analysis = meas.analyze()
        meas.save("mosfet_iv_data.h5")
```

### Pattern 4: Error Handling and Cleanup

**Before:**
```python
async def robust_measurement():
    instruments = []
    try:
        scope = AutoInstrument.from_config("tek/MSO64", address="...")
        await scope.connect_backend()
        instruments.append(scope)
        
        psu = AutoInstrument.from_config("keysight/EDU36311A", address="...")
        await psu.connect_backend()
        instruments.append(psu)
        
        # Perform measurements
        await scope.trigger.single()
        trace = await scope.read_channels([1, 2])
        
    except Exception as e:
        print(f"Measurement failed: {e}")
    finally:
        for instr in instruments:
            await instr.close()
```

**After:**
```python
def robust_measurement():
    instruments = []
    try:
        scope = AutoInstrument.from_config("tek/MSO64", address="...")
        scope.connect_backend()
        instruments.append(scope)
        
        psu = AutoInstrument.from_config("keysight/EDU36311A", address="...")
        psu.connect_backend()
        instruments.append(psu)
        
        # Perform measurements
        scope.trigger.single()
        trace = scope.read_channels([1, 2])
        
    except Exception as e:
        print(f"Measurement failed: {e}")
    finally:
        for instr in instruments:
            instr.close()
```

## API Changes

### Core Classes

| Component | Async Method | Sync Method | Notes |
|-----------|--------------|-------------|-------|
| `Bench` | `await Bench.open()` | `Bench.open()` | Returns context manager directly |
| `AutoInstrument` | `await instr.connect_backend()` | `instr.connect_backend()` | Direct call |
| `MeasurementSession` | `async with MeasurementSession()` | `with MeasurementSession()` | Context manager |

### Instrument Operations

| Operation | Async | Sync |
|-----------|-------|------|
| Connect | `await instr.connect_backend()` | `instr.connect_backend()` |
| Configure | `await instr.channel(1).setup(...)` | `instr.channel(1).setup(...)` |
| Measure | `await instr.measure_voltage_dc()` | `instr.measure_voltage_dc()` |
| Set Value | `await instr.set_voltage(5.0)` | `instr.set_voltage(5.0)` |
| Read Data | `await instr.read_channels([1,2])` | `instr.read_channels([1,2])` |
| Close | `await instr.close()` | `instr.close()` |

### Measurement Sessions

| Operation | Async | Sync |
|-----------|-------|------|
| Create | `async with MeasurementSession()` | `with MeasurementSession()` |
| Acquire Function | `async def acquire(...)` | `def acquire(...)` |
| Run | `await meas.run()` | `meas.run()` |
| Analyze | `await meas.analyze()` | `meas.analyze()` |
| Save | `await meas.save()` | `meas.save()` |

## Performance Considerations

### What You Gain

1. **Simplified Code**: No async/await complexity
2. **Easier Debugging**: Standard synchronous stack traces
3. **Better IDE Support**: Full autocomplete and static analysis
4. **Reduced Memory Overhead**: No event loop or coroutine objects

### What You Lose

1. **Explicit Concurrency**: Can't easily run multiple instruments in parallel
2. **Non-blocking I/O**: Operations block until complete

### Performance Tips

1. **Use Batch Operations**: Many instruments support batched commands
```python
# Good: Batch multiple channel configurations
scope.channels([1, 2, 3]).setup(scale=0.5, offset=0).enable()

# Less efficient: Individual calls
scope.channel(1).setup(scale=0.5, offset=0).enable()
scope.channel(2).setup(scale=0.5, offset=0).enable()
scope.channel(3).setup(scale=0.5, offset=0).enable()
```

2. **Optimize Measurement Sessions**: Use vectorized parameters
```python
# Good: Single session with parameter sweep
meas.parameter("voltage", np.linspace(0, 5, 50))

# Less efficient: Multiple individual measurements
for v in np.linspace(0, 5, 50):
    # individual measurement calls
```

3. **Connection Pooling**: Reuse instrument connections
```python
# Good: Use context managers for automatic cleanup
with pytestlab.Bench.open("config.yaml") as bench:
    # Multiple operations with same instruments
    
# Less efficient: Repeated connect/disconnect
```

## Testing Your Migration

### Unit Tests

Update your test functions:

**Before:**
```python
import pytest

@pytest.mark.asyncio
async def test_voltage_measurement():
    async with await pytestlab.Bench.open("test_config.yaml") as bench:
        voltage = await bench.dmm.measure_voltage_dc()
        assert voltage.values > 0
```

**After:**
```python
import pytest

def test_voltage_measurement():
    with pytestlab.Bench.open("test_config.yaml") as bench:
        voltage = bench.dmm.measure_voltage_dc()
        assert voltage.values > 0
```

### Integration Tests

**Before:**
```python
@pytest.mark.asyncio
async def test_full_experiment():
    async with MeasurementSession("Test") as meas:
        # setup and run experiment
        results = await meas.run()
        assert len(results) > 0
```

**After:**
```python
def test_full_experiment():
    with MeasurementSession("Test") as meas:
        # setup and run experiment
        results = meas.run()
        assert len(results) > 0
```

### Performance Tests

Verify that timing-critical operations still meet requirements:

```python
import time

def test_measurement_speed():
    start_time = time.time()
    
    with pytestlab.Bench.open("config.yaml") as bench:
        for i in range(100):
            voltage = bench.dmm.measure_voltage_dc()
    
    elapsed = time.time() - start_time
    assert elapsed < 10.0  # Should complete within 10 seconds
```

## Troubleshooting

### Common Migration Issues

#### Issue: "AttributeError: 'coroutine' object has no attribute '...'"
**Cause**: Forgot to remove `await` keyword
**Solution**: Remove `await` from the method call

**Before:**
```python
result = bench.dmm.measure_voltage_dc()  # Missing await in old version
```

**After:**
```python
result = bench.dmm.measure_voltage_dc()  # Direct call in new version
```

#### Issue: "TypeError: 'async with' requires an object with __aenter__ and __aexit__ methods"
**Cause**: Using `async with` instead of `with`
**Solution**: Remove `async` keyword

**Before:**
```python
async with pytestlab.Bench.open("config.yaml") as bench:
```

**After:**
```python
with pytestlab.Bench.open("config.yaml") as bench:
```

#### Issue: "'await' outside async function"
**Cause**: Forgot to remove `await` keyword
**Solution**: Remove all `await` keywords

#### Issue: Tests hanging or timing out
**Cause**: May have missed updating some async test decorators
**Solution**: Remove `@pytest.mark.asyncio` decorators

### Debugging Tips

1. **Use Print Statements**: Add logging to track execution flow
```python
def debug_measurement():
    print("Opening bench...")
    with pytestlab.Bench.open("config.yaml") as bench:
        print("Bench opened successfully")
        voltage = bench.dmm.measure_voltage_dc()
        print(f"Voltage measured: {voltage}")
```

2. **Check Instrument Status**: Verify instruments are responsive
```python
with pytestlab.Bench.open("config.yaml") as bench:
    status = bench.dmm.get_status()
    print(f"DMM Status: {status}")
```

3. **Validate Configuration**: Ensure YAML configs are still correct
```python
import yaml

with open("config.yaml") as f:
    config = yaml.safe_load(f)
    print(f"Config loaded: {config}")
```

## Parallel Task Migration

### Background Tasks with @session.task

The `@session.task` decorator for parallel execution is preserved but uses threading instead of asyncio.

**Before (Async):**
```python
@session.task
async def psu_ramp(psu):
    while True:
        for v in [1.0, 2.0, 3.0]:
            await psu.channel(1).set_voltage(v)
            await asyncio.sleep(0.5)
```

**After (Sync):**
```python
@session.task
def psu_ramp(psu, stop_event):
    while not stop_event.is_set():
        for v in [1.0, 2.0, 3.0]:
            if stop_event.is_set():
                break
            psu.channel(1).set_voltage(v)
            time.sleep(0.5)
```

**Key Changes:**
- Remove `async` keyword from task functions
- Add `stop_event` parameter for graceful shutdown
- Replace `await` with direct calls
- Replace `asyncio.sleep()` with `time.sleep()`
- Check `stop_event.is_set()` in loops for clean termination

**Usage Example:**
```python
with MeasurementSession("Parallel Test") as session:
    psu = session.instrument("psu", "keysight/E36311A", simulate=True)
    
    @session.task
    def background_stimulus(psu, stop_event):
        while not stop_event.is_set():
            # Your stimulus code here
            psu.channel(1).set_voltage(3.3)
            time.sleep(1.0)
            if stop_event.is_set():
                break
            psu.channel(1).set_voltage(5.0)
            time.sleep(1.0)
    
    @session.acquire
    def measure_response(dmm):
        return {"voltage": dmm.measure_voltage_dc()}
    
    # Run with parallel execution
    experiment = session.run(duration=10.0, interval=0.2)
```

## Migration Checklist

- [ ] Remove all `import asyncio` statements
- [ ] Convert all `async def` to `def`
- [ ] Replace `async with await` with `with`
- [ ] Remove all `await` keywords
- [ ] Replace `asyncio.run()` with direct function calls
- [ ] Update test decorators (remove `@pytest.mark.asyncio`)
- [ ] Update measurement session acquire functions
- [ ] Update @session.task functions to use stop_event parameter
- [ ] Replace asyncio.sleep() with time.sleep() in task functions
- [ ] Test all critical measurement paths including parallel execution
- [ ] Verify performance meets requirements
- [ ] Update documentation and comments

## Getting Help

If you encounter issues during migration:

1. Check this guide for common patterns
2. Review the API documentation for the latest method signatures
3. Test with simulation mode first (`simulate=True`)
4. Use logging to debug connection and timing issues
5. Open an issue on GitHub with minimal reproduction code

The synchronous API provides the same powerful capabilities as the async version with simplified usage patterns. Take your time with the migration and test thoroughly to ensure your measurement workflows continue to work correctly.