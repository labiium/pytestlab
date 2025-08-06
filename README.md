<!--
  PyTestLab – Scientific test & measurement toolbox
  =================================================
  Comprehensive README generated 2025-06-10
-->

<p align="center">
  <img src="pytestlab_logo.png"
       alt="PyTestLab logo" width="320"/>
</p>

<h1 align="center">PyTestLab</h1>

<p align="center">
  Modern Python toolbox for laboratory<br/>
  test-and-measurement automation, data management&nbsp;and analysis.
</p>

<p align="center">
  <a href="https://pypi.org/project/pytestlab"><img alt="PyPI"
     src="https://img.shields.io/pypi/v/pytestlab?logo=pypi&label=PyPI&color=blue"/></a>
  <a href="https://pytestlab.org"><img
     alt="Docs"
     src="https://img.shields.io/badge/docs-latest-blue"/></a>
  <a href="https://opensource.org/licenses/Apache-2.0"><img alt="Apache License"
        src="https://img.shields.io/badge/license-Apache%202.0-blue"/></a>
</p>

---

## ✨ Key Features

* **Unified driver layer** – consistent high-level API across oscilloscopes, PSUs, DMMs, VNAs, AWGs, spectrum & power meters, DC loads, …
  (see `pytestlab.instruments.*`).
* **Chainable facade API** – fluent method chaining for readable instrument control: `psu.channel(1).set(5.0, 0.1).on()`.
* **Plug-and-play profiles** – YAML descriptors validated by Pydantic & JSON-schema.
  Browse ready-made Keysight profiles in `pytestlab/profiles/keysight`.
* **Simulation mode** – develop anywhere using the built-in `SimBackend` (no hardware required, deterministic outputs for CI).
* **Record & Replay** – record real instrument sessions and replay them exactly for reproducible measurements, offline analysis, and regression testing with strict sequence validation.
* **Bench descriptors** – group multiple instruments in one `bench.yaml`, define safety limits, automation hooks, traceability and measurement plans.
* **High-level measurement builder** – notebook-friendly `MeasurementSession` for parameter sweeps that stores data as Polars DataFrames and exports straight to the experiment database.
* **Rich database** – compressed storage of experiments & measurements with full-text search (`MeasurementDatabase`).
* **Powerful CLI** – `pytestlab …` commands to list/validate profiles, query instruments, convert benches to simulation, replay sessions, etc.
* **Extensible back-ends** – VISA, Lamb server, pure simulation; drop-in new transports via the `InstrumentIO` protocol.
* **Docs & examples** – Jupyter tutorials, MkDocs site, and 40+ ready-to-run scripts in `examples/`.

---

## 🚀 Quick Start

### 1. Install

```bash
pip install pytestlab           # core
pip install pytestlab[full]     # + plotting, uncertainties, etc.
```

> Need VISA? Install NI-VISA or Keysight IO Libraries, then `pip install pyvisa`.

### 2. Hello Oscilloscope (simulated)

```python
from pytestlab.instruments import AutoInstrument

def main():
    scope = AutoInstrument.from_config("keysight/DSOX1204G", simulate=True)
    scope.connect_backend()

    # simple façade usage with method chaining
    scope.channel(1).setup(scale=0.5).enable()
    scope.trigger.setup_edge(source="CH1", level=0.2)

    trace = scope.read_channels(1)      # Polars DataFrame
    print(trace.head())

    scope.close()

main()
```

### 3. Build a Bench

```yaml
# bench.yaml  (excerpt)
bench_name: "Power-Amp Characterisation"
simulate: false           # set to true for dry-runs / CI
instruments:
  psu:
    profile: "keysight/EDU36311A"
    address: "TCPIP0::172.22.1.5::inst0::INSTR"
    safety_limits:
      channels:
        1: {voltage: {max: 6.0}, current: {max: 3}}
  dmm:
    profile: "keysight/34470A"
    address: "USB0::0x0957::0x1B07::MY56430012::INSTR"
```

```python
import pytestlab

def run():
    with pytestlab.Bench.open("bench.yaml") as bench:
        v = bench.dmm.measure_voltage_dc()
        print("Measured:", v.values, v.units)

run()
```

### 4. Record & Replay Sessions

Record real instrument interactions and replay them exactly:

```bash
# Record a measurement session
pytestlab replay record my_measurement.py --bench bench.yaml --output session.yaml

# Replay the recorded session
pytestlab replay run my_measurement.py --session session.yaml
```

Perfect for reproducible measurements, offline analysis, and catching script changes!

---

## 🔄 Record & Replay Mode

PyTestLab's **Record & Replay** system enables you to capture real instrument interactions and replay them with exact sequence validation. This powerful feature supports reproducible measurements, offline development, and regression testing.

### Core Benefits

- **🎯 Reproducible Measurements** – Exact same SCPI command sequences every time
- **🛡️ Measurement Integrity** – Scripts cannot deviate from validated sequences
- **🔬 Offline Analysis** – Run complex measurements without real hardware
- **🧪 Regression Testing** – Catch unintended script modifications immediately

### How It Works

1. **Recording Phase**: The `SessionRecordingBackend` wraps your real instrument backends and logs all commands, responses, and timestamps to a YAML session file.

2. **Replay Phase**: The `ReplayBackend` loads the session and validates that your script executes the exact same command sequence. Any deviation triggers a `ReplayMismatchError`.

### Usage Examples

#### Basic Recording & Replay
```bash
# Record a measurement with real instruments
pytestlab replay record voltage_sweep.py --bench lab_bench.yaml --output sweep_session.yaml

# Replay the exact sequence (simulated)
pytestlab replay run voltage_sweep.py --session sweep_session.yaml
```

#### Programmatic Usage
```python
from pytestlab.instruments import AutoInstrument
from pytestlab.instruments.backends import ReplayBackend

def main():
    # Load a recorded session
    replay_backend = ReplayBackend("recorded_session.yaml")

    # Create instrument with replay backend
    psu = AutoInstrument.from_config(
        "keysight/EDU36311A",
        backend_override=replay_backend
    )

    psu.connect_backend()

    # This will replay the exact recorded sequence
    psu.set_voltage(1, 5.0)
    voltage = psu.read_voltage(1)

    psu.close()

main()
```

#### Session File Format
```yaml
psu:
  profile: keysight/EDU36311A
  log:
  - type: query
    command: '*IDN?'
    response: 'Keysight Technologies,EDU36311A,CN61130056,K-01.08.03-01.00-01.08-02.00'
    timestamp: 0.029241038020700216
  - type: write
    command: 'VOLT 5.0, (@1)'
    timestamp: 0.8096857140189968
  - type: query
    command: 'MEAS:VOLT? (@1)'
    response: '+4.99918100E+00'
    timestamp: 1.614894539990928
```

### Error Detection

If your script deviates from the recorded sequence:

```python
# During recording: set_voltage(1, 5.0)
# During replay: set_voltage(1, 3.0)  # ← Different value!

# Raises: ReplayMismatchError: Expected 'VOLT 5.0, (@1)' but got 'VOLT 3.0, (@1)'
```

### Advanced Features

- **Multi-instrument sessions** – Record PSU, oscilloscope, DMM interactions simultaneously
- **Timestamp preservation** – Exact timing information for analysis
- **Automatic error checking** – Captures instrument `:SYSTem:ERRor?` queries
- **CLI integration** – Full command-line workflow support
- **Backend flexibility** – Works with VISA, LAMB, and custom backends

See `examples/replay_mode/` for complete working examples and tutorials.

---

## 🔧 Chainable Facade API

PyTestLab features a fluent, chainable API that makes instrument control code clean and readable:

### Power Supply Example
```python
from pytestlab.instruments import AutoInstrument

psu = AutoInstrument.from_config("keysight/E36312A")

# Method chaining for clean configuration
psu.channel(1).set(voltage=5.0, current_limit=0.1).slew(duration_s=1.0).on()
psu.channel(2).set(voltage=3.3, current_limit=0.05).on()

# Measurements
voltage = psu.channel(1).measure_voltage()
current = psu.channel(1).measure_current()

# Clean shutdown
psu.channel(1).off()
psu.channel(2).off()
psu.close()
```

### Oscilloscope Example
```python
scope = AutoInstrument.from_config("keysight/DSOX1204G", simulate=True)
scope.connect_backend()

# Configure multiple channels with chaining
scope.channel(1).setup(scale=0.5, offset=0, coupling="DC").enable()
scope.channel(2).setup(scale=1.0, coupling="AC").enable()

# Setup trigger and acquisition
scope.trigger.setup_edge(source="CH1", level=0.2, slope="POSITIVE")
scope.acquisition.set_acquisition_type("NORMAL").set_acquisition_mode("REAL_TIME")

# Capture data
scope.trigger.single()
traces = scope.read_channels([1, 2])

scope.close()
```

### Benefits
- **Direct function calls** – No complex concurrency patterns needed
- **Method chaining** – `instrument.channel(1).set(5.0).on()`
- **Readable sequences** – Complex setups in clean, linear code
- **Error prevention** – Method chaining encourages proper instrument setup

---

## 📚 Documentation

| Section | Link |
|---------|------|
| Installation | `docs/installation.md` |
| 10-minute tour (Jupyter) | `docs/tutorials/10_minute_tour.ipynb` |
| User Guide | `docs/user_guide/*` |
| API Guide | `docs/user_guide/api_guide.md` |
| Bench descriptors | `docs/user_guide/bench_descriptors.md` |
| Chainable Facades | `docs/user_guide/chainable_facades.md` |
| API reference | `docs/api/*` |
| Instrument profile gallery | `docs/profiles/gallery.md` |
| Tutorials | |
| Compliance and Audit | `docs/tutorials/compliance.ipynb` |
| Custom Validations | `docs/tutorials/custom_validations.ipynb` |
| Profile Creation | `docs/tutorials/profile_creation.ipynb` |
| Migration Guide | `docs/tutorials/migration_guide.ipynb` |

HTML docs hosted at <https://pytestlab.readthedocs.io> (builds from `docs/`).

---

## 📊 Measurement Sessions

PyTestLab's `MeasurementSession` provides a powerful framework for parameter sweeps and data acquisition:

### Basic Parameter Sweep
```python
from pytestlab.measurements import MeasurementSession
import numpy as np

with MeasurementSession("Voltage Response Test") as session:
    # Define sweep parameters
    session.parameter("voltage", np.linspace(0, 5, 10), unit="V")
    session.parameter("delay", [0.1, 0.5], unit="s")
    
    # Setup instruments
    psu = session.instrument("psu", "keysight/EDU36311A", simulate=True)
    dmm = session.instrument("dmm", "keysight/34470A", simulate=True)
    
    # Define measurement function
    @session.acquire
    def measure_response(voltage, delay, psu, dmm):
        psu.channel(1).set_voltage(voltage).on()
        time.sleep(delay)
        
        result = dmm.measure_voltage_dc()
        psu.channel(1).off()
        
        return {"measured_voltage": result.values}
    
    # Execute sweep
    experiment = session.run(show_progress=True)
    print(f"Collected {len(experiment.data)} measurements")
```

### Bench Integration
```python
from pytestlab import Bench
from pytestlab.measurements import MeasurementSession

# Use existing bench configuration with measurement session
with Bench.open("lab_bench.yaml") as bench:
    with MeasurementSession(bench=bench) as session:
        # Session inherits instruments and experiment context from bench
        session.parameter("frequency", np.logspace(3, 6, 50), unit="Hz")
        
        @session.acquire
        def frequency_response(frequency, psu, scope, fgen):
            fgen.channel(1).setup_sine(frequency=frequency, amplitude=1.0)
            scope.trigger.single()
            return {"amplitude": scope.measure_amplitude(1)}
        
        experiment = session.run()
        # Data automatically saved to bench database
```

---

## ⚡ Parallel Tasks

Execute background operations simultaneously with data acquisition using `@session.task`:

### PSU Ramping with Continuous Monitoring
```python
with MeasurementSession("Power Ramp Analysis") as session:
    psu = session.instrument("psu", "keysight/E36311A", simulate=True)
    dmm = session.instrument("dmm", "keysight/34470A", simulate=True)
    
    # Background task: Continuously ramp voltage
    @session.task
    def voltage_ramp(psu, stop_event):
        while not stop_event.is_set():
            # Ramp up 1V to 5V over 4 seconds
            for v in np.linspace(1.0, 5.0, 20):
                if stop_event.is_set(): break
                psu.channel(1).set_voltage(v)
                time.sleep(0.2)
            
            # Ramp down 5V to 1V over 4 seconds  
            for v in np.linspace(5.0, 1.0, 20):
                if stop_event.is_set(): break
                psu.channel(1).set_voltage(v)
                time.sleep(0.2)
    
    # Acquisition: Monitor voltage every 100ms
    @session.acquire
    def monitor_voltage(dmm):
        voltage = dmm.measure_voltage_dc()
        return {"measured_voltage": voltage.values}
    
    # Run for 30 seconds with 100ms acquisition interval
    experiment = session.run(duration=30.0, interval=0.1)
    print(f"Captured {len(experiment.data)} voltage points during ramp")
```

### Multiple Parallel Tasks
```python
with MeasurementSession("Complex Power Analysis") as session:
    psu = session.instrument("psu", "keysight/E36311A", simulate=True)
    load = session.instrument("load", "keysight/EL34143A", simulate=True)
    scope = session.instrument("scope", "keysight/DSOX1204G", simulate=True)
    
    # Task 1: Voltage stepping
    @session.task
    def voltage_steps(psu, stop_event):
        voltages = [3.3, 5.0, 12.0, 5.0, 3.3]
        while not stop_event.is_set():
            for v in voltages:
                if stop_event.is_set(): break
                psu.channel(1).set_voltage(v)
                time.sleep(2.0)
    
    # Task 2: Load pulsing
    @session.task  
    def load_pulsing(load, stop_event):
        load.set_mode("CC")
        while not stop_event.is_set():
            load.set_current(1.0).enable_input(True)
            time.sleep(1.0)
            if stop_event.is_set(): break
            load.set_current(0.1)
            time.sleep(1.0)
    
    # Task 3: Scope triggering
    @session.task
    def scope_triggering(scope, stop_event):
        scope.channel(1).setup(scale=1.0).enable()
        scope.trigger.setup_edge(source="CH1", level=2.5)
        while not stop_event.is_set():
            scope.trigger.single()
            time.sleep(0.5)
    
    # Acquisition: Monitor all parameters
    @session.acquire
    def power_monitoring(psu, scope):
        voltage = psu.channel(1).get_voltage()
        current = psu.channel(1).get_current()
        power = voltage * current
        
        try:
            scope_data = scope.read_channels(1)
            scope_samples = len(scope_data)
        except:
            scope_samples = 0
            
        return {
            "supply_voltage": voltage,
            "supply_current": current, 
            "power_consumption": power,
            "scope_samples": scope_samples
        }
    
    # Run all tasks in parallel for 20 seconds
    experiment = session.run(duration=20.0, interval=0.3)
```

---

## 💾 Database & Persistence

PyTestLab includes a powerful measurement database with full-text search and automatic data management:

### Basic Database Usage
```python
from pytestlab.experiments import MeasurementDatabase

# Create/open database
with MeasurementDatabase("lab_measurements") as db:
    # Store experiment
    experiment_id = db.store_experiment(None, experiment)  # Auto-generated ID
    print(f"Stored experiment: {experiment_id}")
    
    # List all experiments
    experiments = db.list_experiments()
    print(f"Database contains {len(experiments)} experiments")
    
    # Search experiments by description
    results = db.search_experiments("voltage sweep")
    for result in results:
        print(f"Found: {result['title']} - {result['description']}")
    
    # Retrieve specific experiment
    exp = db.retrieve_experiment(experiment_id)
    print(f"Retrieved data: {len(exp.data)} measurements")
```

### Bench-Database Integration
```python
# bench.yaml with database configuration
bench_config = """
bench_name: "Automated Test Station"
experiment:
  title: "Device Characterization"
  database_path: "station_measurements.db"
  operator: "Lab Station A"
  
instruments:
  psu:
    profile: "keysight/E36311A"
    address: "TCPIP0::192.168.1.100::INSTR"
"""

with Bench.open("bench.yaml") as bench:
    # Database automatically initialized from bench config
    print(f"Database: {bench.db.db_path}")
    
    with MeasurementSession(bench=bench) as session:
        # ... perform measurements ...
        experiment = session.run()
        # Experiment automatically saved to bench database
        
    # Query database  
    recent_experiments = bench.db.list_experiments()
    print(f"Recent experiments: {len(recent_experiments)}")
```

### Advanced Database Features
```python
with MeasurementDatabase("advanced_lab") as db:
    # Full-text search across descriptions and notes
    power_tests = db.search_experiments("power consumption efficiency")
    thermal_tests = db.search_experiments("temperature cycling")
    
    # Database statistics
    stats = db.get_stats()
    print(f"Total experiments: {stats['experiments']}")
    print(f"Total measurements: {stats['measurements']}")
    
    # Cross-experiment analysis
    all_experiments = [db.retrieve_experiment(eid) for eid in db.list_experiments()]
    
    # Combine data from multiple experiments
    combined_data = pl.concat([exp.data for exp in all_experiments])
    print(f"Combined dataset: {len(combined_data)} total measurements")
```

---

## 🔒 Compliance & Audit

PyTestLab provides built-in compliance features for regulated environments:

### Automatic Measurement Signing
```python
# Compliance features are automatically enabled
from pytestlab.instruments import AutoInstrument

dmm = AutoInstrument.from_config("keysight/34470A")
dmm.connect_backend()

# Every measurement is automatically signed
result = dmm.measure_voltage_dc()

# Access compliance envelope
print("Measurement signature:", result.envelope['signature'])
print("Measurement hash:", result.envelope['sha'])
print("Timestamp:", result.envelope['timestamp'])

# Provenance information (PROV-O compatible)
print("Provenance:", result.prov)

# Save measurement with compliance envelope
result.save("voltage_measurement.h5")
# Creates: voltage_measurement.h5 (data) + voltage_measurement.h5.env.json (envelope)
```

### Audit Trail
```python
from pytestlab.compliance import AuditTrail

# Audit trail automatically tracks all measurement operations
# Review audit history
with open(f"{Path.home()}/.pytestlab/audit.sqlite", 'r') as audit_db:
    # Audit entries include:
    # - Actor (who performed the action)
    # - Action (what was done)
    # - Timestamp (when it occurred)  
    # - Envelope (cryptographic proof)
    print("All measurement operations are automatically audited")
```

### Database Compliance Integration  
```python
with MeasurementDatabase("compliant_lab") as db:
    # Store measurement with automatic envelope persistence
    measurement_id = db.store_measurement(None, signed_result)
    
    # Retrieve measurement with envelope verification
    retrieved = db.retrieve_measurement(measurement_id)
    
    # Envelopes are stored in separate table for integrity
    # Query: SELECT * FROM measurement_envelopes WHERE codename = ?
    print("Compliance envelopes automatically persisted")
```

### Instrument State Signatures
```python
from pytestlab.compliance import Signature

# Create instrument state snapshot
psu = AutoInstrument.from_config("keysight/E36311A")
psu.connect_backend()

# Configure instrument
psu.channel(1).set_voltage(5.0).set_current_limit(1.0)

# Create cryptographic signature of current state
signature = Signature.create(psu)
print("Instrument configuration hash:", signature.hash)

# Verify instrument state hasn't changed
later_signature = Signature.create(psu)
if signature.verify(later_signature):
    print("✅ Instrument configuration unchanged")
else:
    print("⚠️ Instrument configuration has been modified")
```

---

## 🧑‍💻 Contributing

Pull requests are welcome! See [`CONTRIBUTING.md`](CONTRIBUTING.md) and the [Code of Conduct](CODE_OF_CONDUCT.md).
Run the test-suite (`pytest`), type-check (`mypy`), lint/format (`ruff`), and keep commits conventional (`cz c`).

---

## 🗜️ License

Apache-2.0 © 2023 Emmanuel Olowe & contributors.

Commercial support / custom drivers? Open an issue or contact <support@pytestlab.org>.

---

> Built with ❤️  &nbsp;by scientists, for scientists.
