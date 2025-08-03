<!--
  PyTestLab – Scientific test & measurement toolbox
  =================================================
  Comprehensive README generated 2025-06-10
-->

<p align="center">
  <img src="pytestlab_logo.png"
       alt="PyTestLab logo" width="320"/>
</p>

<h1 align="center">PyTestLab</h1>

<p align="center">
  Modern, async-first Python toolbox for laboratory<br/>
  test-and-measurement automation, data management&nbsp;and analysis.
</p>

<p align="center">
  <a href="https://pypi.org/project/pytestlab"><img alt="PyPI"
     src="https://img.shields.io/pypi/v/pytestlab?logo=pypi&label=PyPI&color=blue"/></a>
  <a href="https://github.com/your-org/pytestlab/actions/workflows/build_wheels.yml"><img
     alt="CI"
     src="https://github.com/your-org/pytestlab/actions/workflows/build_wheels.yml/badge.svg"/></a>
  <a href="https://pytestlab.org"><img
     alt="Docs"
     src="https://img.shields.io/badge/docs-latest-blue"/></a>
  <a href="https://opensource.org/licenses/Apache-2.0"><img alt="Apache License"
        src="https://img.shields.io/badge/license-Apache%202.0-blue"/></a>
</p>

---

## ✨ Key Features

* **Async by design** – non-blocking instrument I/O with `async/await`.
* **Unified driver layer** – consistent high-level API across oscilloscopes, PSUs, DMMs, VNAs, AWGs, spectrum & power meters, DC loads, …
  (see `pytestlab.instruments.*`).
* **Plug-and-play profiles** – YAML descriptors validated by Pydantic & JSON-schema.
  Browse ready-made Keysight profiles in `pytestlab/profiles/keysight`.
* **Simulation mode** – develop anywhere using the built-in `SimBackend` (no hardware required, deterministic outputs for CI).
* **Record & Replay** – record real instrument sessions and replay them exactly for reproducible measurements, offline analysis, and regression testing with strict sequence validation.
* **Bench descriptors** – group multiple instruments in one `bench.yaml`, define safety limits, automation hooks, traceability and measurement plans.
* **High-level measurement builder** – notebook-friendly `MeasurementSession` for parameter sweeps that stores data as Polars DataFrames and exports straight to the experiment database.
* **Rich database** – compressed storage of experiments & measurements with full-text search (`MeasurementDatabase`).
* **Powerful CLI** – `pytestlab …` commands to list/validate profiles, query instruments, convert benches to simulation, replay sessions, etc.
* **Extensible back-ends** – VISA, Lamb server, pure simulation; drop-in new transports via the `AsyncInstrumentIO` protocol.
* **Docs & examples** – Jupyter tutorials, MkDocs site, and 40+ ready-to-run scripts in `examples/`.

---

## 🚀 Quick Start

### 1. Install

```bash
pip install pytestlab           # core
pip install pytestlab[full]     # + plotting, uncertainties, etc.
```

> Need VISA? Install NI-VISA or Keysight IO Libraries, then `pip install pyvisa`.

### 2. Hello Oscilloscope (simulated)

```python
import asyncio
from pytestlab.instruments import AutoInstrument

async def main():
    scope = AutoInstrument.from_config("keysight/DSOX1204G", simulate=True)
    await scope.connect_backend()

    # simple façade usage
    await scope.channel(1).setup(scale=0.5).enable()
    await scope.trigger.setup_edge(source="CH1", level=0.2)

    trace = await scope.read_channels(1)      # Polars DataFrame
    print(trace.values.head())

    await scope.close()

asyncio.run(main())
```

### 3. Build a Bench

```yaml
# bench.yaml  (excerpt)
bench_name: "Power-Amp Characterisation"
simulate: false           # set to true for dry-runs / CI
instruments:
  psu:
    profile: "keysight/EDU36311A"
    address: "TCPIP0::172.22.1.5::inst0::INSTR"
    safety_limits:
      channels:
        1: {voltage: {max: 6.0}, current: {max: 3}}
  dmm:
    profile: "keysight/34470A"
    address: "USB0::0x0957::0x1B07::MY56430012::INSTR"
```

```python
import asyncio, pytestlab

async def run():
    async with await pytestlab.Bench.open("bench.yaml") as bench:
        v = await bench.dmm.measure_voltage_dc()
        print("Measured:", v.values, v.units)

asyncio.run(run())
```

### 4. Record & Replay Sessions

Record real instrument interactions and replay them exactly:

```bash
# Record a measurement session
pytestlab replay record my_measurement.py --bench bench.yaml --output session.yaml

# Replay the recorded session
pytestlab replay run my_measurement.py --session session.yaml
```

Perfect for reproducible measurements, offline analysis, and catching script changes!

---

## 🔄 Record & Replay Mode

PyTestLab's **Record & Replay** system enables you to capture real instrument interactions and replay them with exact sequence validation. This powerful feature supports reproducible measurements, offline development, and regression testing.

### Core Benefits

- **🎯 Reproducible Measurements** – Exact same SCPI command sequences every time
- **🛡️ Measurement Integrity** – Scripts cannot deviate from validated sequences
- **🔬 Offline Analysis** – Run complex measurements without real hardware
- **🧪 Regression Testing** – Catch unintended script modifications immediately

### How It Works

1. **Recording Phase**: The `SessionRecordingBackend` wraps your real instrument backends and logs all commands, responses, and timestamps to a YAML session file.

2. **Replay Phase**: The `ReplayBackend` loads the session and validates that your script executes the exact same command sequence. Any deviation triggers a `ReplayMismatchError`.

### Usage Examples

#### Basic Recording & Replay
```bash
# Record a measurement with real instruments
pytestlab replay record voltage_sweep.py --bench lab_bench.yaml --output sweep_session.yaml

# Replay the exact sequence (simulated)
pytestlab replay run voltage_sweep.py --session sweep_session.yaml
```

#### Programmatic Usage
```python
import asyncio
from pytestlab.instruments import AutoInstrument
from pytestlab.instruments.backends import ReplayBackend

async def main():
    # Load a recorded session
    replay_backend = ReplayBackend("recorded_session.yaml")

    # Create instrument with replay backend
    psu = AutoInstrument.from_config(
        "keysight/EDU36311A",
        backend_override=replay_backend
    )

    await psu.connect_backend()

    # This will replay the exact recorded sequence
    await psu.set_voltage(1, 5.0)
    voltage = await psu.read_voltage(1)

    await psu.close()

asyncio.run(main())
```

#### Session File Format
```yaml
psu:
  profile: keysight/EDU36311A
  log:
  - type: query
    command: '*IDN?'
    response: 'Keysight Technologies,EDU36311A,CN61130056,K-01.08.03-01.00-01.08-02.00'
    timestamp: 0.029241038020700216
  - type: write
    command: 'VOLT 5.0, (@1)'
    timestamp: 0.8096857140189968
  - type: query
    command: 'MEAS:VOLT? (@1)'
    response: '+4.99918100E+00'
    timestamp: 1.614894539990928
```

### Error Detection

If your script deviates from the recorded sequence:

```python
# During recording: set_voltage(1, 5.0)
# During replay: set_voltage(1, 3.0)  # ← Different value!

# Raises: ReplayMismatchError: Expected 'VOLT 5.0, (@1)' but got 'VOLT 3.0, (@1)'
```

### Advanced Features

- **Multi-instrument sessions** – Record PSU, oscilloscope, DMM interactions simultaneously
- **Timestamp preservation** – Exact timing information for analysis
- **Automatic error checking** – Captures instrument `:SYSTem:ERRor?` queries
- **CLI integration** – Full command-line workflow support
- **Backend flexibility** – Works with VISA, LAMB, and custom backends

See `examples/replay_mode/` for complete working examples and tutorials.

---

## 📚 Documentation

| Section | Link |
|---------|------|
| Installation | `docs/installation.md` |
| 10-minute tour (Jupyter) | `docs/tutorials/10_minute_tour.ipynb` |
| User Guide | `docs/user_guide/*` |
| Async vs. Sync | `docs/user_guide/async_vs_sync.md` |
| Bench descriptors | `docs/user_guide/bench_descriptors.md` |
| API reference | `docs/api/*` |
| Instrument profile gallery | `docs/profiles/gallery.md` |
| Tutorials | |
| Compliance and Audit | `docs/tutorials/compliance.ipynb` |
| Custom Validations | `docs/tutorials/custom_validations.ipynb` |
| Profile Creation | `docs/tutorials/profile_creation.ipynb` |

HTML docs hosted at <https://pytestlab.readthedocs.io> (builds from `docs/`).

---

## 🧑‍💻 Contributing

Pull requests are welcome! See [`CONTRIBUTING.md`](CONTRIBUTING.md) and the [Code of Conduct](CODE_OF_CONDUCT.md).
Run the test-suite (`pytest`), type-check (`mypy`), lint/format (`ruff`), and keep commits conventional (`cz c`).

---

## 🗜️ License

MIT © 2022–2025 Emmanuel Olowe & contributors.

Commercial support / custom drivers? Open an issue or contact <support@pytestlab.org>.

---

> Built with ❤️  &nbsp;by scientists, for scientists.
