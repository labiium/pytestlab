<!--
  PyTestLab – Scientific test & measurement toolbox
  =================================================
-->

<p align="center">
  <img src="https://raw.githubusercontent.com/labiium/pytestlab/master/pytestlab_logo.png"
       alt="PyTestLab logo" width="320"/>
</p>

<h1 align="center">PyTestLab</h1>

<p align="center">
  Modern Python toolbox for laboratory<br/>
  test-and-measurement automation, data management&nbsp;and analysis.
</p>

<p align="center">
  <a href="https://pypi.org/project/pytestlab"><img alt="PyPI"
     src="https://img.shields.io/pypi/v/pytestlab?logo=pypi&label=PyPI&color=blue"/></a>
  <a href="https://pytestlab.org"><img
     alt="Docs"
     src="https://img.shields.io/badge/docs-latest-blue"/></a>
  <a href="https://opensource.org/licenses/Apache-2.0"><img alt="Apache License"
        src="https://img.shields.io/badge/license-Apache%202.0-blue"/></a>
  <a href="https://github.com/labiium/pytestlab/actions/workflows/test.yml"><img
     alt="Tests"
     src="https://github.com/labiium/pytestlab/actions/workflows/test.yml/badge.svg"/></a>
</p>

## Quick start

PyTestLab runs laboratory measurements from Python, with model-specific instrument
commands kept in reusable profiles. Start with a simulated multimeter. No
instrument, address, or VISA runtime is needed.

Install **PyTestLab 0.3.0** on **Python 3.11 or newer**:

```bash
python -m pip install "pytestlab==0.3.0"
ptl --version
```

If 0.3.0 is not yet on PyPI, use the matching source checkout or wait for the
release. Earlier versions may not support these examples.

Save this as `first_measurement.py` and run `python first_measurement.py`:

```python
from pytestlab import AutoInstrument

dmm = AutoInstrument.from_preset("keysight/34470A", simulate=True)
try:
    reading = dmm.measure("dc_voltage", range_val=10, uncertainty=False)
    print(f"{float(reading):.3f} V (simulated)")
finally:
    dmm.close()
```

Expected output: `0.000 V (simulated)`. This is a fixture response, not a
physical or calibrated measurement.

## Put the meter in a bench

Save a `bench.yaml` beside your script:

```yaml
bench_name: Voltage check
simulate: true
instruments:
  dmm:
    profile: keysight/34470A
```

```bash
ptl bench validate --strict
ptl bench ls --json
```

These commands inspect the configuration without opening hardware. Python
scripts access the meter as `bench.dmm` inside `Bench.open("bench.yaml")`.
Keep that alias when changing the physical setup. See the [bench guide](https://pytestlab.org/bench-yaml/)
and the [CLI walkthrough](https://pytestlab.org/cli/). A bench does not reset
instruments on open by default. Use `bench.reset()` to reset supported
instruments deliberately, or opt into `reset_on_open: true` in a reviewed
physical bench.

## What you can do

- **Discover supported operations before connecting.** Inspect profile-defined
  functions, ranges, and other settings with
  `ptl instrument list-options keysight/34470A measure function`.
  See [operation discovery](https://pytestlab.org/api/instruments/operation_contract/).
- **Keep native captures with each trial.** Store waveforms, VNA sweeps, spectrum
  traces, RF power readings, or impedance sweeps with units and metadata.
  [Measurement sessions](https://pytestlab.org/user_guide/measurement_session/#store-a-waveform-or-sweep-with-each-trial)
  and the [database](https://pytestlab.org/api/database/) preserve trial order.
  `MeasurementSession` uses signing, auditing, and timestamping by default.
  Open it with `compliance=False` for an ordinary unsigned session; native RF
  results require that mode.
- **Propagate uncertainty where the measurement model supports it.**
  Work with quantities, component budgets, waveform reductions, and channel
  timing. A nominal-only result is not report-grade. See the
  [uncertainty guide](https://pytestlab.org/user_guide/uncertainty/).
- **Reproduce experiments offline.** Use a supported simulator or replay a
  recorded command and response sequence. Replay does not recreate the
  physical instrument. See [record and replay](https://pytestlab.org/user_guide/replay_mode/),
  [digital-twin evidence](https://pytestlab.org/user_guide/digital_twin/), and
  [offline examples](https://github.com/labiium/pytestlab/blob/master/examples/QUICKSTART.md).

## Save and reopen two captures

This example uses synthetic spectrum traces. It shows how to preserve trial
order and amplitude units without connecting to an analyzer. Save and reopen
the captures in Parquet:

```python
import polars as pl

from pytestlab.experiments import Experiment
from pytestlab.instruments.SpectrumAnalyser import SpectrumTrace

run = Experiment("Synthetic spectrum")
for amplitude in (-45.0, -12.0):
    run.add_trial(SpectrumTrace(1, (1e6, 2e6), (amplitude, -70.0), "frequency", "dBm"))
run.save_parquet("spectrum.parquet")

reopened = Experiment("Reopened spectrum")
reopened.data = pl.read_parquet("spectrum.parquet")
captures = reopened.measurements["result"]
print([(capture.values["amplitude"][0], capture.units) for capture in captures[:]])
```

The final line is `[(-45.0, 'dBm'), (-12.0, 'dBm')]`. These are supplied sample values,
not instrument readings or uncertainty estimates. See the
[spectrum analyzer guide](https://pytestlab.org/api/instruments/spectrum-analyzer/)
for acquiring a trace from a configured analyzer.

## Connect physical instruments when ready

Choose a [supported profile](https://pytestlab.org/profiles/gallery/), confirm
the exact device address and lab limits, and follow the optional
[VISA setup](https://pytestlab.org/installation/#visa-backend-support).
PyVISA is included as a Python dependency. Install or select a VISA backend
only if your physical setup needs one. See
[Connecting to Instruments](https://pytestlab.org/user_guide/connecting/) for a
separate live example.

[API reference](https://pytestlab.org/api/) ·
[Release notes](https://github.com/labiium/pytestlab/blob/master/CHANGELOG.md) ·
[Contributing](https://github.com/labiium/pytestlab/blob/master/CONTRIBUTING.md) ·
[Code of Conduct](https://github.com/labiium/pytestlab/blob/master/CODE_OF_CONDUCT.md)

Apache-2.0 © 2023 Emmanuel Olowe & contributors.
