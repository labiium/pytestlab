---
title: Instrument Drivers
description: Overview of PyTestLab instrument driver classes and the shared simulation and profile model.
---

# Instrument drivers

PyTestLab provides a consistent interface across real and simulated laboratory instruments. Start with [`AutoInstrument`](autoinstrument.md) when selecting a driver from configuration, or use a concrete driver when you need instrument-specific operations.

## Core classes

- [`AutoInstrument`](autoinstrument.md) selects and configures the appropriate driver.
- [`Instrument`](instrument.md) is the shared base for transport, health, identity, and lifecycle behavior.

## Supported instrument types

- [`Oscilloscope`](oscilloscope.md)
- [`PowerSupply`](power-supply.md)
- [`WaveformGenerator`](waveform-generator.md)
- [`Multimeter`](multimeter.md)
- [`DCActiveLoad`](dc-active-load.md)
- [`SpectrumAnalyser`](spectrum-analyzer.md)
- [`VectorNetworkAnalyser`](vector-network-analyzer.md)
- [`PowerMeter`](power-meter.md)

All drivers support simulation through configuration or `simulate=True`. See [Simulation Mode](../../user_guide/simulation.md) and [Creating Profiles](../../profiles/creating.md).
