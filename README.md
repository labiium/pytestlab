<!--
  PyTestLab – Scientific test & measurement toolbox
  =================================================
  Comprehensive README generated 2025-06-10
-->

<p align="center">
  <img src="https://raw.githubusercontent.com/your-org/pytestlab/main/docs/assets/pytestlab_logo.svg"
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
  <a href="https://pytestlab.readthedocs.io"><img
     alt="Docs"
     src="https://img.shields.io/badge/docs-latest-blue"/></a>
  <a href="LICENSE"><img alt="License"
     src="https://img.shields.io/badge/license-MIT-green"/></a>
</p>

---

## ✨ Key Features

* **Async by design** – non-blocking instrument I/O with `async/await`.
* **Unified driver layer** – consistent high-level API across oscilloscopes, PSUs, DMMs, VNAs, AWGs, spectrum & power meters, DC loads, …  
  (see `pytestlab.instruments.*`).
* **Plug-and-play profiles** – YAML descriptors validated by Pydantic & JSON-schema.  
  Browse ready-made Keysight profiles in `pytestlab/profiles/keysight`.
* **Simulation mode** – develop anywhere using the built-in `SimBackend` (no hardware required, deterministic outputs for CI).
* **Bench descriptors** – group multiple instruments in one `bench.yaml`, define safety limits, automation hooks, traceability and measurement plans.
* **High-level measurement builder** – notebook-friendly `MeasurementSession` for parameter sweeps that stores data as Polars DataFrames and exports straight to the experiment database.
* **Rich database** – compressed storage of experiments & measurements with full-text search (`MeasurementDatabase`).
* **Powerful CLI** – `pytestlab …` commands to list/validate profiles, query instruments, convert benches to simulation, etc.
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

Commercial support / custom drivers? Open an issue or contact <pytestlab-support@example.com>.

---

> Built with ❤️  &nbsp;by scientists, for scientists.