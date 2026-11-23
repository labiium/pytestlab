---
title: Impedance analyzer coverage
---

# Impedance analyzer coverage

This inventory separates instrument capabilities from PyTestLab support. **Typed**
means a typed profile workflow covered by offline transcripts; **prepared** means
the operator first sets the instrument up; **catalog** means vendor-documented
but not yet a typed workflow. **Restricted** identifies a hardware, safety,
freshness, or protocol question that must be resolved before claiming support.

Sources: the [E4990A programming help][keysight], [IM3570 model-specific command
reference][hioki-scpi] and [IM3570 user manual][hioki-user]. The vendor-authored
E4990A Help PDF (A.01.0x, printed pages) and Hioki IM3570A983-09 communication
transport manual were cross-checked. No hardware verification is implied.

| Workflow | Keysight E4990A | Hioki IM3570 |
| --- | --- | --- |
| Identity and installed features | Identity and derived installed frequency range; `*OPT?` catalog. Options 010/020/030/050/120 (10/20/30/50/120 MHz). Service, firmware and adapter capability codes are separate. | Identity; LCR, Analyzer and Continuous modes. Optional IM9000 equivalent circuit analysis must not be inferred from the model identity. |
| Channel, trace and display | Four logical channels, up to four traces each. Typed held trace definition. Active selection, trace layout, channel coupling and display configuration catalog (`SERV:ACH`, `CALC:PAR`, `DISP`). | One logical channel; two Analyzer display slots (logical 1/2 correspond to vendor PARA1/PARA3 per §5.2.1), four LCR slots. Typed slot selection via `PARAmeter#` with DUT disconnected, Comparator/bias off. LCR response bitmap `MEAS:ITEM` is not valid in Analyzer. |
| Normal frequency sweep | Typed LIN/LOG start/stop and point count (20 Hz to installed maximum, max 1601) and buffered complex/scalar reads. Center/span, CW, dwell and explicit axis controls catalog (`SENS:FREQ`, `SENS:SWE`). | Typed Analyzer START-STOP frequency setup (4 Hz–5 MHz, 2–801 points) and buffered read. Center-span, start-step, interval and explicit point edits catalog (§§5.2–5.3). |
| Frequency segment table | Typed table inspection and guarded existing-row edit, plus prepared complex/scalar segmented readback. [`SENS:SEGM:DATA`][e4990-segm] documents 1–201 segments and optional per-row oscillator, bias, speed, point averages, sweep time and delay. 1601 points total. | Typed table inspection; guarded existing-row edit only when both tables are ≤1 MHz, V mode and Comparator/bias OFF, and idle/trigger isolation verified. §5.4 documents 1–20 segments and 801 points total, per-row spacing, range, speed, averaging, source level and delay; shared source mode and bias. Separate `SEGM:ADD/DEL/NUM`, `SEGM:STAR:STOP`, `SEGM:SUB:SOUR`. |
| Other sweep axes | `POW`, `BIAS` and `LBI` oscillator and bias sweeps; typed frequency reads reject them. Explicit axis and physical source constraints required before automation. | Analyzer V/CV/CC sweeps (linear only), interval and LCR single frequency; Continuous runs saved panels. These axes are not Hz frequency traces. |
| Baseline impedance measurements | Typed IMP, Z, phase, R/X, LS/LP, CS/CP, Q/D. Phase requires DEG and expansion off; output Ω, degrees, H, F or dimensionless ratio. | Prepared Z+PHASE and labelled scalar reads. A compatible held buffer does not prove freshness. |
| Advanced measurement parameters | Typed Y, TY (DEG only), G/B/RP. Documented complex ADM, VAC/IAC and bias-sweep-only VDC/IDC remain catalog. | Typed Y, G/B/RP. Only impedance phase is exposed; RDC is LCR-only. Comparator and optional circuit analysis numbers are separate output contracts. |
| Source, DC bias and operating limits | Typed oscillator mode/level/ALC and bias state; guarded voltage-only writes with DUT disconnected. ALC limits, current, bias/current and bias modes catalog. Electrical limits depend on source and fixture conditions. | Typed V/CV/CC readback; guarded V-only voltage programming. Low-Z, high-Z rejection, trigger-synchronous output and voltage/current monitors catalog. Internal DC bias and CV/CC high-band advisory apply. |
| Range, speed, timing and average | Typed speed steps 1–5 and point average 1–999. Sweep averaging is a distinct feature. Channel sweep time, delay and automatic/manual timing catalog. | Typed speed Fast/Medium/Slow/Slow2, 1–256 averaging, auto or 100 mΩ–100 MΩ fixed range with frequency-dependent limits. Per-segment range and timing are distinct from normal sweep controls. |
| Trigger and acquisition | Typed prepared normal fresh single sweep: BUS/ACT, point and sweep averaging off, voltage mode and no ALC/bias; timeout and verified hold/recovery. External/point trigger and segmented fresh acquisition catalog/safety-gated. | Prepared passive reads only. EXT I/O EOM has whole-sweep behavior in sequential mode (§11.2.2), but the separate SCPI `ESR0` may update after a point. `*OPC?` is not a proven fresh-buffer barrier. |
| Buffer formats, memory and status | Typed ASCII RDAT/FDAT with count and sentinel checks. FORM binary, trace memory, service and diagnostic status catalog; some queries consume error entries/events. | Typed ASCII labelled per-point with VALID/status checks; binary, bulk record framing, long format, automatic output, memory and read-to-clear event registers catalog. |
| Equivalent circuit analysis | `CALC:EPAR` models A–G, R/L/C values, compensation model and simulation catalog, distinct from native swept parameters. | Optional IM9000 `CIRC:ANAL`, equivalent circuit/simulation and KR/K31/K33/KT/K15 electromechanical analysis. Verify installed feature and model before reading. |
| Marker, search, comparator and trace math | Typed passive active-trace scalar frequency limit-line table and its programmed offsets. Marker/statistics/search, dynamic tracking, result/qualification reads and trace math remain catalog. | Typed Analyzer frequency AREA point thresholds and PEAK windows and thresholds. Cursor/search, actual area/peak result qualification, LCR comparator/BIN and Continuous judgments remain catalog. |
| Existing correction state | Typed fixture open/short/load plus independent port/user calibration and port-extension state/time. Correction state does not prove calibration validity. | Typed Analyzer open/short state; load status is not available through LCR-only `CORR:LOAD:RET?`. Typed ALL/SPOT mode, cable compensation, scaling flag and AC compensation range. An enabled flag does not ensure accuracy. |
| Retained standard observation | Typed OPEN/SHORT/LOAD complex impedance and stored axes for distinct CAL1 user and CAL2 fixture data layers. No capture or application. | Typed Analyzer OPEN/SHORT ALL or indexed SPOT inspection. OPEN is admittance; SHORT is impedance. Distinguishes disabled slots, DC (0 Hz), and the result flag; zeros may denote uncaptured compensation. No LCR load query. |
| Fixture, calibration and standards | Documented port CAL1 and fixture CAL2 open/short/load, adapter collection, electrical delay and port extension. Restrictions: verify accessory, standard, fixture connection, stimulus, completion and persistent save/clear separately. | §7 open/short ALL/SPOT; cable/lead compensation and scaling. LCR reference/load differs. Restrictions: verify fixture, standard hookup, external bias, failure flags and operation completion first. |
| Adapters and accessories | 4-terminal-pair probes/fixtures/adapters, test-port extension and 10 MHz reference are option-dependent. Fixture limits may be narrower than instrument limits. | Interchangeable leads/fixtures and external DC bias units, contact checks, length compensation and standards. The fixture rating takes precedence over base instrument rating. |
| Transport, instrument and service | IEEE common/status, TRIG/SYST/SERV, remote/local, self-test, front panel/display, MMEM save/recall/export and persistent file operations catalog. | IEEE common, GP-IB/serial/USB/LAN, EXT I/O, status registers 0–3, key lock, self-test, panel save/load/clear, memory/USB files, printer/display/beeper catalog. |

A catalog entry is not a promise of automated support. Use the [impedance API
guide](impedance-analyzer.md) for current bench workflows and safety gates.

[keysight]: https://helpfiles.keysight.com/csg/e4990a/home.htm
[e4990-segm]: https://helpfiles.keysight.com/csg/e4990a/programming/command_reference/sense/sens_segm_data.htm
[hioki-scpi]: https://www.hioki.com/e/products/lcr/application/IM3570/English/Files/03/Right03.htm
[hioki-user]: https://shop.hioki.eu/media/53/a4/9e/1736346059/IM3570A981-08_Manual_EN.pdf

## Inspect prepared limit tests

These read the configured thresholds without changing them or reporting a
fresh pass/fail result. Prepare the relevant frequency sweep and limit
function at the instrument and stop any measurements before reading.

```python
with Bench.open("bench.yaml", aliases={"impedance"}, start_experiment=False) as bench:
    analyzer = bench.impedance
    if analyzer.supports_operation("get_trace_limit_table"):
        table = analyzer.get_trace_limit_table("conductance")
        print(table.unit, table.lines, table.stimulus_offset_hz, table.response_offset)
    else:
        # IM3570 in Analyzer AREA mode, judging slot 2 of a normal sweep.
        limits = analyzer.get_area_comparator_limits(2, slot=2)
        print(limits.frequency_hz, limits.lower, limits.upper, limits.unit)
```

- **E4990A:** Read the active held scalar trace's raw OFF/upper/lower limit
  lines and programmed horizontal and vertical offsets. The driver verifies
  the requested scalar parameter, frequency domain, ASCII, normal trace
  math, and degrees without phase expansion for phase, before and after
  reading the table. Stored breakpoints
  may be outside the current sweep range. Changing the trace format can
  change displayed units without rescaling the stored values; revalidate
  the table when changing format. Raw rows and offsets are not a
  reconstruction of the effective limit when tracking is used.
- **IM3570:** In a normal frequency sweep with AREA enabled,
  `get_area_comparator_limits(point, slot=...)` reads a programmed frequency
  and the selected slot's thresholds. For PEAK mode,
  `get_peak_comparator_limits(segment=..., slot=..., peak="min")` reads
  the configured search window and thresholds with frequency bounds in Hz.
  Use `peak="max"` for local maxima. Each `None` limit is explicitly OFF;
  it does not mean zero. Logical Analyzer slot 2 uses the PARA3 display
  parameter for its units. These APIs do not run detection or read a
  pass/fail result.
