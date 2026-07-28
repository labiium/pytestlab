# Using Instruments and Connections

PyTestLab separates **selecting a device** from **opening communication**. Your experiment code creates an instrument or opens a bench, then uses ordinary measurement/control methods. PyTestLab opens the underlying backend automatically when the first command or query needs it.

---

## Using `AutoInstrument`

Use `pytestlab.AutoInstrument` when you want a single instrument from a packaged preset, a local profile file, or an in-memory config.

!!! note "Automatic backend opening"
    `AutoInstrument.from_preset()`, `from_file()`, and `from_config()` build a configured Python object. They do not immediately touch hardware. The first operation that needs I/O, such as `id()`, `query()`, `read_channels()`, or `measure()`, opens the backend automatically.

---

### Real Instrument

For physical instruments, provide the address or backend settings required by your lab. The first instrument operation performs the actual connection.

```python
import pytestlab

def main():
    dmm = pytestlab.AutoInstrument.from_preset(
        "keysight/34470A",
        address_override="USB0::0x0957::0x1B07::MY56430012::INSTR"
    )

    # id() is the first I/O operation, so PyTestLab opens the backend here.
    print(f"Instrument: {dmm.id()}")

    voltage = dmm.measure(pytestlab.DMMFunction.VOLTAGE_DC)
    print(f"Measured voltage: {voltage}")

    dmm.close()

main()
```

---

### Simulated Instrument

For development, CI, and notebooks, use simulation mode. No hardware address is needed.

```python
import pytestlab

def main():
    scope = pytestlab.AutoInstrument.from_preset("keysight/DSOX1204G", simulate=True)

    scope.channel(1).setup(scale=0.5).enable()
    trace = scope.read_channels(1)
    print(trace.values.head())

    scope.close()

main()
```

---

## Using a Bench

For complete experiments, prefer `pytestlab.Bench`. A bench descriptor declares the instruments, addresses, backend defaults, safety limits, accessories, and measurement plan in one reviewable YAML file. `Bench.open()` validates the file, initializes the devices, and closes them when the `with` block exits.

```python
import pytestlab

def main():
    with pytestlab.Bench.open("bench.yaml") as bench:
        print(f"Bench loaded: {bench.config.bench_name}")

        bench.psu.channel(1).set(voltage=3.3, current_limit=0.5).on()
        voltage = bench.dmm.measure(pytestlab.DMMFunction.VOLTAGE_DC)
        print(f"Measured: {voltage.values:.4f} V")
    # All bench devices are closed automatically here.

main()
```

See the [Working with Benches](bench_descriptors.md) guide for more details.

---

## Troubleshooting

- **VISA Not Found:** Ensure you have installed a VISA library (NI-VISA, Keysight IO Libraries, etc.) and that it is accessible in your system's PATH.
- **Address Errors:** Double-check the instrument address in your code or `bench.yaml`. Use `pytestlab profile list` and `pytestlab bench ls` to inspect available profiles and bench configurations.
- **Failure point:** Connection failures usually appear at the first I/O operation, because backend opening is automatic and lazy for standalone instruments.
- **Simulation:** If you encounter persistent connection issues, try running in simulation mode to isolate hardware vs. software problems.

---

## Next Steps

- [Getting Started Guide](getting_started.md)
- [Simulation Guide](simulation.md)
- [Bench Descriptors](bench_descriptors.md)
