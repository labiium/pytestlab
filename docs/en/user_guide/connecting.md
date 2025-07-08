# Connecting to Instruments

PyTestLab provides a unified and straightforward way to connect to both real and simulated instruments.

---

## Using `AutoInstrument`

The `pytestlab.AutoInstrument` factory is the primary way to create a single instrument instance. You need to provide a configuration source, which can be a profile key (e.g., `"keysight/DSOX1204G"`) or a path to a YAML file.

!!! note "Asynchronous Connection"
    Creating an instrument instance with `AutoInstrument.from_config()` does **not** establish the connection.  
    You must always `await` the `connect_backend()` method on the created instrument object.

---

### Connecting to a Real Instrument

To connect to a physical instrument, you typically need its VISA address.

```python
import asyncio
import pytestlab

async def main():
    # Create an instrument instance from a profile and specify its address
    dmm = await pytestlab.AutoInstrument.from_config(
        "keysight/34470A",
        address_override="USB0::0x0957::0x1B07::MY56430012::INSTR"
    )

    # Establish the connection
    await dmm.connect_backend()

    print(f"Connected to: {await dmm.id()}")

    # ... perform operations ...

    await dmm.close()

asyncio.run(main())
```

---

### Connecting to a Simulated Instrument

To create a simulated instrument for development or testing, set the `simulate=True` flag. No address is needed.

```python
import asyncio
import pytestlab

async def main():
    scope_sim = await pytestlab.AutoInstrument.from_config("keysight/DSOX1204G", simulate=True)
    await scope_sim.connect_backend()

    print(f"Connected to simulated instrument: {await scope_sim.id()}")

    await scope_sim.close()

asyncio.run(main())
```

Simulation mode is ideal for development, CI, and testing when hardware is unavailable.

---

## Using a Bench

For managing multiple instruments, the `pytestlab.Bench` class is the recommended approach. It handles the connection and cleanup for all instruments defined in your `bench.yaml` file automatically.

```python
import asyncio
import pytestlab

async def main():
    async with await pytestlab.Bench.open("bench.yaml") as bench:
        print(f"Bench loaded: {bench.config.bench_name}")
        # Access instruments by alias, e.g.:
        await bench.psu.channel(1).set(voltage=3.3, current_limit=0.5).on()
        voltage = await bench.dmm.measure_voltage_dc()
        print(f"Measured: {voltage.values:.4f} V")
    # All instruments are closed automatically here

asyncio.run(main())
```

See the [Working with Benches](bench_descriptors.md) guide for more details.

---

## Troubleshooting Connections

- **VISA Not Found:** Ensure you have installed a VISA library (NI-VISA, Keysight IO Libraries, etc.) and that it is accessible in your system's PATH.
- **Address Errors:** Double-check your instrument's VISA address. Use `pytestlab profile list` and `pytestlab bench ls` to inspect available profiles and bench configurations.
- **Simulation:** If you encounter persistent connection issues, try running in simulation mode to isolate hardware vs. software problems.

---

## Next Steps

- [Getting Started Guide](getting_started.md)
- [Async vs. Sync Programming](async_vs_sync.md)
- [Simulation Guide](simulation.md)
- [Bench Descriptors](bench_descriptors.md)