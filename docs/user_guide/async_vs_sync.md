# Synchronous vs. Asynchronous Programming in PyTestLab

PyTestLab is designed with an asynchronous-first approach to handle the complexities of interacting with laboratory instruments. This guide explains the difference between synchronous and asynchronous programming and why PyTestLab prefers the latter.

## Why an Async-First Design?

Interacting with hardware is often an I/O-bound operation. When you send a command to an instrument, your program has to wait for the instrument to process the command and send a response. In a traditional synchronous program, this waiting time blocks the entire program, making it unresponsive.

Asynchronous programming, using Python's `asyncio` library, allows your program to perform other tasks while waiting for I/O operations to complete. This is particularly beneficial in a lab environment where you might be coordinating multiple instruments, updating a user interface, or processing data in the background.

**Key benefits of async in PyTestLab:**

*   **Improved Responsiveness:** Your application's GUI or command-line interface remains responsive while waiting for instruments.
*   **Concurrent Operations:** Easily manage multiple instruments at once without complex threading code.
*   **Resource Efficiency:** Async I/O can handle many concurrent operations with lower memory overhead than traditional threading models.

## Using `async`/`await` with PyTestLab Instruments

All instrument methods in PyTestLab that involve I/O are `async` functions. This means you need to use the `await` keyword to call them.

Here is a simple example of how to connect to an oscilloscope and read a waveform:

```python
import asyncio
from pytestlab.instruments import Oscilloscope

async def measure_waveform():
    # Connect to the oscilloscope
    osc = Oscilloscope(address="TCPIP0::localhost::inst0::INSTR")
    await osc.connect()

    # Configure the instrument
    await osc.setup_acquisition(channel=1, time_range=1e-3, voltage_range=5.0)

    # Read the waveform
    waveform = await osc.read_waveform(channel=1)
    print("Captured waveform:", waveform)

    # Disconnect
    await osc.disconnect()

if __name__ == "__main__":
    asyncio.run(measure_waveform())
```

In this example, `osc.connect()`, `osc.setup_acquisition()`, and `osc.read_waveform()` are all asynchronous calls that perform I/O. The `await` keyword pauses the `measure_waveform` function and allows the `asyncio` event loop to run other tasks until the instrument operation is complete.

## Migrating Synchronous Scripts to Async

If you have existing synchronous scripts, you'll need to make some changes to use them with PyTestLab.

1.  **Make your functions `async`:** Any function that calls a PyTestLab instrument method must be defined with `async def`.
2.  **Use `await`:** Add `await` before every call to a PyTestLab instrument method.
3.  **Run the async code:** Use `asyncio.run()` to start your top-level `async` function.

**Synchronous (Old Way - Not for PyTestLab I/O):**

```python
# This is a conceptual example and will not work with PyTestLab
def measure_sync():
    osc = SomeSyncOscilloscope()
    osc.connect()
    osc.setup_acquisition()
    waveform = osc.read_waveform()
    print(waveform)
    osc.disconnect()

measure_sync()
```

**Asynchronous (PyTestLab Way):**

```python
import asyncio
from pytestlab.instruments import Oscilloscope

async def measure_async():
    osc = Oscilloscope(address="TCPIP0::localhost::inst0::INSTR")
    await osc.connect()
    await osc.setup_acquisition(channel=1, time_range=1e-3, voltage_range=5.0)
    waveform = await osc.read_waveform(channel=1)
    print(waveform)
    await osc.disconnect()

asyncio.run(measure_async())
```

## Frequently Asked Questions (FAQ)

### Why async?

As explained above, an asynchronous design prevents your application from blocking when communicating with slow hardware. This leads to better performance and responsiveness, especially when controlling multiple instruments concurrently. It's a modern approach to I/O-bound tasks that fits perfectly with the needs of a test and measurement environment.

### How do I use this in a Jupyter Notebook or a simple script?

**In a Script:**

For standalone Python scripts, the `asyncio.run()` function is the simplest way to execute your main async function, as shown in the examples above.

**In a Jupyter Notebook:**

Jupyter notebooks run their own event loop. To run async code in a notebook cell, you can simply `await` the async function call if you are in an environment that supports top-level await (like modern IPython/Jupyter).

If you see an error like `SyntaxError: 'await' outside function`, it means your Jupyter environment doesn't have top-level await enabled. In that case, you can use `asyncio.run()`:

```python
# In a Jupyter cell
import asyncio
from pytestlab.instruments import Oscilloscope

async def measure_in_notebook():
    osc = Oscilloscope(address="TCPIP0::localhost::inst0::INSTR")
    await osc.connect()
    waveform = await osc.read_waveform(channel=1)
    await osc.disconnect()
    return waveform

# If top-level await is supported:
# waveform_data = await measure_in_notebook()
# print(waveform_data)

# If not, or for compatibility:
waveform_data = asyncio.run(measure_in_notebook())
print(waveform_data)

```
Some environments, like JupyterLab, might require `nest_asyncio` to run `asyncio.run()` inside the already running event loop.

```python
import nest_asyncio
nest_asyncio.apply()

# Now you can use asyncio.run()
waveform_data = asyncio.run(measure_in_notebook())
print(waveform_data)