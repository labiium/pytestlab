---
title: Impedance sweep analysis and export
---

# Analyze and export an impedance sweep

Both complex and scalar sweep results have `to_dataframe()` (Polars) and
`to_csv(path)`. These are local result operations, not instrument commands.
Rows use the measured frequency axis and instrument point order. Complex
impedance uses real and imaginary columns in ohms; scalar results carry
their native parameter name and unit. Missing point status stays null
(blank in CSV), distinct from Hioki's normal status `0`. `fresh` means the
driver verified a new acquisition; a held read is always `false`.

See the [bench and preparation instructions](impedance-analyzer.md) first.

```python
from pytestlab import Bench

with Bench.open("bench.yaml", aliases={"impedance"}, start_experiment=False) as bench:
    analyzer = bench.impedance
    print(analyzer.get_fixture_correction())  # Programmed flags, not calibration validity.
    curve = analyzer.read_impedance_sweep()
    minimum = min(curve.readings, key=lambda point: point.magnitude_ohm)
    print(minimum.frequency_hz, minimum.magnitude_ohm)
    curve.to_csv("impedance_sweep.csv")
```

A sampled minimum is not necessarily a physical resonance. CSV refuses to
replace an existing file unless you pass `overwrite=True`.

From a source checkout, use the same `bench.impedance` workflow with strict,
synthetic replay (no instrument connection):

```bash
ptl replay run examples/replay_mode/export_impedance.py --session examples/replay_mode/impedance_e4990a.yaml
```

To try Hioki, use `impedance_im3570.yaml` instead. Move the previous output or
run in a separate directory so `impedance_sweep.csv` is not overwritten.

## Add an accuracy limit or a Type B component

Pass the documented conditions **at acquisition**, not current settings read
afterward. For example, given a captured `curve` from an E4990A:

```python
from pytestlab.instruments.ImpedanceAnalyzer import E4990AAccuracyConditions

conditions = E4990AAccuracyConditions(
    setup_reference="run-042/setup-record",
    temperature_c=23,
    warmup_minutes=90,
    voltage_v_rms=0.5,
    measurement_time=5,
    dc_current_range_a=0.001,
    dc_bias_enabled=False,
)
bounded = curve.to_measurement_result(accuracy=conditions)
point = curve.readings[0].to_measurement_result(
    accuracy=conditions, rectangular_type_b="magnitude"
)
quantity = point.uncertainty
```

[Keysight Equation 1](https://www.keysight.com/tw/zh/assets/7018-04256/data-sheets/5991-3890.pdf#page=11)
covers the calibrated direct front-panel plane here (20 Hz–10 MHz,
1 Ω–1 MΩ, 5–500 mVrms, unbiased, 18–28 °C, at least 90 minutes warmed up).
Use within the operating environmental limits and without an applied AC magnetic field.
[Hioki's IM3570E15-62B catalog, p. 7](https://www.hioki.com/us-en/products/lcr-meters/3-ghz/id_5772) is available
through `IM3570AccuracyConditions` here for 1–10 kHz and fixed ranges
300 Ω, 1 kΩ, 3 kΩ, 10 kΩ, or 30 kΩ. Record actual normal V-mode settings,
valid open/short compensation, in-date calibration, and a noncondensing
environment. Unsupported points keep nominal data and null limits.

Accuracy columns are ± limits, not standard uncertainties. An explicit
`rectangular_type_b="magnitude"` or `"phase"` on one point uses
[the GUM rectangular assumption](https://www.bipm.org/en/doi/10.59161/jcgm100-2008e)
to produce a partial standard uncertainty, limit/√3, for that component only.
No relationship between points or components, complete uncertainty budget,
SI traceability, or physical qualification is inferred.
