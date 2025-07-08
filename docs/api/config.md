# Configuration Models

This section details the Pydantic models used for instrument and bench configuration in PyTestLab. These models define the schema for instrument profiles, bench descriptors, and related configuration files.

---

## Bench Configuration

::: pytestlab.config.bench_config.BenchConfigExtended
    options:
      show_root_heading: true
      show_root_toc_entry: false

---

## Instrument Configuration Models

Each instrument profile YAML must specify a `device_type` that matches one of the following configuration models. These models define the required and optional fields for each instrument type.

### Base Instrument Model

::: pytestlab.config.instrument_config.InstrumentConfig

---

### Power Supply

::: pytestlab.config.power_supply_config.PowerSupplyConfig

---

### Oscilloscope

::: pytestlab.config.oscilloscope_config.OscilloscopeConfig

---

### Waveform Generator

::: pytestlab.config.waveform_generator_config.WaveformGeneratorConfig

---

### Multimeter

::: pytestlab.config.multimeter_config.MultimeterConfig

---

### DC Active Load

::: pytestlab.config.dc_active_load_config.DCActiveLoadConfig

---

### Vector Network Analyzer (VNA)

::: pytestlab.config.vna_config.VNAConfig

---

### Spectrum Analyzer

::: pytestlab.config.spectrum_analyzer_config.SpectrumAnalyzerConfig

---

### Power Meter

::: pytestlab.config.power_meter_config.PowerMeterConfig

---

### Virtual Instrument

::: pytestlab.config.virtual_instrument_config.VirtualInstrumentConfig

---

## Accuracy Specification

Many instrument models include an `accuracy` field or section. This is typically defined using the `AccuracySpec` model.

::: pytestlab.config.accuracy_spec.AccuracySpec

---

## Configuration Loader

For advanced users, PyTestLab provides a configuration loader utility for validating and loading profiles.

::: pytestlab.config.loader.ConfigLoader

---

For more information on creating and validating instrument profiles, see the [Creating Profiles Guide](../profiles/creating.md).
