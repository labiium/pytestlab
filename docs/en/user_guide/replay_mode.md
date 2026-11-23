# Record & Replay Mode

Recording saves the device exchanges a script makes. Replay supplies the
saved responses and checks the sequence for each device. This is useful for
testing that a script still issues the expected commands. It does not
reproduce the physical bench or verify a measurement's accuracy.

## Examples

In a source checkout, run the checked-in synthetic scope example:

```bash
ptl replay run examples/replay_mode/capture_scope.py --session examples/replay_mode/scope_session.yaml
```

It reads the recorded identity, waveform preamble, and eight binary samples
without a scope, a VISA driver, or an external simulator.

## Basic usage

Save the [simulated meter descriptor](../bench-yaml.md#start-with-one-simulated-meter)
as `bench.yaml`. Save this script as `read_voltage.py`:

```python
def main(bench):
    reading = bench.dmm.measure("dc_voltage", uncertainty=False)
    print(f"{float(reading):.3f} V")
```

```bash
ptl replay record read_voltage.py --bench bench.yaml --output session.yaml
ptl replay run read_voltage.py --session session.yaml
```

Recording opens the supplied bench and runs the script's `main(bench)`.
With a live descriptor, that can communicate with real hardware and run
configured hooks. The wrapper is installed after the bench opens, so
initialization and pre-experiment hooks are not part of the script's
recording. Use a trusted descriptor and script. Ordinary
`Bench.open("bench.yaml")` does not enable recording.

Replay loads each saved profile and supplies a `ReplayBackend` in place of
its normal backend. It passes the recorded aliases to `main(bench)`. It
does not open the originating bench or run its hooks. Replay is not a Python
sandbox: unrelated I/O issued by the script itself is not intercepted.

## Programmatic usage

Load the named entry from session YAML, then pass its **log**, not the file
name, to `ReplayBackend`:

```python
from pathlib import Path

import yaml
from pytestlab import AutoInstrument
from pytestlab.instruments.backends.replay_backend import ReplayBackend

entry = yaml.safe_load(Path("session.yaml").read_text())["dmm"]
backend = ReplayBackend(entry["log"], profile_key="dmm")
dmm = AutoInstrument.from_preset(entry["profile"], backend_override=backend)
try:
    print(float(dmm.measure("dc_voltage", uncertainty=False)))
finally:
    dmm.close()
```

The example uses a packaged profile. For a session that references a local
profile file, pass its path to `AutoInstrument.from_file()` instead. A local
profile must remain available when you replay the recording.

## Session file format

Each top-level key is a bench alias. Its `profile` is a packaged key or a
path to a local profile, and its `log` is a list of exchanges in capture
order. Text queries include a `response` string, writes do not, and binary
`query_raw` records store base64 bytes, a SHA-256 hash, and the byte count.
Recordings include relative timestamps, but replay does not reproduce the
recorded timing. A synthetic fixture can omit timestamps.

## Error detection and validation

A command that does not match the next recorded command for the same alias
fails. The backend raises
`pytestlab.errors.ReplayMismatchError`; higher-level instrument methods
can wrap it in a communication error. Replay does not require a script to
consume every trailing exchange, so it is not proof that the entire original
procedure ran. Logs are independent across aliases; replay does not enforce
one global order across different devices.

If replay fails, compare the first diverging exchange with the recording,
including the alias, command text, and whether the operation was a write,
text query, or binary query. Reuse the same script and profile versions
before re-recording. Capture from a simulator for offline regression tests;
use a commissioned real bench only when you need actual instrument
responses. Review recordings before sharing, since replies may contain
serial numbers or station data.

## API reference

- [ReplayBackend](../api/backends.md#replaybackend)
- [SessionRecordingBackend](../api/backends.md#sessionrecordingbackend)
- [ReplayMismatchError](../api/errors.md#replaymismatcherror)
