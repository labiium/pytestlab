# Instrument Drivers

This section documents the main instrument driver classes provided by PyTestLab. All drivers support both real and simulated backends, and expose a modern, async-first API.

---

## Core Instrument Classes

::: pytestlab.instruments.AutoInstrument
    options:
      show_root_heading: true
      show_category_heading: true

::: pytestlab.instruments.Instrument

---

## Supported Instrument Types

### Oscilloscope

::: pytestlab.instruments.Oscilloscope

### Power Supply

::: pytestlab.instruments.PowerSupply

### Waveform Generator

::: pytestlab.instruments.WaveformGenerator

### Multimeter

::: pytestlab.instruments.Multimeter

### DC Active Load

::: pytestlab.instruments.DCActiveLoad

### Spectrum Analyzer

::: pytestlab.instruments.SpectrumAnalyser

### Vector Network Analyzer (VNA)

::: pytestlab.instruments.VectorNetworkAnalyser

### Power Meter

::: pytestlab.instruments.PowerMeter

---

## Facade Pattern

All instrument drivers expose "facade" objects for common operations, enabling a fluent, chainable API. For example, you can configure and enable a channel with:

```python
await scope.channel(1).setup(scale=0.5, offset=0).enable()
```

See the [10-Minute Tour](../../tutorials/10_minute_tour.ipynb) for practical examples.

---

## Simulation Support

All drivers support simulation via the `simulate=True` flag or by using a simulated backend. See the [Simulation Guide](../user_guide/simulation.md) for details.

---

## Extending Drivers

To add support for a new instrument, create a profile YAML file and use `AutoInstrument.from_config()` or subclass `Instrument`. See [Creating Profiles](../profiles/creating.md) for guidance.
