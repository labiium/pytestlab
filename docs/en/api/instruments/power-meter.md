---
title: RF Power Meter
description: Configure, capture, diagnose, and deliberately zero RF power sensors in PyTestLab.
---

# RF power meter

Both profiles expose one sensor channel (channel 1). See [datasheet uncertainty](power-meter-capabilities.md#power-datasheet-uncertainty).

## Read an already configured sensor

If the sensor is already set up for scalar average power, connect and take a fresh
reading. You don't need to reconfigure it or create a bench file.

```python
from pytestlab import AutoInstrument

meter = AutoInstrument.from_config(
    "rohdeschwarz/NRP18AN",
    address_override="TCPIP0::192.0.2.10::hislip0::INSTR",
)
try:
    power = meter.acquire_power()
    print(power.value, power.unit)
finally:
    meter.close()
```

Use the sensor's own VISA address. For a Keysight U2000A, use the packaged
`keysight/U2000A_PM` profile.

Bind named sensors in [`bench.yaml`](../../bench-yaml.md). Bench
`safety_limits` do not apply to RF meters, which are measurement devices.

```yaml
name: rf_power_bench
instruments:
  rf_meter:
    profile: rohdeschwarz/NRP18AN
    address: TCPIP0::192.0.2.10::hislip0::INSTR
```

```python
from pytestlab import Bench

with Bench.open("bench.yaml", aliases={"rf_meter"}, start_experiment=False) as bench:
    power = bench.rf_meter.acquire_power()
    print(power.value, power.unit)
```

`start_experiment=False` opens the sensor without starting a configured bench
experiment or its automation. It is not required to acquire power.

## Available workflows

| Workflow | Keysight U2000A | R&S NRP18AN |
| --- | --- | --- |
| Fresh scalar average | Average-only detector, immediate trigger | Continuous-average function, immediate or either external input |
| Fixed, automatic, or disabled averaging | Yes | Yes |
| Programmable aperture | No in this workflow | 10 µs to 2 s, normal (not fast) acquisition |
| Duty-cycle pulse average | 0.001–99.999%; known RF duty cycle | 0.001–100%; known RF duty cycle |
| RF envelope trace | Single-arm external or RF-envelope trigger; binary high/medium/low | No native trigger-referenced trace |
| Native scalar peak or random sample | No separate native feed; a trace can report its sampled maximum | Peak or random sample in the measurement interval |
| Time-gated average | Normal detector, internal or external rising/falling edge | Unsupported |
| Native buffered average | Not exposed; Keysight fast burst is a different acquisition mode | 2–8,192 results with immediate or external triggers |
| Condition registers and identity | Input overload and calibration status | Corrupt measurement, zero needed, and zero failure |
| One-shot zero | Internal isolation or quiet-input external zero | Quiet-input external zero only |

## Configure and acquire average power

With the sensor open, call `configure_power()` when first setting it up or changing
settings, not before each reading. Choose the actual RF frequency for sensor compensation:

```python
meter.configure_power(frequency_hz=2.4e9)
power = meter.acquire_power()
```

`configure_power()` stops the sensor's current acquisition and selects idle single
initiation, ASCII data, and native dBm unless `native_unit="W"` is requested.
Fixed averaging defaults to eight measurements. Use `averaging_mode="automatic"`
or `"disabled"` without specifying `averaging_count` for those modes. The reported
count is the sensor register, not an observed count in automatic or disabled mode.
NRP18AN also accepts an `aperture_s` setting independently of the averaging count.

Use `read_power_settings()` for a typed snapshot without arming the sensor, or
`acquire_power()` for a fresh reading and a new snapshot. The correction frequency
comes from your setup, not from measuring the carrier. Output units `dBm`, `W`,
`mW`, and `uW` are converted locally and do not change native units. Timestamps are
host receipt times, not sensor playback or trigger timestamps.

The NRP18AN's **continuous-average** function describes what it measures, not whether
triggering is continuous. For externally synchronized scalar or buffered acquisition,
configure `trigger_source="external_1"` (differential pair in the sensor cable) or
`"external_2"` (SMB). EXT1 supports rising/falling selection; for EXT2 omit
`trigger_edge` (readback is `None`). To trigger from Python, use
[scoped arming](power-meter-capabilities.md#synchronize-an-external-trigger-from-python).
For an RF envelope
trigger instead, select `trigger_source="internal"` and a `trigger_level_dbm`
between −40 and +23 dBm. The trigger sender must be off before selecting
internal triggering and before any verified NRP18AN scalar or buffer acquisition.
Immediate triggering also requires trigger sync off. These outputs are
operator-owned: PyTestLab checks their state without changing them.
Initial setup uses zero delay and no artificial triggers.

## Capture a native average-power buffer (NRP18AN only)

```python
with Bench.open("bench.yaml", aliases={"rf_meter"}, start_experiment=False) as bench:
    meter = bench.rf_meter
    meter.configure_power(
        frequency_hz=2.4e9,
        averaging_count=4,
        aperture_s=250e-6,
        mode="buffered_average",
        sample_count=16,
    )
    capture = meter.acquire_power_buffer(unit="mW", timeout_ms=5_000)
    print(capture.values, capture.settings.sample_count)
```

Each entry is a distinct average-power result, not a raw RF waveform. The workflow
verifies the full buffer and matching trigger count, clears old buffer contents,
arms once, waits for completion, and rejects short, malformed, or questionable
data. There is no inferred per-reading time axis. An external buffer needs one
usable trigger per result; space edges far enough apart for the selected aperture
and averaging. Use `configure_power(mode="average", frequency_hz=...)` to return to scalar
mode; `acquire_power()` does not silently disable buffering.

## Measure average power within a gate (U2000A only)

With the `rf_meter` alias bound to `keysight/U2000A_PM`:

```python
with Bench.open("bench.yaml", aliases={"rf_meter"}, start_experiment=False) as bench:
    meter = bench.rf_meter
    meter.configure_power(
        frequency_hz=2.4e9,
        averaging_count=4,
        mode="gated_average",
        gate_offset_s=200e-6,
        gate_duration_s=400e-6,
    )
    power = meter.acquire_power(mode="gated_average", timeout_ms=2_000)
    print(power.value, power.unit, power.settings.gate_duration_s)
```

Connect the documented Keysight external trigger input and provide the selected edge
after the sensor arms (rising by default). To trigger on the RF envelope instead,
set `trigger_source="internal"` and `trigger_level_dbm` (−50 to +20 dBm for U2000A). Gate offset is relative to the delayed trigger point; ordinary setup starts with
zero delay. If you [adjust trigger timing](power-meter-capabilities.md#setting-trigger-timing),
`settings.gate_window_s` includes the actual delay and offset from the detected edge.
Use a gate inside the settled part of the RF burst; Keysight recommends allowing
150 µs after the rising edge and 40 µs before the falling edge. The Normal
detector has less dynamic range than Average-only. This workflow does not generate
or synchronize an external pulse; arrange the trigger in your bench setup.
The NRP18AN cannot do this measurement. The NRP18SN is a different model with a
distinct timeslot mode; it is not supported by this profile.

## Measure a known duty-cycle pulse average

```python
meter.configure_power(
    frequency_hz=2.4e9, mode="pulse_average", duty_cycle_percent=25, averaging_count=8
)
pulse = meter.acquire_power(mode="pulse_average", unit="dBm")
print(pulse.value, pulse.settings.duty_cycle_percent)
```

This is the sensor's duty-cycle-corrected average, not a time gate, peak measurement,
or measurement of duty cycle. Supply percent (25, not 0.25, for one-quarter on-time)
and choose it from the actual RF waveform. The workflow enables correction and
verifies the live value. Plain verified average, gated average, R&S peak/random,
and buffered average reject active duty-cycle correction rather than relabeling it.

## Capture a Keysight RF envelope trace

```python
meter.configure_power_trace(
    frequency_hz=2.4e9,
    duration_s=1e-3,
    offset_s=-200e-6,
    trigger_source="internal",
    trigger_level_dbm=-10,
    trigger_edge="rising",
)
trace = meter.acquire_power_trace(resolution="high", unit="dBm", timeout_ms=2000)
print(trace.settings.time_window_s, trace.sampled_peak)
```

Use `trigger_source="external"` for a TTL edge on the sensor's external input and
omit the internal level. The capture uses Normal detection, one trigger cycle,
no automatic delay, and no averaging or frequency stepping. It explicitly arms a
new acquisition, checks completion and errors, and then reads the big-endian
IEEE-488.2 float32 block. Keysight's low/medium formats return 230/1,000
decimated points; high returns the full capture buffer. The API provides ordered
samples and verified window bounds in seconds relative to the trigger, not a
per-point timing calibration. The guide does not specify decimation indices,
endpoint alignment, or sample timestamps; do not infer them from point count.
`sampled_peak` is the maximum returned point, not a guaranteed pulse peak.

## Read an NRP18AN peak or random sample

```python
meter.configure_power(frequency_hz=2.4e9, mode="peak", aperture_s=250e-6)
peak = meter.acquire_power(mode="peak")
```

Use `mode="random_sample"` for the sensor's randomly selected value from the
measurement interval. These are native continuous-average-function feeds, not
trace samples with known times, statistics over separate host readings, or a
promise of peak bandwidth. They do not override the configured averaging,
aperture, or triggering. Auxiliary `MINMAX`/`RNDMAX` payloads are not decoded.

## Inspect corrections and trigger state

See [corrections and trigger state](power-meter-capabilities.md#inspect-corrections-and-trigger-state)
for the fixed offsets, actual trigger settings, and NRP18AN reference-plane workflow.

## Diagnose or deliberately zero the sensor

```python
status = meter.sensor_status()
print(status.model, status.serial_number, status.active_conditions)

# Only after switching off or removing RF at the sensor's input:
meter.zero_sensor()
# U2000A only: isolated internal zero, if it meets your accuracy requirements.
# meter.zero_sensor(mode="internal")
# Still with RF off, a deliberate native electronics test:
# result = meter.run_self_test()
```

`sensor_status()` reads live power and calibration condition registers, not event
registers or the error queue. Measurement workflows never zero the sensor. Before
an external zero or self-test, switch off or disconnect RF at the sensor input.
Call these maintenance methods directly; bulk instrument checks do not run them.
The live manufacturer and model, plus the serial number when configured,
must match the bench binding before any zero-related write. Set the serial
number on the bench entry if a same-model sensor swap must be detected.
`zero_sensor()` refuses if the sensor is continuously initiating, measuring, armed,
or already calibrating. It does not stop an RF source or a measurement for you.
On U2000A the selected internal/external zero type persists after the call, so it can
affect the sensor's own automatic zero facility. A zero is not a full calibration.
`run_self_test()` uses the same identity and idle checks and returns an
`InstrumentSelfTestResult` with `passed` and the native result code, without
clearing the SCPI error queue. It can take tens of
seconds; the Keysight guide gives approximately 40 seconds.

## Timeouts, recovery, and legacy methods

The timeout is a shared SCPI I/O budget after the connection and lock
are acquired. No result is returned for a missed edge, a rejected acquisition, a
stale/overload sentinel, or uncertain data. On ambiguous transport failure or interruption the
driver tries a native Device Clear when the active backend provides it, with a
separate 250 ms communication timeout. This is not a reset or `*CLS`. If the clear
is unavailable or fails, the sensor may still be armed or have an unread reply.
Perform a device clear and reopen the bench before retrying; neither verified nor legacy power
methods reuse the uncertain session. Even when clear succeeds, the original call fails. A timed-out zero may have altered
the sensor even when Device Clear succeeds. The meter object stays quarantined;
verify the sensor at the bench and reopen the bench before resuming.

`configure_sensor()`, `read_power()`, and `measure_power()` keep their existing interfaces. The
legacy `read_power()` can return the last available value, as a float in native
units. For verified settings and a bounded fresh acquisition, use the workflow above.
Measurement workflows do not turn on RF, reset, zero, or calibrate the sensor.
The operator is responsible for correct RF level and valid calibration. Other
instrument-side corrections, such as external attenuation or user calibration tables,
are not changed by this workflow.

See the [manual-backed capability matrix](power-meter-capabilities.md) for
mode-specific details, remaining workflows, and verification plans.

These command sequences were verified against the vendor manuals and tested with
offline SCPI transcripts, not physical sensors.

- [Keysight U2000 Series programming guide](https://www.keysight.com/mt/en/assets/9018-01701/programming-guides/9018-01701.pdf), U2000-90411 (edition 8): pp. 24–25, 72, 93–110, 114–115, 190–207, 220–222, 229–242, 264–282, 305–310, 314–316, 329–344, 361–362, 374, 384–389. PDF SHA-256: `03819c1c5f018319725bb1648ce9f742d4bdf8103cceba620df52647e6d8977c`.
- [R&S NRPxA(N) manual](https://scdn.rohde-schwarz.com/ur/pws/dl_downloads/pdm/cl_manuals/user_manual/1177_6017_01/NRPxAN_UserManual_en_18.pdf), 1177.6017.02 v18: §§9.2–9.9, 9.11.8, 10.1, 10.3, 11.2.3, 11.2.5. PDF SHA-256: `d7e8407c660b97b14e7e29fddcdc68b93661bcdc8234add9ca88a5e18335c4d8`.
- [R&S NRPxS(N) manual](https://scdn.rohde-schwarz.com/ur/pws/dl_downloads/pdm/cl_manuals/user_manual/1177_5079_01/NRPxSN_UserManual_en_26.pdf), 1177.5079.02 v26: the separate timeslot mode is outside this profile. PDF SHA-256: `af0d11dd5444a6b63feb43c95be14fd2357278db33fde5826e4cb224151e1d77`.

::: pytestlab.instruments.PowerMeter
    options:
      filters:
        - "!^_"
        - "!^to_measurement_result$"
        - "!^(PowerTriggerTiming|configure_power_trigger_timing|read_power_trigger_timing|ArmedPowerCapture|arm_power)$"
