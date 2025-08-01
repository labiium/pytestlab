# PyTestLab Test Suite

This directory contains the comprehensive test suite for PyTestLab, organized into logical categories for maintainability and clarity.

## 📁 Directory Structure

### Core Test Categories

```
tests/
├── conftest.py                    # Shared fixtures and test configuration
├── instruments/                   # Instrument-specific tests
├── experiments/                   # Experiment and measurement tests
├── config/                       # Configuration and validation tests
├── unit/                         # Unit tests for core functionality
├── smoke/                        # Smoke tests for basic functionality
└── test_*.py                     # Integration and system-level tests
```

### Test Organization

#### **`instruments/`** - Instrument Tests
Contains tests for all instrument drivers and backends:
- `test_awg.py` - Arbitrary Waveform Generator tests
- `test_bench.py` - Bench system integration tests
- `test_dc_load.py` - DC Electronic Load tests
- `test_multimeter.py` - Digital Multimeter tests
- `test_oscilloscope.py` - Oscilloscope tests
- `test_psu.py` - Power Supply Unit tests
- `sim/` - Simulation-specific tests and profiles

#### **`experiments/`** - Experiment Framework Tests
Tests for the measurement and experiment framework:
- `test_database.py` - Experiment database tests
- `test_experiment.py` - Core experiment functionality
- `test_compliance.py` - Compliance and audit tests
- `test_result.py` - Measurement result handling

#### **`config/`** - Configuration Tests
Tests for configuration loading and validation:
- `test_config_models_hypothesis.py` - Property-based config testing

#### **`unit/`** - Unit Tests
Isolated unit tests for core components:
- `test_instrument_helpers.py` - Instrument utility functions
- `test_instrument_error_handling.py` - Error handling mechanisms

#### **`smoke/`** - Smoke Tests
Basic functionality verification:
- `test_profile_loading.py` - Profile loading smoke tests

#### **Root Level Tests** - Integration & System Tests
- `test_cli.py` - Command-line interface tests
- `test_safety.py` - Safety system tests
- `test_uncertainty.py` - Measurement uncertainty tests
- `test_logging.py` - Logging system tests
- `test_replay_backend.py` - Replay functionality tests
- `test_session_recording_backend.py` - Session recording tests
- `test_measurement_session.py` - Measurement session tests
- `test_autoinstrument_backend_override.py` - Backend override tests

## 🧪 Running Tests

### Run All Tests
```bash
pytest tests/
```

### Run Specific Test Categories
```bash
# Instrument tests only
pytest tests/instruments/

# Experiment tests only
pytest tests/experiments/

# Unit tests only
pytest tests/unit/

# Smoke tests only
pytest tests/smoke/
```

### Run Tests by Markers
```bash
# Tests that require real hardware
pytest -m requires_real_hw

# CI-friendly examples (simulation only)
pytest -m ci_example

# Skip hardware tests
pytest -m "not requires_real_hw"
```

### Run Specific Test Files
```bash
# Single test file
pytest tests/instruments/test_psu.py

# Multiple test files
pytest tests/test_safety.py tests/test_uncertainty.py
```

## 🏷️ Test Markers

The test suite uses the following pytest markers:

- **`requires_real_hw`** - Tests that need actual hardware instruments
- **`ci_example`** - Examples designed for CI environments (simulation only)

## 🔧 Test Configuration

### Fixtures
The `conftest.py` file provides shared fixtures:
- `sim_scope` - Simulated oscilloscope instance
- `temp_profile_file` - Temporary instrument profile for testing
- `temp_session_file` - Temporary session file for replay tests
- `tmp_db_file` - Temporary database file
- `simple_experiment` - Basic experiment instance

### Simulation Mode
Most tests run in simulation mode by default to avoid requiring real hardware. Tests that need real instruments are marked with `requires_real_hw`.

## 📊 Test Coverage

The test suite covers:
- ✅ All instrument drivers (PSU, DMM, Oscilloscope, AWG, DC Load)
- ✅ Bench system integration
- ✅ Measurement sessions and parameter sweeps
- ✅ Experiment database and persistence
- ✅ Safety limit enforcement
- ✅ Configuration loading and validation
- ✅ CLI functionality
- ✅ Backend systems (VISA, Simulation, Replay)
- ✅ Error handling and logging
- ✅ Measurement uncertainty propagation

## 🚀 Migration from Async

This test suite has been migrated from async to synchronous patterns:
- ❌ No `async def` test functions
- ❌ No `await` keywords
- ❌ No `@pytest.mark.asyncio` decorators
- ✅ All tests use synchronous patterns
- ✅ Direct function calls instead of awaiting
- ✅ Standard pytest fixtures and patterns

## 📝 Writing New Tests

When adding new tests:

1. **Choose the right location**:
   - Instrument-specific → `instruments/`
   - Experiment-related → `experiments/`
   - Core functionality → `unit/`
   - Integration → root level

2. **Use appropriate markers**:
   ```python
   @pytest.mark.requires_real_hw
   def test_real_hardware_function():
       pass
   ```

3. **Follow synchronous patterns**:
   ```python
   def test_sync_function():
       instrument = AutoInstrument.from_config("profile")
       instrument.connect_backend()
       result = instrument.measure_voltage()  # No await
       assert result.values > 0
   ```

4. **Use simulation by default**:
   ```python
   def test_simulated_measurement():
       instrument = AutoInstrument.from_config("profile", simulate=True)
       # Test logic here
   ```

## 🐛 Debugging Tests

### Verbose Output
```bash
pytest tests/ -v
```

### Show Print Statements
```bash
pytest tests/ -s
```

### Run Failed Tests Only
```bash
pytest tests/ --lf
```

### Debug with PDB
```bash
pytest tests/ --pdb
```

## 📈 Continuous Integration

The test suite is designed to work in CI environments:
- Uses simulation by default
- Hardware tests are marked and can be skipped
- Fast execution for quick feedback
- Comprehensive coverage for reliability

For CI, run:
```bash
pytest tests/ -m "not requires_real_hw"
```

This ensures only simulation-based tests run in CI environments where real hardware is not available.