---
title: Home
template: home.html
hide:
  - navigation
  - toc
  - footer
---

```python
from pytestlab import AutoInstrument

# Take a voltage reading without connecting hardware.
dmm = AutoInstrument.from_config(
    "keysight/34470A", simulate=True
)
try:
    reading = dmm.measure("dc_voltage")
    print(reading.values, reading.units)
finally:
    dmm.close()
```

```yaml
# bench.yaml
bench_name: "Power-Amp Characterisation"
simulate: true

instruments:
  psu:
    profile: "keysight/EDU36311A"
    safety_limits:
      channels:
        1: {voltage: {max: 6.0}, current: {max: 3}}
  dmm:
    profile: "keysight/34470A"
```

```python
import pytestlab
from pytestlab.bench import SafetyLimitError

def run_bench():
    # Context manager handles connections & safety
    with pytestlab.Bench.open("bench.yaml") as bench:

        # Access instruments by their alias
        v = bench.dmm.measure("dc_voltage")
        print(f"Measured: {v.values} {v.units}")

        # Safety limits are automatically enforced
        try:
            bench.psu.set_voltage(1, 7.0)
        except SafetyLimitError as e:
            print(f"Error: {e}")

run_bench()
```

```python
from pytestlab.measurements import MeasurementSession

# Declaratively build a complex experiment
def run_sweep():
    with MeasurementSession("MOSFET IV Curve") as meas:
        meas.instrument("psu", "keysight/EDU36311A", simulate=True)
        meas.instrument("dmm", "keysight/34470A", simulate=True)

        meas.parameter("v_gate", [0.0, 0.5, 1.0], unit="V")
        meas.parameter("v_drain", [0.1, 1.0, 5.0], unit="V")

        @meas.acquire
        def drain_current(psu, dmm, v_gate, v_drain):
            psu.set_voltage(1, v_gate)
            psu.set_voltage(2, v_drain)
            return dmm.measure("dc_current")

        results = meas.run()
        print(results.data.head())

run_sweep()
```
