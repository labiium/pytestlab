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

The shared hierarchy is `Config` → `BaseConfig` → `DeviceConfig` →
`InstrumentConfig`. `Config` supplies JSON-compatible serialization, while
`DeviceConfig` owns the common identity, role, address, driver, and backend
fields used by concrete device and instrument profiles.

::: pytestlab.config.config.Config

::: pytestlab.config.config.BaseConfig

::: pytestlab.config.device_config.DeviceConfig

::: pytestlab.config.device_config.GenericDeviceConfig

::: pytestlab.config.device_config.DeviceRole

### Base Instrument Model

`InstrumentConfig.operation_options` is the optional profile block for
semantic operation parameters. Each parameter declares a kind (`enum`,
`range`, `open_string`, `bool`, or `unresolved`), semantic option values, and
private transport mappings used by profile authors. Those mappings are consumed
internally by the shared operation resolver and are never returned by normal
Python or CLI discovery.

::: pytestlab.config.operation_options.ProfileOperationOptions

::: pytestlab.config.operation_options.ProfileOperationParameter

::: pytestlab.config.operation_options.ProfileOperationOption

::: pytestlab.config.instrument_config.InstrumentConfig

::: pytestlab.config.switch_matrix_config.SwitchMatrixConfig

::: pytestlab.uncertainty.specs.BandAccuracySpec

::: pytestlab.uncertainty.specs.CompositeBudgetSpec

::: pytestlab.uncertainty.specs.ExpressionAccuracySpec

::: pytestlab.uncertainty.specs.MonteCarloAccuracySpec

::: pytestlab.uncertainty.specs.RepeatabilityAccuracySpec

::: pytestlab.uncertainty.specs.UncertaintyContext

::: pytestlab.uncertainty.units.UnitCompatibilityError

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

### Impedance Analyzer

::: pytestlab.config.impedance_analyzer_config.ImpedanceAnalyzerConfig

---

### Virtual Instrument

::: pytestlab.config.virtual_instrument_config.VirtualInstrumentConfig

---

## Accuracy Specification

Many instrument models include an `accuracy` field or section. This is typically defined using the `AccuracySpec` model.

::: pytestlab.uncertainty.specs.AccuracySpec

---

## Configuration Loader

For advanced users, PyTestLab provides functions for resolving, validating, and loading profiles.

::: pytestlab.config.loader.resolve_profile_key_to_path

::: pytestlab.config.loader.load_device_profile

For class-oriented integrations, `ConfigLoader` delegates to the same canonical
functions rather than maintaining a separate loading implementation.

::: pytestlab.config.loader.ConfigLoader

---

For more information on creating and validating instrument profiles, see the [Creating Profiles Guide](../profiles/creating.md).
