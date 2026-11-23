---
title: Instrument Drivers
description: Overview of PyTestLab instrument driver classes and the shared simulation and profile model.
---

# Instrument drivers

PyTestLab provides a consistent interface across real and simulated laboratory instruments. Start with [`AutoInstrument`](autoinstrument.md) when selecting a driver from configuration, or use a concrete driver when you need instrument-specific operations.

## Core classes <span id="core-instrument-classes"></span>

- [`AutoInstrument`](autoinstrument.md) selects and configures the appropriate driver.
- [`Instrument`](instrument.md) is the shared base for transport, health, identity, and lifecycle behavior.

## Supported instrument types

- [`Oscilloscope`](oscilloscope.md){ #oscilloscope }
- [`PowerSupply`](power-supply.md){ #power-supply }
- [`WaveformGenerator`](waveform-generator.md){ #waveform-generator }
- [`Multimeter`](multimeter.md){ #multimeter }
- [`DCActiveLoad`](dc-active-load.md){ #dc-active-load }
- [`SpectrumAnalyser`](spectrum-analyzer.md){ #spectrum-analyzer }
- [`VectorNetworkAnalyser`](vector-network-analyzer.md){ #vector-network-analyzer-vna }
- [`PowerMeter`](power-meter.md){ #power-meter }
- [`ImpedanceAnalyzer`](impedance-analyzer.md)

## Working with drivers

- For examples of fluent driver APIs, see the [10-Minute Tour](../../tutorials/10_minute_tour.ipynb){ #facade-pattern }.
- Use `simulate=True` or bench configuration with a compatible profile. Not every packaged profile includes a simulation fixture. See [Simulation Mode](../../user_guide/simulation.md){ #simulation-support }.
- To add an instrument profile, see [Creating Profiles](../../profiles/creating.md){ #extending-drivers }.

## RF measurement workflows

Read back applied settings. A held read neither starts a sweep nor establishes
freshness. For an FSW26, inspect declared measurements offline with
`instrument.describe_operations(group="measurements", include_unsupported=False)`
or:

```console
ptl instrument list-operations rohdeschwarz/FSW26 --group measurements --supported-only
```

The catalog describes profile support, not installed options or current state.

| Driver | Verified setup and readback | Fresh acquisition | Held read |
| --- | --- | --- | --- |
| [Spectrum analyzer](spectrum-analyzer.md) | On N9000A and FSW26: RF input, detector, bandwidth, sweep, trigger and trace settings | Synchronized swept or zero-span traces, finite native averaging or hold, channel power and occupied bandwidth on both; one or multiple adjacent-channel pairs on N9000A | Actual coordinates, measured-bin peak and native markers |
| [RF power meter](power-meter.md) | Correction frequency, averaging, trigger timing, diagnostics and guarded zeroing; NRP18AN aperture | Absolute and duty-cycle-corrected power on both; gates and native traces on U2000A; buffered, peak and random measurements on NRP18AN | Legacy native scalar read where supported |
| [Impedance analyzer](impedance-analyzer.md) | Frequency and segment tables, drive, retained fixture standards and comparator limits | E4990A on a prepared bench, with programmed-level checks | Complex impedance and supported scalar curves on E4990A and IM3570 |
| [Vector network analyzer](vector-network-analyzer.md) | E5071C sweep settings and setup with RF off | One stepped LIN/LOG E5071C sweep on a prepared two-port bench | E5071C and C1209 indexed complex traces, analyzer capacity, segment tables and passive markers |

Software coverage does not imply hardware qualification or calibration.
