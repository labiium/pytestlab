---
title: RF Power Sensor Capability Matrix
description: Vendor-manual evidence, implemented PyTestLab workflows, and deferred verification for U2000A and NRP18AN.
---

# RF Power Sensor Capability Matrix

The mappings below apply to the **Keysight U2000A** and the **Rohde & Schwarz
NRP18AN** profiles. Each is one sensor channel, not a multichannel mainframe.
“Implemented” means a typed or existing driver workflow with offline tests,
not hardware qualification. “Deferred” means hardware is documented but no
supported high-level method is supplied here. “Not applicable” means the
covered manual/model does not provide the same function. A known command in a
profile is not itself a guarantee of a safe workflow.

References: [U2000 Series Programming Guide](https://www.keysight.com/mt/en/assets/9018-01701/programming-guides/9018-01701.pdf)
(U2000-90411, edition 8); [U2000 Operating and Service Guide](https://www.keysight.com/az/en/assets/9018-01703/user-manuals/9018-01703.pdf)
(Normal detector, trace and gate illustrations pp. 38–40);
[R&S NRPxA(N) User Manual](https://scdn.rohde-schwarz.com/ur/pws/dl_downloads/pdm/cl_manuals/user_manual/1177_6017_01/NRPxAN_UserManual_en_18.pdf)
(1177.6017.02, v18; applies to FW 03.40 and newer).
The adjacent [power-meter workflow examples](power-meter.md) show current bench usage.

## Power datasheet uncertainty

Acquisition and persistence are nominal by default. For a known continuous-wave
signal at the sensor input, opt in when converting the fresh scalar result:

```python
from pytestlab.instruments.PowerMeter import PowerCWConditions

reading = meter.acquire_power()
record = reading.to_measurement_result(
    cw_conditions=PowerCWConditions(
        frequency_hz=2.4e9,
        ambient_temperature_c=22,
        warmup_s=1800,
        temperature_storage_s=10800,
        path_selection="automatic",
        transition_offset_db=0,
    )
)
```

This R&S example assumes the actual physical conditions shown, current
calibration, all applicable adjustments complete, and no user correction or
external loss applied to the sensor input result. The source frequency must
match the acquisition's correction frequency. The conversion performs no I/O.
Use `record.uncertainty` for the **sensor-only** uncertainty component in watts;
`record.nominal` and `record.units` still describe the original reading.

- **R&S NRP18AN:** Only immediate average power above −40 through +23 dBm,
  within 8 kHz–18 GHz at 20–25 °C, after three hours at the operating
  temperature and at least 30 minutes powered on. Automatic path selection
  and a 0 dB transition offset are required. Uses the conservative 0.094 dB
  upper endpoint of the published absolute component with `k=2`, converted
  to standard uncertainty in watts by first-order propagation. This covers
  sensor calibration, linearity and temperature effects, not zero, drift,
  noise or mismatch. [R&S data sheet, v15, pp. 3, 6, 26–29 and note 8](https://www.rohde-schwarz.com/us/brochure-datasheet/nrp-a-an/).
- **Keysight U2000A:** Supply `zero_age_s` for a sensor already zeroed at the
  bench and warmed up for at least 30 minutes. Only immediate Average-only
  acquisition with 1024 manual averages, 10 MHz–18 GHz and −60 to +20 dBm
  is covered. The published ±3.0% (15–35 °C) or ±3.5% (0–55 °C) is an
  accuracy limit, not a standard uncertainty. It is stored in
  `record.envelope["accuracy_limit"]`. An explicitly chosen
  `accuracy_limit_distribution="rectangular"` or `"triangular"` optionally
  treats that bounded term as a Type B component. Those assumptions are not
  vendor confidence levels. Frequency-dependent calibration factor, zero,
  drift, noise and mismatch remain outside the term; Keysight advises
  external zeroing below −30 dBm. [Keysight 5989-6278EN, Average only mode power accuracy, notes 7–8](https://www.keysight.com.cn/cn/zh/assets/7018-01515/data-sheets/5989-6278.pdf).

Unsupported modes or conditions still return the nominal measurement, with a
reason in its envelope and no numerical uncertainty attached. The attached
component is not a serial-specific calibration or a report-grade uncertainty
for a DUT. The separate NRP18AN reflection readback continues to report the
sensor's expanded **reflection-magnitude** uncertainty. Its native result exposes
that term in standard form via `record.uncertainty`, without assigning any phase
or power uncertainty.

## Measurement, acquisition, and triggering

| Subsystem/workflow | U2000A | NRP18AN | Evidence and remaining acceptance tests |
| --- | --- | --- | --- |
| Absolute RF power / selection | **Implemented:** average-only detector, one immediate acquisition; separately Normal detector for gate/trace. | **Implemented:** continuous-average function with single initiation; no implication of continuous triggering. | Keysight pp. 83–101, 206–208; R&S §§9.3.3–9.5, 10.1. Verify fresh rearm and native-unit/compensation round-trip under CW signal changes. |
| Aperture, averaging, settling | **Implemented:** manual/automatic/disabled filtering in Normal-rate workflows; **deferred:** expected level/resolution controls, range and measurement rate tuning. | **Implemented:** 10 µs–2 s normal aperture, manual/automatic/disabled averaging, repeat termination. **Deferred:** moving termination, NSR/resolution/maximum-time tuning, smoothing, fixed range, measurement path/ref source and 8 µs fast-unchopped mode. | Keysight pp. 43–46, 86–98, 175–186, 220–222, 398; R&S §§9.3.1–9.3.3, 9.5.1, 9.6.1, 10.2. Characterize first valid output, noise/settling, and range transitions; verify unsupported combinations. |
| Triggered scalar/gate controls | **Implemented:** immediate scalar, internal or external rising/falling gated average, explicit RF level, verified signed delay/holdoff and internal hysteresis. **Deferred:** hold/remote/bus and continuous modes. | **Implemented:** immediate, EXT1 differential cable and EXT2 SMB, internal RF envelope in dBm, rising/falling for internal and EXT1 only (EXT2 edge unreported), manual nonnegative delay/holdoff and internal dropout/hysteresis; sender must be off before all verified starts and sync off for immediate starts. **Deferred:** additional level units, hold/bus, automatic triggering, negative delay, sync/sender, EXT2 termination and free run. | Keysight pp. 229–235, 311–345, 385–386; R&S §9.4. Validate level units under offset, port direction and termination, missed-edge policy, readiness and dwell, and completion on finite rearm. |
| Trigger operations and live state | **Implemented:** non-clearing wait/measure/calibrate/continuous state snapshot, fresh arm/abort as part of typed capture. **Deferred:** standalone asynchronous arm/abort/trigger and status event routing. | **Implemented:** same snapshot, blocking capture and scoped external arm → live ready → fetch/abort. **Deferred:** native bus trigger and event routing. | Keysight pp. 264–277, 314–328; R&S §§9.4, 11.2.5. Test no stale late events, native clear, and exclusion between open acquisitions and independent state changes. |
| Time-gated average | **Implemented:** trigger-referenced Normal detector gate, signed offset, signed trigger delay and actual quantized duration. | **Not applicable:** this model does not have timeslot or triggered envelope trace mode; NRP18SN is a distinct model and manual. | Keysight pp. 229–234, 385–386; R&S §9.3.3. Verify range settling and known pulse widths on the bench, including falling-edge placement. |
| Trace and derived peak | **Implemented:** Normal detector, internal/TTL edge, level for internal, verified signed offset/duration, W/dBm capture, three resolutions, fixed big-endian IEEE block; returned sample maximum only. **Deferred:** exact point timestamps and automated pulse parameters. | **Not applicable:** no equivalent trigger-referenced native trace. | Keysight pp. 237–242, 305–310, 315–316, 362, 387. Binary/framing, INIT rejection, false/late completion, and trigger-order transcript coverage. Bench plan: pulse marker at known start/stop; verify HRES count/sample alignment and MRES/LRES decimation against HRES before exposing per-point times. |
| Peak / random feed vs auxiliary | **Not applicable:** native scalar peak/random feed; use sampled trace maximum when suitable. | **Implemented:** scalar `POWer:PEAK` and `POWer:RANDom` feed on a fresh acquisition. **Deferred:** AUX MINMAX / RNDMAX, without inventing field order or units. | R&S §§9.3.4, 9.8.1. First capture firmware-specific AUX scalar/array ASCII and binary layouts, validate grouping and count with known alternating extrema; only then publish structured auxiliary results. |
| Buffers, FAST, frequency stepping | **Deferred:** 2–250 external average-trigger buffer and stepped-frequency acquisition, and the distinct 2–50 immediate FAST trigger-count burst or free run. | **Implemented:** 2–8,192 hardware-buffered ordered average readings, immediate or external, matched trigger count and completion. **Deferred:** raw fast/unchopped REAL32 blocks, partial/live buffers, hardware without the full-array contract. | Keysight pp. 55–57, 187–188, 211–218, 220–222, 342–343, 388–389; R&S §§9.5.1.3, 9.8.1, 10.2–10.3. Test clear/full/error handling, no stale buffers, burst-unit/correction couplings, and output shape. No invented sample times. |
| Native result formats / units | **Implemented:** ASCII absolute W/dBm for normal scalars, raw trace independent of scalar format; local mW/uW conversion. **Deferred:** scalar REAL64 and byte-order switching, display/voltage units and relative/ratio outputs if supported by the program mode. | **Implemented:** ASCII W/dBm scalar/array, local mW/uW. **Deferred:** REAL32/64, native border, ASCII precision controls, and native dBµV (not treated as an absolute power unit). | Keysight pp. 133–138, 305–310, 349–354; R&S §§9.7–9.8. Verify framing/endianness, sentinels, unit dictionaries, and measurement assumptions before enabling each format. |
| Duty-cycle pulse power | **Implemented:** known 0.001–99.999% duty cycle; sensor-corrected average in Average-only detection. | **Implemented:** known 0.001–100% duty cycle; sensor-corrected average in continuous-average function. | Keysight pp. 194–198, 384; R&S §9.6.2. Test readback and wrong-mode rejection, then compare with an independently characterized pulsed source. Not equivalent to gate or peak. |

## Synchronize an external trigger from Python

For the NRP18AN, configure EXT1 or EXT2 and keep the trigger generator quiet
until the `arm_power()` context yields. The context waits for the sensor's
live waiting-for-trigger bit, not the `INIT` acknowledgement. Supply the edge
from a separate source or controller, then fetch the result once:

```python
meter = bench.rf_meter
meter.configure_power(frequency_hz=2.4e9, trigger_source="external_2")

with meter.arm_power(timeout_ms=3_000) as arm:
    # This is your separate controller's function, not a PyTestLab action.
    supply_test_trigger()
    reading = arm.fetch()
```

For a buffer, pass `mode="buffered_average"` to both setup and arm, and supply
enough edges for the full capture. Fetch verifies completion and idle, validates
the full buffer where applicable, and never rearms or falls back to a cached result.
The deadline includes time spent on the trigger source, but does not interrupt
your Python code. If you return too late to fetch, the scope takes the verified
abort path without a completion query. Use only the capture handle while active:
the same meter object blocks conflicting commands. This does not interlock other
clients, other aliases, or the sensor controls. Exiting without fetch aborts and checks idle. After an ambiguous
transfer, the driver attempts native Device Clear rather than sending another
SCPI command into a possible outstanding reply.

Supported only on NRP18AN EXT1/EXT2: its manual §9.4.1 and §11.2.5.3
(pp. 71, 154–155) define single initiation, abort, and the live waiting bit;
§10.3 shows externally triggered buffered operation. Keysight's U2000A
summary documents entry to wait and clearance at idle, not the same direct
wait-to-measure condition. Its existing blocking capture is unchanged.
Offline tests model delayed readiness and stale results; bench qualification
still needs one real external source for both a scalar and a full buffer.

::: pytestlab.instruments.PowerMeter.ArmedPowerCapture

::: pytestlab.instruments.PowerMeter.PowerMeter.arm_power

## Setting trigger timing

Set up the intended edge and acquisition first using `configure_power()` or
`configure_power_trace()`; then adjust timing without changing the source or
edge. A timing update requires a matching, idle sensor and verifies the
settings it changed. For example, on a U2000A with a configured external gate:

```python
timing = meter.configure_power_trigger_timing(delay_s=80e-6, holdoff_s=200e-6)
reading = meter.acquire_power(mode="gated_average")
print(timing.delay_s, reading.settings.gate_window_s)
```

| Field | U2000A | NRP18AN |
| --- | --- | --- |
| `delay_s` | −0.15 to +0.15 s; 1 µs steps | 0 to 10 s in the verified workflow |
| `holdoff_s` | 1 µs to 400 ms; 1 µs steps | 0 to 10 s |
| `hysteresis_db` | Internal RF edge only; 0 to 3 dB, 0.1 dB steps | Internal RF edge only; 0 to 10 dB |
| `dropout_s` | Unsupported | Internal RF edge only; 0 to 10 s |

The NRP18AN manual restricts programmable slope to INTernal/EXTernal
(p. 83) and gives a separate EXT2 SMB example without a slope setting
(§10.3, pp. 137–138). EXT2 reports no polarity and does not query or set slope.

An explicit delay turns automatic delay off. Other timing changes leave that
setting as is; `read_power_trigger_timing()` reports the live state without
arming. No trigger routing, pulse generator, or connector output is changed.
U2000A gate and trace windows are relative to the detected edge: readback
adds the actual delay to the gate or trace offset. It does not create
per-sample timestamps. Allow enough transport time for the selected delay
and averaging, as well as waiting for the external edge.

Keysight evidence: programming guide pp. 229–242 and 332–337. R&S evidence:
manual §§9.4.2.4–9.4.2.5 and pp. 80–81. Bench qualification remains to compare
a pulse and synchronized trigger against a scope, including actual delay,
holdoff/dropout and hysteresis, and check phase-aligned repeatability. The
R&S manual lists a signed native delay; negative pretrigger integration is
not enabled here until its behavior on NRP18AN is verified.

::: pytestlab.instruments.PowerMeter.PowerTriggerTiming

::: pytestlab.instruments.PowerMeter.PowerMeter.configure_power_trigger_timing

::: pytestlab.instruments.PowerMeter.PowerMeter.read_power_trigger_timing

## Corrections, data, and service

| Subsystem/workflow | U2000A | NRP18AN | Evidence and remaining acceptance tests |
| --- | --- | --- | --- |
| Frequency, fixed gain/loss | **Implemented:** correction frequency configuration and readback, fixed GAIN2 setting/status readback and explicit enable/disable; native negative loss; writes refused in FAST. **Deferred:** dynamic native ranges. | **Implemented:** correction frequency, fixed OFFSet setting/status readback and explicit enable/disable; native positive attenuation. **Deferred:** live capability-limit queries. | Keysight pp. 47, 200–210; R&S §§9.6.3.2, 9.6.5, 9.11.9. Offline verifies native signs; bench-check actual power against an independent reference, no double correction, and coupling of offset to trigger level. |
| Frequency tables, paths, S-parameter correction | **Implemented:** frequency-dependent correction enabled state/selected table. **Deferred:** applied/interpolated offset unit, table editing/download, user state registers, and behavior across stepped frequency. | **Implemented:** select and enable/disable an installed S-parameter set, configure/read source Γ, and report native input Γ with live reference plane and expanded magnitude uncertainty (k=2). **Deferred:** S-parameter table catalog/update and Touchstone/plain-text transfers, sensor calibration/reference-path tables, and uncertainty-file management. | Keysight pp. 36–42, 139–171, 189–199, 390–391; R&S §§9.6.3.2–9.6.3.6, 9.6.4–9.6.6, 9.9.1. In addition to offline readback and reference-plane-change tests, bench-check a characterized two-port and source mismatch. Require unit/format evidence and a reversible or nonmutating test for persistent table edits. |
| Calculation feeds, relative math, limit tests | **Implemented:** average/gated calculation feeds as supported workflow configuration. **Deferred:** expression/math, relative outputs, limits/counters and output I/O. | **Implemented:** native mean/peak/random feed. **Deferred:** auxiliary payload (above), profile-specific calculation and quality/limit configuration. | Keysight pp. 111–132, 257–261, 273–277; R&S §§9.3.4, 9.8, 11.2.5. Test dimensional semantics and prove flags/counters are not silently cleared. |
| Zero and calibration | **Implemented:** one-shot internal isolation or externally quiet zero with live vendor/model/optional serial guard, idle preflight and sticky quarantine on ambiguity. **Deferred:** auto-zero policy and full calibration/service workflows. | **Implemented:** quiet-input external zero only, live vendor/model/optional serial and static error verification; **deferred:** uploading/activating user calibration, factory calibration and footprint history. | Keysight pp. 24–25, 103–110, 361–362; R&S §§9.9, 9.11.8. No RF source changes. Any calibration replacement needs restorable reference data and identified hardware; offline tests cannot prove a zero offset. |
| Identification, status and diagnostics | **Implemented:** IDN and non-clearing question/operation conditions and guarded native self-test. **Deferred:** destructive event reads, SRQ setup, BIST details, cap query. | **Implemented:** IDN and non-clearing condition snapshots and guarded native self-test. **Deferred:** detailed per-step self-test results, SERR and support archives/info beyond documented zero/error handling. | Keysight pp. 243–282, 288–297, 355–373; R&S §§9.10–9.11, 11.2, 13.3. Distinguish diagnostic read from operation or destructive queue/event read; verify error decoding and self-test readiness. |
| System, settings, USB/LAN | **Implemented:** profile connection and common SCPI commands through supported backends. **Deferred:** explicit save/restore/preset policies, personality changes, USBTMC trigger/service controls. | **Implemented:** profile connection; USB/LAN framing depends on backend. **Deferred:** static network setup, sensor name/LED, restart/update, support bundle, legacy protocol and trigger synchronization hardware. | Keysight pp. 63–72, 139–161, 285–302, 355–374; R&S §§9.11, 11.1, 7, 8. Keep firmware/network/service destructive changes out of generic measurement workflows; test policy, identity and offline fixtures before hardware work. |
| Model/options closure | **Scoped:** U2000A 10 MHz–18 GHz. Family U2001/U2002/U2004, B/H ranges and option-specific specs are not inherited. | **Scoped:** NRP18AN 8 kHz–18 GHz, USB and LAN; no NRP18SN modes. NRP6 and non-LAN A variants are distinct identities/profiles. | Only declare another model/option after its own manual/datasheet manifest and negative compatibility tests; an ID prefix does not prove support. |

Known bench qualification remains open. No result in this matrix is based on
physical instrument access during development.

## Inspect corrections and trigger state

```python
corrections = meter.read_power_corrections()
print(corrections.fixed_offset_enabled, corrections.fixed_offset_db)
print(meter.read_power_trigger_state().waiting_for_trigger)
```

The readback includes the programmed offset and duty cycle alongside their
enabled states, the Keysight frequency table identity or R&S S-parameter set,
and the frequency used for sensor correction. It does not compute or modify
the overall correction. Trigger state reads non-clearing conditions. It
cannot interleave a blocking acquisition on the same connection; arrange
pulses on a separate source or trigger controller.

### Apply corrections and inspect the reference plane

```python
# Use the signed convention of the attached model for a 12.5 dB attenuation:
# U2000A: meter.configure_power_offset(enabled=True, offset_db=-12.5)
# NRP18AN: meter.configure_power_offset(enabled=True, offset_db=12.5)
meter.configure_power_offset(enabled=False)  # retains the programmed value

# NRP18AN only: select an already-installed calibrated two-port, not a file upload.
meter.configure_power_s_parameter(enabled=True, data_set=3)
meter.configure_power_source_reflection(enabled=True, magnitude=0.15, phase_deg=-30)
reflection = meter.read_power_input_reflection()
print(reflection.reference_plane, reflection.magnitude, reflection.expanded_magnitude_uncertainty)
```

Offset range is ±100 dB on U2000A and ±200 dB on NRP18AN. PyTestLab writes
and returns the native signed value; it does not normalize the two models.
Keysight documents negative loss in GAIN2 (programming guide p. 47), while
R&S documents positive attenuation in its additive offset (§9.6.3.2).
Keysight offset changes require Normal or Double measurement rate. In FAST,
the instrument can report a settings conflict after changing the stored value.
The workflow checks the live rate and does not change it. The NRP source
reflection setting is a supplied coefficient (Γ magnitude 0–1 and phase in
degrees), not a source measurement. The input reflection is the sensor's
calibrated Γ at the live correction frequency and identifies either the
sensor connector or the selected two-port input as the reference plane.
Its expanded uncertainty (`k=2`) applies only to the magnitude, not to phase
or to a power reading. These are firmware-reported calibration references,
not a physical verification of the attached two-port or its correction.

Updates require a matching, idle sensor. S-parameter and source-reflection
updates disable the selected correction before programming, and only enable it
after verifying the requested settings. If an update fails, inspect the live
settings before using them; there is no implicit rollback. One correction does
not turn off another. Avoid counting the same external loss in both a fixed
offset and a calibrated two-port table. No correction workflow changes the RF
source, uploads a table, or edits the calibration data.
