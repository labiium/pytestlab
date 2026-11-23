---
title: Impedance analyzer
---

# Impedance analyzer

Use the packaged profile and the analyzer’s actual VISA resource. A Bench
alias is convenient for shared setups, not required. For a direct connection:

```python
from pytestlab import AutoInstrument

analyzer = AutoInstrument.from_config(
    "keysight/E4990A", address_override="TCPIP0::YOUR_ANALYZER::inst0::INSTR",
)
try:
    curve = analyzer.read_impedance_sweep()  # Use an already completed, held sweep.
finally:
    analyzer.close()
```

If you prefer a Bench alias, the same profile and address can go in an inline
descriptor or an optional `bench.yaml`:

```yaml
bench_name: Impedance sweep
instruments:
  impedance:
    profile: keysight/E4990A
    address: "TCPIP0::YOUR_ANALYZER::inst0::INSTR"
```

For the Hioki, use `hioki/IM3570` and the instrument's configured VISA resource.
For example, for LAN use `TCPIP0::YOUR_ANALYZER::PORT::SOCKET` with the configured
port, rather than copying the Keysight address. Match any non-default
terminators in the bench transport settings.

## Read a completed sweep

First perform the measurement on the instrument with safe excitation and a
compensated fixture. Leave it stopped and do not change front-panel settings
while reading.

```python
from pytestlab import Bench

with Bench.open("bench.yaml", aliases={"impedance"}, start_experiment=False) as bench:
    analyzer = bench.impedance
    curve = analyzer.read_impedance_sweep()
    resonant = min(curve.readings, key=lambda point: point.magnitude_ohm)
    print(resonant.frequency_hz, resonant.impedance_ohm, resonant.phase_deg)
```

The result exposes aligned `frequency_hz` and `impedance_ohm` tuples in instrument
order. Frequency values come from the measurement's actual axis, not an axis
reconstructed from endpoints. Channels and points are 1-based.
`read_impedance_sweep()` does not write, trigger, establish buffer age, or
certify calibration.

- **Keysight E4990A:** Use ASCII transfer and hold a linear, log, or segmented
  frequency sweep. Select the complex impedance (IMP) measurement and complex
  R-X format, with no trace data math. The full sweep uses the actual frequency
  data and formatted complex values, rejecting invalid numeric values (including
  the instrument's invalid-measurement token) and inconsistent point counts.
  The instrument does not report a separate point status in this format, so
  `status` is `None`.
- **Hioki IM3570:** Use ANALYZER mode, a non-segmented frequency sweep set using
  START-STOP, and sequential or step trigger. Select Z and PHASE on the
  instrument and use ASCII transfer, headers on, automatic output off, and
  `VALID=22` (status, sweep-point value, measurements). Complete every point
  before reading. Each point must include normal status; a malformed, missing,
  or non-normal point fails the whole read. Only logical channel 1 is supported.

The original `read_impedance(point=2)` API is still available. It reads a single
held point. On the E4990A it retains its original RDAT path, which does not expose
the formatted invalid-measurement status.

See [impedance sweep export](impedance-sweep-export.md) for DataFrame, CSV,
and replay, or [store a sweep with each trial](../../user_guide/measurement_session.md#store-a-waveform-or-sweep-with-each-trial).

## Read native impedance and admittance quantities

`read_measurement_sweep()` reads a native scalar result in engineering units.
Choose series or parallel capacitance/inductance explicitly: they are
different instrument measurement parameters. Resistance is series R; X is
series reactance. Q and D are dimensionless. Admittance magnitude, conductance
and susceptance are reported in siemens; parallel resistance is in ohms. The
E4990A also reports admittance phase. This does not derive values from complex
Z or retrigger when the prepared buffer does not match.

```python
from pytestlab.instruments.ImpedanceAnalyzer import ImpedanceParameter

with Bench.open("bench.yaml", aliases={"impedance"}, start_experiment=False) as bench:
    capacitance = bench.impedance.read_measurement_sweep(
        ImpedanceParameter.PARALLEL_CAPACITANCE
    )
    print(capacitance.frequency_hz, capacitance.values, capacitance.unit)  # Hz, F
```

- **E4990A:** Select the matching active trace, hold the sweep, use ASCII
  transfer and Normal trace math. For phase, select degrees and disable phase
  expansion; the driver will reject the radians format.
  `configure_measurement_parameter(parameter, trace=2)` can define and verify
  a trace that already exists without activating it; use `parameter="impedance"`
  for complex IMP. Select the desired active trace and complex R-X format
  on the instrument when needed.
- **IM3570:** Select either Analyzer slot from the front panel or with
  `configure_measurement_parameter(parameter, trace=2)`.
  Logical slots 1 and 2 correspond to Hioki's shared PARA1 and PARA3
  settings. To prepare complex impedance, set slot 1 to magnitude and slot 2
  to phase. Stop any measurement, physically disconnect the DUT, and
  isolate external trigger/panel-load and bias wiring first; comparator and
  internal bias must be OFF. Labelled ASCII points are then checked
  individually. A slot edit does not switch into LCR mode or capture data.

## Configure a sweep without a connected DUT

Both profiles can set and read back a linear or log frequency span and point
count. Prepare the normal, held frequency mode on the instrument first.
**Physically disconnect the DUT before using this method**. A stopped sweep is
not a guarantee that the instrument's terminals are de-energized.

```python
with Bench.open("bench.yaml", aliases={"impedance"}, start_experiment=False) as bench:
    settings = bench.impedance.configure_frequency_sweep(
        start_hz=1_000, stop_hz=49_000, points=51, spacing="log",
    )
    print(settings)
```

Configuration uses the installed E4990A frequency option's reported limits.
The IM3570 uses its native START-STOP command (up to 801 points, 4 Hz to 5 MHz).
The settings returned are the values the instrument accepted, with small
rounding differences allowed. Neither profile sends a trigger, resets the
instrument, changes fixture correction, or writes excitation or bias
settings. The instrument itself can change the drive as frequency changes.
A failed verification can leave sweep settings partly applied.

On the **IM3570**, the driver requires a readback of internal DC bias and
the Comparator function both OFF before writing. Keep the DUT physically
disconnected, wait until the sweep stops, and isolate external trigger,
panel-load and bias sources: changing a measurement condition can emit the configured DC
level even with trigger-synchronous output enabled ([instruction manual,
§5.9.10, pp. 235–236](https://shop.hioki.eu/media/53/a4/9e/1736346059/IM3570A981-08_Manual_EN.pdf#page=243)).
For a stop above 1 MHz, the driver also requires verified open-circuit voltage
mode (V), not constant voltage (CV) or constant current (CC). On firmware
V1.00–V3.13, a frequency sweep crossing 1 MHz in CV or CC can raise the drive
to 1 V or 10 mA, respectively. Later sweeps may retain that higher drive
while the initial screen still displays the earlier value. Hioki fixed this
in V3.14 for the affected hardware; V4.00 is for a different hardware revision.
[Hioki incident notice](https://www.hioki.com/jp-ja/important/id_1269003.html)
· [Hioki release history (English)](https://www.hioki.com/us-en/support/download/software/versionup/detail/id_519)
· [Hioki hardware revision note](https://www.hioki.com/jp-ja/support/download/software/versionup/detail/id_519)

Edits to sweep points or Analyzer display parameters can invalidate the
IM3570 comparator settings. Re-enter or revalidate stored thresholds before
turning Comparator on again (instruction manual pp. 169 and 199).

Before reconnecting the DUT, confirm the actual drive and bias for the final
setup and full sweep range. A displayed setpoint alone is not evidence of
actual output.

## Inspect and edit a segmented frequency sweep

For either profile, enable segmentation and establish the desired number of
rows on the front panel. Leave the analyzer in held frequency mode. On
IM3570, use Analyzer and Sequential or Step, not Repeat. Independently
confirm the sweep has ended and physically isolate external trigger and
panel-load wiring. The mode readback alone does not confirm idle.

```python
with Bench.open("bench.yaml", aliases={"impedance"}, start_experiment=False) as bench:
    analyzer = bench.impedance
    table = analyzer.get_segmented_sweep()
    print(table.total_points, table.segments)
    # Physically disconnect the DUT and isolate external bias before editing.
    row = analyzer.configure_frequency_segment(
        1, start_hz=1_000, stop_hz=4_000, points=41,
    )
    print(row)
```

The API reads the actual table and preserves instrument row order. An
existing row can be edited and verified without starting a sweep, changing
row count, or changing its source, averaging, timing, or range. After
editing, independently verify physical stimulus and fixture compensation
before reconnecting the DUT. A failed verification can leave the new
setting partly applied.

- **E4990A:** 201 rows, 1601 total points, linear spacing. The vendor array
  reports optional per-row oscillator, DC bias, speed, averaging, segment
  time and delay; these are programmed values with typed units, not measured
  DUT levels. Editing requires both list oscillator and list bias off,
  internal bias off, and the installed frequency limits satisfied.
- **IM3570:** 20 rows, 801 total points, linear or logarithmic. Read per-row
  source level, range, speed, averaging and delay. Editing requires
  Comparator and internal bias OFF, verified V (open-circuit voltage) drive,
  and physical idle/trigger isolation, which the operator must verify. Both
  the existing and edited table must stay within 1 MHz. Tables above 1 MHz
  can be inspected but not edited, due to the high-band drive advisory. Revalidate stored
  comparator settings before re-enabling them. This does not add fresh or
  buffered segmented data capture on the IM3570.

## Inspect and tune a prepared sweep

`get_measurement_settings()` reports the model's speed step (1 is fastest) and
effective averaging count (1 means disabled). On the E4990A this is **point**
averaging, not sweep averaging; it has speed steps 1–5 and averaging 1–999.
The IM3570 has four speed steps (Fast, Medium, Slow, Slow2), averaging 1–256,
and either auto range or a reported fixed nominal range. A high fixed range
may be unavailable at the sweep's stop frequency.

```python
with Bench.open("bench.yaml", aliases={"impedance"}, start_experiment=False) as bench:
    analyzer = bench.impedance
    # Disconnect the DUT and isolate any external bias before making changes.
    print(analyzer.configure_measurement_settings(
        speed_step=2, averages=1,
    ))
    print(analyzer.configure_voltage_excitation(0.025))
    print(analyzer.get_fixture_correction())
```

For the IM3570, add `range_mode="auto"` or `range_mode="fixed"` with
`fixed_range_ohm` to change range. `get_excitation()` reads the programmed
AC mode and level and internal DC-bias state, not DUT terminal voltage or
current. `configure_voltage_excitation()` is limited to 5 mVrms–1 Vrms in an
already configured voltage mode with bias OFF. E4990A additionally requires
ALC OFF; the IM3570 requires V, not CV or CC, and at least 10 mVrms above 1 MHz.
It does not switch modes, enable or adjust bias, or program current. A failed
write or readback may leave settings partly applied; verify the front panel
and physical output before reconnecting a DUT.

`get_fixture_correction()` reports enabled states, not whether stored
compensation data is valid for these leads/fixture, standards or sweep
conditions. The E4990A exposes open, short and load; the IM3570 Analyzer
exposes open and short and returns `None` for load (the load query is LCR-only).

Use `get_fixture_setup()` after operator calibration and before measuring.
On E4990A it also reports the independent port/user calibration flag and
port-extension state and time in seconds. On IM3570 it reports open/short
mode (OFF/ALL/SPOT), cable compensation in metres, the configured AC
compensation frequency range, and whether scaling is enabled. Compare
those values to your physical standards, cable, and intended sweep. The
driver does not collect, apply, erase, validate or save a standard. Run the vendor's physical compensation
procedure with the actual standards. The API does not collect, alter or erase
correction standards.

## Check a retained calibration standard

Perform the physical calibration with the manufacturer's procedure and the
actual fixture and standard. Wait for calibration and any sweep to finish.
Then distinguish **what corrections are applied** (`get_fixture_setup()`)
from **what numerical standard data is retained** (`read_fixture_standard()`).

```python
with Bench.open("bench.yaml", aliases={"impedance"}, start_experiment=False) as bench:
    analyzer = bench.impedance
    fixture = analyzer.get_fixture_setup()
    record = analyzer.read_fixture_standard("open")
    print(fixture.correction, record.ac_span_hz, len(record.samples), record.unit)
```

- **E4990A:** With the channel held and ASCII transfer, select `"open"`,
  `"short"` or `"load"`. The default `calibration_layer="fixture"` reads
  CAL2 fixture compensation. `calibration_layer="user"` reads the separate
  CAL1 user data. Results use the stored calibration frequency axis and
  complex impedance in ohms. A port/user enable flag applies to the CAL1
  layer, not to an individual record.
- **IM3570:** Use stopped Analyzer mode (Sequential or Step, automatic
  output OFF). The default reads retained **ALL** data for `"open"` or
  `"short"`. Use `spot=1` to `spot=5` to inspect that slot instead, without
  changing which compensation is applied. OPEN is complex admittance in
  siemens; SHORT is complex impedance in ohms. 0 Hz denotes DC. A disabled
  SPOT returns no samples. The model can report zero for uncaptured
  compensation, and its result flag does not prove when a stored sample was
  acquired. Load compensation is not exposed in Analyzer.

The AC span describes the returned records only. It does not prove continuous
coverage, interpolation accuracy, fixture identity, current calibration,
or that the correct standard was attached. Selecting a record here never
collects, applies, clears, or saves calibration.

## Inspect prepared limit tests

See [prepared limit tests](impedance-capabilities.md#inspect-prepared-limit-tests)
for read-only Keysight limit tables and Hioki comparator thresholds.

## Acquire a fresh sweep on a prepared Keysight

Set the active channel to the requested channel, trigger **BUS** with **Active**
scope, and leave the channel held. Use a normal linear or log frequency sweep,
point trigger off, point and sweep averaging off, bias off, voltage mode, and AC level
control (ALC) off. Prepare the complex IMP trace as above. Verify the physical
fixture, wiring, and any external sources; the software cannot read those.
Before reconnecting or triggering, check the allowed current, voltage, and
frequency against the DUT's limits.

```python
with Bench.open("bench.yaml", aliases={"impedance"}, start_experiment=False) as bench:
    curve = bench.impedance.acquire_impedance_sweep()
    assert curve.fresh
```

The driver verifies that the programmed voltage is inside the
[documented 5 mVrms–1 Vrms source range](https://helpfiles.keysight.com/csg/e4990a/programming/command_reference/source/sour_volt.htm)
and checks the bias and trigger state before arming. Pass
`max_excitation_v_rms=0.05` (or another DUT-appropriate value) to lower that
ceiling. This is a setpoint check, not a measurement of terminal voltage or
a guarantee of physical DUT safety. The profile ceiling is not a recommended
DUT level; for loads at or below 50 Ω, Keysight recommends at most 0.5 Vrms.
Use the typed Python setup and acquisition methods deliberately; generic
profile diagnostics skip their guarded write commands.

The method requests one sweep, checks completion and errors, returns the
channel to hold, and fetches the curve under one host-side timeout budget.
It does not set the oscillator or turn on bias. A result received
after that deadline is not accepted. On failure, it attempts to abort the sweep
and verify hold if the stream is usable. If a timed-out command could have left
an unread reply, it requires native Device Clear before any more SCPI. If cleanup
cannot be verified, the analyzer session is blocked from further impedance
operations. Stop or hold the sweep at the instrument, make the DUT safe, clear
the interface, and verify the front-panel state before opening a new session.
No failure is treated as a successful acquisition of older buffered data.

## IM3570 acquisition limits

On the IM3570, perform and stop a sweep from the front panel before reading.
The [communication command manual](https://www.hioki.com/e/products/lcr/application/IM3570/English/Files/03/Right03.htm)
defines `ESR0` events for individual points, not whole sweeps. Hardware
EOM timing does not establish completion through SCPI. PyTestLab only reads
held data on the Hioki; it neither triggers nor proves freshness.

Bias/current programming, table activation or row creation/deletion, and
automated fixture calibration are not supported. Use `supports_operation()` and
`list_operation_options()` to inspect what the profile supports.

See the [model capability inventory](impedance-capabilities.md) for the wider
manual surface, options and evidence status.

## Programming references

- Keysight [E4990A Programming Help](https://helpfiles.keysight.com/csg/e4990a/home.htm):
  [stimulus array](https://helpfiles.keysight.com/csg/e4990a/programming/command_reference/sense/sens_freq_data.htm),
  [formatted data and invalid sentinel](https://helpfiles.keysight.com/csg/e4990a/programming/command_reference/calculate/calc_data_fdat.htm),
  [measurement parameters](https://helpfiles.keysight.com/csg/e4990a/measurement/setting_up_the_display_of_measurement_results/selecting_measurement_parameters.htm),
  [measurement speed](https://helpfiles.keysight.com/csg/e4990a/programming/command_reference/sense/sens_aper.htm),
  [stored standard arrays](https://helpfiles.keysight.com/csg/e4990a/programming/command_reference/sense/sens_corr_zme_open.htm),
  [limit table layout](https://helpfiles.keysight.com/csg/e4990a/programming/command_reference/calculate/calc_lim_data.htm),
  and the Help sections on point averaging, oscillator, and fixture compensation.
- Hioki [IM3570 Communication Command Manual](https://www.hioki.com/e/products/lcr/application/IM3570/English/Files/03/Right03.htm):
  START-STOP setup, sweep-point query, measurement response selection,
  segment mode, DC bias, source level, range, speed, averaging, and EOM/status
  registers. The [IM3570 instruction manual](https://shop.hioki.eu/media/53/a4/9e/1736346059/IM3570A981-08_Manual_EN.pdf)
  covers source accuracy (pp. 45–46), synchronized parameters and sequential
  trigger modes (pp. 133–138), Analyzer tuning (pp. 157–168), fixture
  compensation (Chapter 7) and Analyzer EOM timing (p. 372).

These workflows were tested offline, not on hardware.

::: pytestlab.instruments.ImpedanceAnalyzer.ImpedanceAnalyzer

::: pytestlab.instruments.ImpedanceAnalyzer.ImpedanceReading
    options:
      filters:
        - "!^_"
        - "!^to_measurement_result$"

::: pytestlab.instruments.ImpedanceAnalyzer.ImpedanceSweep
    options:
      filters:
        - "!^_"
        - "!^to_measurement_result$"

::: pytestlab.instruments.ImpedanceAnalyzer.ImpedanceSweepSettings

::: pytestlab.instruments.ImpedanceAnalyzer.ImpedanceParameter

::: pytestlab.instruments.ImpedanceAnalyzer.ImpedanceMeasurementSweep
    options:
      filters:
        - "!^_"
        - "!^to_measurement_result$"

::: pytestlab.instruments.ImpedanceAnalyzer.ImpedanceMeasurementSettings

::: pytestlab.instruments.ImpedanceAnalyzer.ImpedanceExcitation

::: pytestlab.instruments.ImpedanceAnalyzer.ImpedanceFixtureCorrection

::: pytestlab.instruments.ImpedanceAnalyzer.ImpedanceSegmentedSweep

::: pytestlab.instruments.ImpedanceAnalyzer.ImpedanceFrequencySegment

::: pytestlab.instruments.ImpedanceAnalyzer.ImpedanceSegmentLevel

::: pytestlab.instruments.ImpedanceAnalyzer.ImpedanceFixtureSetup

::: pytestlab.instruments.ImpedanceAnalyzer.ImpedanceFixtureStandard

::: pytestlab.instruments.ImpedanceAnalyzer.ImpedanceStandardSample

::: pytestlab.instruments.ImpedanceAnalyzer.ImpedanceTraceLimitTable

::: pytestlab.instruments.ImpedanceAnalyzer.ImpedanceComparatorLimits
