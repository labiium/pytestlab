# bench.yaml

A bench file connects the names in your measurement code to the devices at your station. For example, `dmm` in YAML becomes `bench.dmm` in Python. Keep that alias when changing the connection or swapping in another compatible meter.

## Start with one simulated meter

Save this complete file as `bench.yaml`:

```yaml
bench_name: Voltage check
simulate: true
instruments:
  dmm:
    profile: keysight/34470A
```

`bench_name` identifies the setup. `simulate: true` selects simulation for this bench, and the packaged meter profile supplies the simulated responses. This example needs no instrument address.

## Validate and read

```bash
ptl bench validate --strict
ptl bench ls
```

Run the commands from the descriptor’s directory, or pass its path explicitly.
`ptl bench ls` lists aliases and declarations; it does not discover connected hardware.

Strict validation checks the configuration without loading third-party device plugins, creating drivers, or running bench hooks. Profiles requiring custom drivers or configuration models cannot be checked in strict mode. Passing strict validation does not establish hardware availability or readiness. From the directory containing the file, run this Python example:

```python
from pytestlab import Bench

with Bench.open("bench.yaml") as bench:
    reading = bench.dmm.measure("dc_voltage")
    print(reading.values, reading.units)
```

The context manager closes the bench when the block ends. To save the result from a script, follow the [CLI walkthrough](cli.md#run-a-measurement).

## Reset instruments on demand or at startup

`reset_on_open` is an optional top-level field. It defaults to `false`.

```yaml
reset_on_open: true
```

A normal `Bench.open()` then resets supported, selected instruments before
experiment setup or hooks. Lazy sessions and CLI diagnostics skip it. To
reset on demand instead, leave the field off:

```python
from pytestlab import Bench

with Bench.open("bench.yaml") as bench:
    bench.reset()
```

Unsupported devices, cameras, and probers are skipped. Reset can change
settings; it does not power-cycle equipment or protect the DUT. Failures name
the alias and stop the sequence. Access an instrument named `reset` with
`bench.instruments["reset"]`.

## Connect a physical station

| What you are connecting | Where it goes | What to change |
| --- | --- | --- |
| A physical multimeter | `instruments.dmm` | Set `simulate: false` on the bench and supply the meter's actual address and backend. |
| A wafer prober | `devices.prober` | Supply the controller profile and bus address. See the [PA200 bench example](user_guide/using_prober.md). |
| A microscope camera | `devices.microscope` | Set the backend and the intended camera's explicit `address` from its complete discovered resource string, even if only one camera is attached. See the [camera bench example](user_guide/using_camera_microscope.md). |

For mixed benches, an entry can set its own `simulate` flag. For route definitions, accessories, and safety limits, see the [bench descriptor reference](user_guide/bench_descriptors.md).
