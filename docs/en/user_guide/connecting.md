# Using Instruments and Connections

Start with a simulator, then connect a physical instrument only when you have
reviewed the station and the operation. Constructing a standalone instrument
selects and validates a profile; the first call that needs I/O opens the
configured backend.

## Using `AutoInstrument`

Use `from_preset()` for a bundled model, `from_file()` for a local profile,
or `from_config()` for other supported configuration sources. Inspecting
profile metadata does not connect the instrument.

### Simulated Instrument

The packaged Keysight 34470A fixture needs neither a hardware address nor a
VISA runtime:

```python
from pytestlab import AutoInstrument

dmm = AutoInstrument.from_preset("keysight/34470A", simulate=True)
try:
    reading = dmm.measure("dc_voltage", range_val=10, uncertainty=False)
    print(f"{float(reading):.3f} V (simulated)")
finally:
    dmm.close()
```

### Real Instrument

This example contacts a physical meter. Set up a working
[VISA backend](../installation.md#visa-backend-support), confirm the meter and
wiring, and set `DMM_VISA_RESOURCE` to the selected device's exact VISA address
before running it:

```python
import os

from pytestlab import AutoInstrument

dmm = AutoInstrument.from_preset(
    "keysight/34470A",
    address_override=os.environ["DMM_VISA_RESOURCE"],
    backend_type_hint="visa",
    simulate=False,
)
try:
    print(dmm.id())
    print(dmm.measure("dc_voltage").values)
finally:
    dmm.close()
```

Here `id()` is the first hardware query. It does not prove that the meter is
wired correctly or that a reading is calibrated.

## Using a Bench

For a bench-based workflow, save the
[simulated meter descriptor](../bench-yaml.md#start-with-one-simulated-meter)
as `bench.yaml`:

```python
from pytestlab import Bench

with Bench.open("bench.yaml") as bench:
    voltage = bench.dmm.measure("dc_voltage", uncertainty=False)
    print(f"{float(voltage):.3f} V (simulated)")
```

On a physical station, a default `Bench.open()` can open devices and run
configured experiment hooks. Use `start_experiment=False` with the selected
alias for a lazy device session without hooks. Use `ptl bench ls` or
`ptl bench validate --strict` for offline configuration inspection.

For physical connection errors, check the selected VISA backend with
`pyvisa-info` and confirm the exact device address. See
[Working with Benches](bench_descriptors.md) or the
[simulation guide](simulation.md).
