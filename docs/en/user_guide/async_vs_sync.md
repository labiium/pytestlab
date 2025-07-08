# Asynchronous by Design

PyTestLab is designed with an **asynchronous-first** approach to instrument control and data acquisition. This guide explains why async is the default, how it benefits your workflows, and how to use async code in both scripts and notebooks.

---

## Why Async?

Interacting with laboratory instruments is fundamentally **I/O-bound**: every command you send to a device involves waiting for a response. In a synchronous program, this waiting blocks your entire application, making it unresponsive and inefficient—especially when controlling multiple instruments.

**Asynchronous programming** (using Python's `asyncio`) allows your code to perform other tasks while waiting for I/O to complete. This is crucial for:

- **Responsiveness:** GUIs and CLIs remain interactive while instruments are busy.
- **Concurrency:** Easily coordinate multiple instruments in parallel.
- **Efficiency:** Lower memory and CPU usage compared to threads or processes.

---

## Async in PyTestLab

All instrument methods that involve I/O are **async functions** (coroutines). You must use the `await` keyword to call them.

### Example: Async Oscilloscope Measurement

```python title="Async Oscilloscope Example"
import asyncio
import pytestlab

async def measure_waveform():
    # Create and connect to a simulated oscilloscope
    scope = await pytestlab.AutoInstrument.from_config(
        "keysight/DSOX1204G",
        simulate=True
    )
    await scope.connect_backend()

    # Configure channel and trigger
    await scope.channel(1).setup(scale=0.5, offset=0).enable()
    await scope.trigger.setup_edge(source="CH1", level=0.25)

    # Acquire waveform
    result = await scope.read_channels(1)
    print("Captured waveform data:")
    print(result.values.head())

    await scope.close()

if __name__ == "__main__":
    asyncio.run(measure_waveform())
```

In this example, every instrument operation (`connect_backend`, `setup`, `read_channels`, etc.) is asynchronous and must be awaited.

---

## Using Async in Different Environments

### In a Script

Use `asyncio.run()` to execute your main async function:

```python
import asyncio

async def main():
    # ... your async code ...
    pass

if __name__ == "__main__":
    asyncio.run(main())
```

### In a Jupyter Notebook or IPython

Modern Jupyter and IPython support **top-level await**. You can simply write:

```python
import pytestlab

scope = await pytestlab.AutoInstrument.from_config("keysight/DSOX1204G", simulate=True)
await scope.connect_backend()
await scope.channel(1).setup(scale=0.2).enable()
result = await scope.read_channels(1)
print(result.values.head())
await scope.close()
```

If you see `SyntaxError: 'await' outside function`, your environment may not support top-level await. In that case, define an async function and use `await` inside it, or use `nest_asyncio` to patch the event loop.

---

## Migrating Synchronous Scripts

If you have old synchronous scripts, migrate them by:

1. Changing all instrument I/O calls to `await` their async versions.
2. Wrapping your main logic in an `async def` function.
3. Running your code with `asyncio.run()`.

**Synchronous (not supported):**
```python
# This will NOT work with PyTestLab!
def measure_sync():
    osc = SomeSyncOscilloscope()
    osc.connect()
    osc.setup_acquisition()
    waveform = osc.read_waveform()
    print(waveform)
    osc.disconnect()
```

**Asynchronous (PyTestLab way):**
```python
import asyncio
import pytestlab

async def measure_async():
    osc = await pytestlab.AutoInstrument.from_config("keysight/DSOX1204G", simulate=True)
    await osc.connect_backend()
    await osc.channel(1).setup(scale=0.5).enable()
    result = await osc.read_channels(1)
    print(result.values.head())
    await osc.close()

asyncio.run(measure_async())
```

---

## FAQ

### Why not threads or processes?

Async I/O is lighter, safer, and easier to reason about for I/O-bound tasks. It avoids the complexity and overhead of threads, and is ideal for controlling many instruments concurrently.

### Can I use PyTestLab synchronously?

No. All instrument I/O is async by design. This ensures your code is robust, scalable, and ready for modern lab automation.

### What if I need to call async code from sync code?

You must use an event loop. In scripts, use `asyncio.run()`. In notebooks, use top-level `await` or an async function.

---

For more practical examples, see the [10-Minute Tour](../../tutorials/10_minute_tour.ipynb) and the [Getting Started Guide](getting_started.md).