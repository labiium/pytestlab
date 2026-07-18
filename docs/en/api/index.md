---
title: API Overview
description: Map of PyTestLab's public Python API, from instrument drivers to measurements and configuration.
---

# API overview

Use this reference when you know the PyTestLab object or subsystem you need. If you are building your first bench, start with the [Getting Started guide](../user_guide/getting_started.md).

| Area | Use it for |
| --- | --- |
| [Instrument drivers](instruments/index.md) | Connecting to oscilloscopes, power supplies, meters, loads, analyzers, and custom profiles |
| [Measurements](measurements.md) | Building and running repeatable measurement sessions |
| [Experiments and database](experiments.md) | Structuring, persisting, plotting, and retrieving results |
| [Backends](backends.md) | Selecting real, simulated, replay, or circuit-simulation communication |
| [Configuration](config.md) | Validated instrument, bench, and runtime configuration models |
| [Errors](errors.md) | Catching and diagnosing PyTestLab exceptions |
| [Common utilities](common.md) | Shared enums, health information, and helper types |

## Typical paths

- Create an instrument from a profile: [`AutoInstrument`](instruments/autoinstrument.md)
- Work directly with an oscilloscope: [`Oscilloscope`](instruments/oscilloscope.md)
- Define a parameter sweep: [Measurements](measurements.md)
- Diagnose a connection failure: [Troubleshooting](../user_guide/troubleshooting.md)
