# Handling Uncertainty

PyTestLab treats uncertainty as a measurement budget, not just a displayed
`+/-` value. Instrument profiles describe explicit uncertainty components,
drivers evaluate those components with runtime context, and scalar results are
returned as `MeasurementQuantity` objects with nominal value, unit, standard
uncertainty, expanded uncertainty, and budget provenance.

The model follows the usual metrology workflow: identify Type A and Type B
components, convert limits to standard uncertainty using the stated
distribution, combine independent components in quadrature, and report
expanded uncertainty when needed.

## Strict Accuracy Specs

Accuracy fields are intentionally explicit. Ambiguous fields such as
`percent_reading` are rejected.

```yaml
accuracy:
  model: linear
  reading_percent: 0.025
  range_percent: 0.005
  offset: 0.0005
  offset_unit: V
  distribution: rectangular
  source: "EDU34450A datasheet, 1 year, 23 C +/- 5 C"
```

Percent fields are human percentages: `0.025` means `0.025%`, not the fraction
`0.025`. Use `reading_fraction` or `reading_ppm` when the source is already in
fractional or ppm units.

## Measurement Quantities

When an applicable accuracy model is available, instrument methods return a
`MeasurementQuantity` in `MeasurementResult.values`.

```python
result = dmm.measure(DMMFunction.VOLTAGE_DC)
quantity = result.values

print(quantity.nominal)      # nominal value
print(quantity.unit)         # "V"
print(quantity.u)            # combined standard uncertainty
print(quantity.U(k=2))       # expanded uncertainty
print(quantity.budget)       # component-level provenance
```

`MeasurementQuantity` supports basic arithmetic propagation and can be exported
to the `uncertainties` package with `quantity.to_ufloat()` for compatibility.
Arithmetic preserves per-component provenance in the propagated budget metadata,
so downstream results remain auditable instead of becoming anonymous standard
deviations.

## Advanced Models

For non-linear or context-dependent instruments, profiles can use richer models:

- band tables for frequency, range, channel, or other context variables
- expression models for compact datasheet formulas
- Monte Carlo models for simulated propagation from component distributions
- repeatability models for Type A uncertainty from repeated observations
- composite budgets that combine repeatability, resolution, calibration, drift,
  and datasheet terms

Every model evaluates against an `UncertaintyContext`, which can include
reading, unit, range, resolution, frequency, temperature, NPLC, bandwidth,
channel, sample count, calibration age, and instrument metadata.

Profile-facing accuracy fields accept the same model set in range specs,
readback specs, and `measurement_accuracy` maps. Use `model` to select the
shape:

```yaml
accuracy:
  model: band_table
  variable: reading
  bands:
    - min: 0
      max: 1
      reading_percent: 0.05
      range_percent: 0.02
    - min: 1
      max: 10
      reading_percent: 0.02
      range_percent: 0.01
```

```yaml
measurement_accuracy:
  vpp_ch1:
    model: composite
    components:
      - model: linear
        range_percent: 1.0
      - model: expression
        expression: "0.01*reading + 0.001*bandwidth/1e6"
        distribution: standard
```

Drivers pass the context they know. For example, multimeters provide reading,
unit, range, resolution, and function; oscilloscopes add channel and bandwidth;
power supplies and active loads provide channel and configured/readback range
when available. If a model requires context the driver cannot know, keep that
term in a profile field or metadata path that the driver can provide.

Model evaluation is strict: referenced expression variables and range/count
terms must have explicit context values, with zero remaining a valid value.
Driver methods keep backward-compatible runtime behavior by default: configured
uncertainty models that fail to evaluate are logged and the nominal float is
returned. Set `uncertainty_strict: true` in a profile to make drivers propagate
those errors during profile qualification or scientific validation.

## Worked Examples

### DMM Range Accuracy From a Profile

Use a linear model when the datasheet gives terms such as percent of reading,
percent of range, fixed offset, counts, or resolution.

```yaml
device_type: multimeter
role: measurement
manufacturer: Test
model: ExampleDMM
uncertainty_strict: true
measurement_functions:
  dc_voltage:
    ranges:
      - nominal_V: 10.0
        resolution: 0.001
        accuracy:
          model: linear
          reading_percent: 0.025
          range_percent: 0.005
          offset: 0.0005
          offset_unit: V
          distribution: rectangular
          source: "ExampleDMM datasheet, 1 year, 23 C +/- 5 C"
```

Then measure normally. In the example below, `backend` is whichever configured
instrument backend you use for the session, such as VISA, Lamb, replay, or a
simulated backend. When the driver finds a matching range, the result value is a
`MeasurementQuantity`.

```python
from pytestlab.config.loader import load_device_profile
from pytestlab.config.multimeter_config import DMMFunction
from pytestlab.instruments.Multimeter import Multimeter

config = load_device_profile("example_dmm.yaml")
dmm = Multimeter(config=config, backend=backend)

measurement = dmm.measure(DMMFunction.VOLTAGE_DC)
quantity = measurement.values

print(quantity.nominal)
print(quantity.u)
print(quantity.U(k=2))
print(quantity.budget.components[0].source)
```

For a 5 V reading on the 10 V range, the budget has separate reading, range,
and offset components. Those components remain visible after later arithmetic.

### Arithmetic Propagation

`MeasurementQuantity` supports scalar and quantity arithmetic while preserving
the input component provenance.

```python
voltage = dmm.measure(DMMFunction.VOLTAGE_DC).values
current = ammeter.measure(DMMFunction.CURRENT_DC).values

power = voltage * current
efficiency = power / input_power
scaled_voltage = 2 * voltage
margin = 5.0 - voltage

print(power.nominal)
print(power.unit)
print(power.u)
print(power.budget.components)
```

Addition and subtraction require compatible units. Multiplication and division
combine units with Pint when available, so `V * A` becomes a power-like compound
unit and `V / mV` can become dimensionless.

### Oscilloscope Context-Dependent Accuracy

Use an expression model when the uncertainty depends on runtime context the
driver can provide, such as reading, range, channel, bandwidth, or sample count.

```yaml
device_type: oscilloscope
role: measurement
manufacturer: Test
model: ExampleScope
bandwidth: 100000000.0
sampling_rate: 1000000000.0
memory: 1000000.0
waveform_update_rate: 1000.0
trigger:
  types: [edge]
  modes: [auto]
  slopes: [rising]
channels:
  - description: CH1
    channel_range:
      min_val: -5.0
      max_val: 5.0
    input_coupling: [DC]
    input_impedance: 1000000.0
    probe_attenuation: [1]
    timebase:
      range:
        min_val: 0.000000001
        max_val: 1.0
      horizontal_resolution: 0.000000001
measurement_accuracy:
  vpp_ch1:
    model: expression
    expression: "0.01*reading + 0.001*bandwidth/1e6"
    distribution: standard
```

```python
result = scope.measure_voltage_peak_to_peak(1)
quantity = result.values

print(quantity.nominal)
print(quantity.u)
print(quantity.budget.method)
```

If an expression references `bandwidth`, `range`, `resolution`, or another
context variable, that value must be provided by the driver or by model
parameters. Missing referenced context raises in the model layer.

### PSU and DC Load Readback Accuracy

Power supplies usually attach measurement accuracy to channel readback keys.

```yaml
device_type: power_supply
role: stimulus
manufacturer: Test
model: ExamplePSU
channels:
  - description: CH1
    voltage_range:
      min: 0.0
      max: 20.0
      resolution: 0.001
    current_limit_range:
      min: 0.0
      max: 2.0
      resolution: 0.0001
measurement_accuracy:
  read_voltage_ch1:
    model: linear
    range_percent: 0.5
    distribution: standard
    source: "ExamplePSU voltage readback specification"
```

```python
voltage = psu.read_voltage(1)
print(voltage.nominal, voltage.u)
```

Active loads place readback accuracy under the operating mode range.

```yaml
device_type: dc_active_load
role: load
manufacturer: Test
model: ExampleLoad
operating_modes:
  constant_voltage_CV:
    ranges:
      - min: 0.0
        max: 10.0
        max_voltage_V: 10.0
        readback_accuracy:
          voltage_accuracy:
            model: linear
            range_percent: 1.0
            distribution: standard
            source: "ExampleLoad voltage readback specification"
```

```python
load.set_mode("CV")
voltage_result = load.measure_voltage()
voltage = voltage_result.values

print(voltage.nominal, voltage.u)
```

### Database Round Trip

Databases preserve the full `MeasurementQuantity` budget, not just the nominal
value and standard uncertainty.

```python
from pytestlab.experiments.database import MeasurementDatabase

measurement = dmm.measure(DMMFunction.VOLTAGE_DC)

with MeasurementDatabase("lab_results") as db:
    key = db.store_measurement(None, measurement)
    restored = db.retrieve_measurement(key)

restored_quantity = restored.values
print(restored_quantity.nominal)
print(restored_quantity.u)
print(restored_quantity.budget.components)
```

Legacy `uncertainties.ufloat` values also round-trip, but new uncertainty-aware
drivers use `MeasurementQuantity` so provenance stays attached.

### Accessory Chains

Instrument profiles describe only the instrument. PyTestLab never assumes a
probe, cable, lead, shunt, or current probe is attached just because an
instrument profile supports one. Accessories must be declared in `bench.yaml` or
constructed explicitly in code.

Accessory corrections reuse the same uncertainty model types as instrument
profiles. A 10:1 probe ratio is a dimensionless `MeasurementQuantity`; applying
it is ordinary multiplication, so the existing arithmetic propagation preserves
the instrument budget and adds the accessory components.

```yaml
accessories:
  probe_ch1:
    profile: keysight/N2142A
    serial_number: MY1234
    notes: Calibrated 10:1 passive probe used on VIN

measurement_plan:
  - name: input_ripple_vpp
    description: Input rail ripple at DUT VIN
    instrument: scope
    target:
      kind: oscilloscope_channel
      channel: 1
      measurement: vpp
    accessories: [probe_ch1]
```

```python
with pytestlab.Bench.open("bench.yaml") as bench:
    print(bench.measurement("input_ripple_vpp").describe())
    ripple = bench.measure("input_ripple_vpp")
    print(ripple.envelope["measurement_chain"])
```

`describe()` is intended to be physically auditable. It reports the path from the
DUT through the declared accessories into the instrument channel, the driver call
that will be made, the correction operations, and the accessory provenance from
`bench.yaml` such as alias, source preset/file, serial number, parameters, and
notes. A static description cannot know whether the future driver call will
return a complete instrument uncertainty budget. That status is recorded on the
measured result envelope after `measure()` or `MeasurementChain.apply()`.

Validate and inspect declared measurements before touching hardware:

```bash
pytestlab bench validate bench.yaml
pytestlab bench measurements bench.yaml
pytestlab bench measurement bench.yaml input_ripple_vpp
```

Executable `measurement_plan` entries use YAML `target:` for the measurement
function/channel to call. Existing descriptive entries remain valid, and their
free-form `settings:` are not interpreted as executable driver arguments. For
executable entries, PyTestLab rejects unknown settings keys so typos such as
`resoluton` do not silently change the experiment.

For ad hoc analysis, chains can also be applied directly:

```python
from pytestlab.accessories import AccessoryProfile, MeasurementChain

probe = AccessoryProfile.from_config("keysight/N2142A")
raw = scope.measure_voltage_peak_to_peak(1)
corrected = MeasurementChain([probe]).apply(raw)
```

Use `AccessoryProfile.from_config()` for packaged PyTestLab presets and
`AccessoryProfile.from_file()` for local lab profiles. Local bench files should
use `file: lab/probes/my_probe.yaml`; packaged presets use `profile:
keysight/N2142A`. Accessory profiles used by executable `measurement_plan`
entries must declare `compatibility.target_kinds` or explicitly set
`compatibility.unrestricted_target_kinds: true`; otherwise `bench validate` and
`Bench.open()` reject the chain before hardware initialization. DMM accessories
can further narrow compatibility with `compatibility.multimeter_functions`, for
example a lead-resistance correction should apply only to resistance functions.

If an instrument driver returns a plain float because its profile has no
uncertainty budget or `uncertainty_strict` is disabled, accessory application is
still allowed. The resulting envelope states that the instrument contributed no
uncertainty budget, so the budget is not mistaken for complete instrument-plus
accessory uncertainty.

### Strict-Mode Profile Qualification

Use `uncertainty_strict: true` when validating a profile. In strict mode,
configured uncertainty models that cannot be evaluated raise instead of being
logged and downgraded to a nominal float.

```yaml
device_type: oscilloscope
role: measurement
manufacturer: Test
model: BrokenScopeProfile
uncertainty_strict: true
measurement_accuracy:
  vpp_ch1:
    model: expression
    expression: "0.01*reading + 0.001*bandwidth"
    distribution: standard
```

If the driver or profile does not provide `bandwidth`, model evaluation raises:

```python
try:
    scope.measure_voltage_peak_to_peak(1)
except ValueError as exc:
    print(f"profile needs more context: {exc}")
```

Leave `uncertainty_strict` at its default `false` for backward-compatible
runtime scripts that should log a profile issue and keep returning nominal
floats until the profile is fixed.

### Choosing a Model

| Datasheet or calibration pattern | Recommended model |
|---|---|
| `+/- (% reading + % range + offset)` | `linear` |
| Counts or resolution terms | `linear` with `counts` and `resolution` |
| Different specs by frequency, range, temperature, or reading band | `band_table` |
| Compact formula using reading, range, bandwidth, channel, or NPLC | `expression` |
| Repeated observations from a calibration run | `repeatability` |
| Several independent terms that need to remain separately auditable | `composite` |
| Nonlinear propagation or simulated component distributions | `monte_carlo` |

Prefer the simplest model that preserves the scientific assumptions from the
source. Always record `source`, distribution, coverage assumptions, calibration
conditions, and unit assumptions for production profiles.

## Persistence

Databases store uncertain scalar values as structured measurement quantities:
nominal value, unit, standard uncertainty, expanded uncertainty, and the full
budget JSON. This avoids serializing raw Python objects and preserves the audit
trail across save/load boundaries. Legacy `uncertainties.ufloat` scalar, list,
and array values are normalized to nominal/standard-uncertainty pairs so older
results also round-trip through the database.

## Validation Lanes

Deterministic CI uses committed fixture profiles under
`tests/fixtures/uncertainty/`. Those profiles intentionally use small, synthetic
models with explicit assumptions so profile loading, driver context, and
database persistence can be regression-tested without hardware.

Real profile and hardware validation is opt-in:

```bash
pytest tests/instruments/test_uncertainty_real_hw.py -m requires_real_hw
```

Set `PYTESTLAB_UNCERTAINTY_HW_PROFILE` and
`PYTESTLAB_UNCERTAINTY_HW_ADDRESS` when a physical instrument is available.
Production profile entries should not be treated as scientifically reviewed
until their source, distribution, coverage assumptions, calibration conditions,
and unit assumptions are recorded in the profile review artifact.

## Practical Defaults

- Type B datasheet limits default to rectangular distribution.
- Expanded uncertainty defaults to `k=2`.
- `budget.coverage_factor_for(confidence)` uses effective degrees of freedom
  and SciPy's Student-t/normal quantiles when available.
- Unit compatibility and scaled-unit algebra are enforced with Pint when
  installed. For example, `1 V / 1000 mV` is treated as dimensionless `1`.
- Missing context required by a model raises an error instead of silently
  dropping uncertainty. Driver-level compatibility fallback is available only
  when `uncertainty_strict` is left at its default `false`.
