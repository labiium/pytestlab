---
title: Spectrum analyzer capabilities
description: Compare manual-backed spectrum analyzer workflows by instrument model.
---

# Spectrum analyzer capabilities

For configuration and capture examples, see the [spectrum analyzer API](spectrum-analyzer.md).

## Manual coverage by subsystem

The matrix is a map of the documented workflows, not a list of every SCPI
spelling. **Available** means a typed operation exercised against a scripted
transport. The two manuals cover more hardware, firmware, and licensed
applications than these two bundled profiles. Availability of a documented
feature is not proof that a particular instrument has its option installed.

| Subsystem | N9000A evidence | FSW26 evidence | Available now and what remains |
| --- | --- | --- | --- |
| Connection, status, synchronization and identity | chs. 2–3, 6; pp. 843–844 | chs. 12–13; pp. 904–908, 921–923 | Profile/bench discovery and bounded single completion. Still to expose typed event/status registers, SRQ, alignment, diagnostics, and recovery workflows. Use timeout, no-reply and stale-queue tests before exposing asynchronous controls. |
| Application, channels, and sequencing | chs. 5, 8–18; p. 371 | pp. 909–923 | Prepare and verify ordinary passive sweep readiness without reset; verify default Spectrum / SA app and named supported measurements. No arbitrary app switching, renamed channel support, or sequencer. Each channel/app should declare its firmware/options and result schema; replay the selected-channel readback before acquiring. |
| RF input and amplitude | ch. 4; pp. 597–632 | pp. 363–473, 1224–1233 | Reference level, mechanical/RF attenuation, auto attenuation and option-checked internal preamp. Still to expose input coupling, impedance, path, electronic attenuation, correction tables, amplitude scaling and installed external front ends. External mixers, generators, probes and sensors need their own capability and no-output guards. |
| Frequency, bandwidth, and sweep engine | pp. 638–639, 891, 927–933, 981–982; ch. 18 | pp. 474–510, 1214–1224 | Center/span, RBW, VBW, points, sweep time, zero span and continuous/single state. Still to expose start/stop, filter shape/coupling, FFT details, optimized/preset settings, segmented/list/span plans and sweep duration. Replay domain and coupling changes, not just setters. |
| Trigger, gate, and timing | ch. 7, pp. 528–592 | pp. 511–533, 1233–1248 | Typed trigger source, external threshold and edge, and timed captures. Still to expose RF/video thresholds, holdoff/delay, position, time/gating, output ports and signal tracking. Connector direction and source-specific time/voltage/power units must be guarded separately. |
| Trace statistics, detector and transfer | pp. 594–596, 752–755, 986–1055 | pp. 613–662, 1257–1278 | Typed detector/processing, instrument X/Y, one fresh sweep for one or multiple Clear/Write traces, native average/min/max hold for one trace, held reads and software peak. Still to expose averaging domain, gating, trace math/normalize/copy, binary formats, spectrogram history and trace export/import. Require exact shape, endianness, units and fresh-vs-held markers for each format. |
| Markers, display analysis, limits | pp. 671–700, 806–808, 1034–1055 | pp. 537–613, 1285–1338 | Frequency marker/peak/next, readback and delta derived from two ordinary markers. Still to expose marker table/peak list, intrinsic delta, noise and band markers, count, N-dB crossing, reference displays and limit lines. Require domain/unit checks and unavailable-result cases. |
| Integrated RF power and bandwidth | chs. 9–11 | pp. 923–994 | Channel power and occupied bandwidth on both models; single-carrier ACP with one or more symmetric pairs on Keysight only. Still to expose power spectral density, programmable multi-pair geometry, adjacent limits, alternate result views, standards-based/cellular and multicarrier layouts. FSW ACP requires verified upper/lower geometry or explicit standard selection qualified on hardware before it can be exposed. |
| Additional scalar and spectrum measurements | chs. 12–18 | ch. 6; pp. 995–1104 | Not typed yet: Keysight CCDF, transmit power, spurious, SEM, TOI, harmonics, list sweep; FSW C/N and C/N0, NPR, spectrum emission mask, spurious, harmonics, TOI, AM and EMI. Split into app-specific results and validate thresholds, limits, enabled regions, acquisition state and option requirements. |
| Capture, files and instrument management | chs. 4–6; pp. 845–885 | chs. 8–11 | No typed screenshot, save/restore/delete, data files, local panel/displays, calibration logs or report actions. Use explicit file targets, supported formats and opt-in for state changes, with fixture tests for overwrite, partial transfer and failed restore. |
| Licensed or platform-specific applications | ch. 5 and mode notes throughout | ch. 6, installed-option catalogs and individual application manuals | Base profile does not claim VSA/IQ, phase-noise, real-time, standards demodulation, wideband or instrument-sharing options. Each needs its own exact firmware/model/option evidence, representative responses and a dedicated unsupported path. |

The manuals are [Keysight X-Series Spectrum Analyzer Mode](spectrum-analyzer.md#programming-references)
and [Rohde & Schwarz FSW v57](spectrum-analyzer.md#programming-references). For a new workflow,
first pick the documented model/application and option scope, map its units
and state explicitly, and add a replay for both the successful result and a
condition where readback would otherwise be misleading. Use
`describe_operation()` to discover the current profile boundary rather than
assuming that an entire manual chapter is implemented.

## Power and bandwidth results

::: pytestlab.instruments.SpectrumAnalyser.SpectrumChannelPower
    options:
      filters:
        - "!^_"
        - "!^to_measurement_result$"

::: pytestlab.instruments.SpectrumAnalyser.SpectrumOccupiedBandwidth
    options:
      filters:
        - "!^_"
        - "!^to_measurement_result$"

::: pytestlab.instruments.SpectrumAnalyser.SpectrumAdjacentChannelPower
    options:
      filters:
        - "!^_"
        - "!^to_measurement_result$"

::: pytestlab.instruments.SpectrumAnalyser.SpectrumAdjacentChannelPair
    options:
      filters:
        - "!^_"
        - "!^to_measurement_result$"

::: pytestlab.instruments.SpectrumAnalyser.SpectrumAdjacentChannelPowerSeries
    options:
      filters:
        - "!^_"
        - "!^to_measurement_result$"
