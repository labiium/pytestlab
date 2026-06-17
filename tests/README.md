# PyTestLab Test Suite

This directory hosts every automated check used to keep PyTestLab stable, from
unit-level utilities to end-to-end session replay tests. The same commands run
locally and in CI (`.github/workflows/test.yml`), so reproducing failures is
easy once you know how things are wired up.

## Layout & Focus Areas

```
tests/
├── conftest.py                  # Shared fixtures and AutoInstrument patches
├── instruments/                 # Instrument drivers, benches and backend sims
│   ├── sim/                     # Simulation profiles (e.g. DSOX1204G_sim.yaml)
│   └── acquisition_test_results/# Logged traces used by oscilloscope tests
├── experiments/                 # Measurement session + database scenarios
├── plotting/                    # Plotly/Matplotlib result rendering guards
├── smoke/                       # Cheap profile-loading regression tests
├── unit/                        # Pure-python helpers, schema and SCPI utilities
├── README.md                    # This guide
└── test_*.py                    # CLI, safety, replay and other integration tests
```

Key root-level tests:
- `test_cli.py` / `test_cli_replay.py` – exercise the `pytestlab` CLI surface.
- `test_compliance.py`, `test_logging.py`, `test_warnings.py` – audit, logging
  and warning flows.
- `test_measurement_database.py`, `test_measurement_session.py` – database and
  session builders.
- `test_recording_backend_psu.py`, `test_replay_backend.py`,
  `test_session_recording_backend.py`, `test_simulation_e2e.py` – record/replay
  and pure simulation paths.

## How Tests Work

### Simulation-First Fixtures

`tests/conftest.py` keeps the suite hardware-free by default:
- An `autouse` fixture patches `AutoInstrument.__init__` so stray imports do not
  talk to VISA or Lamb servers.
- `sim_scope` loads `tests/instruments/sim/DSOX1204G_sim.yaml` with the
  `SimBackend` once per module, enabling deterministic oscilloscope traces.
- `temp_profile_file`, `temp_session_file`, and `tmp_db_file` provide disposable
  YAML/SQLite artifacts for profile validation, replay, and database tests.
- `simple_experiment` builds a pre-populated `Experiment` for result tests.

For features that need realistic SCPI logs, we ship canned recordings such as
`tests/experiments/recorded_psu_sim.yaml` and fixtures under
`tests/instruments/acquisition_test_results/`.

### Hardware-Gated Tests

Instrument acceptance tests under `tests/instruments/` are decorated with the
`requires_real_hw` marker. They show the expected SCPI sequences and limits, but
are skipped unless you opt in (see below) or wire physical gear during manual
runs.

## Running the Suite

1. Install PyTestLab with the development extras (same as CI):
   ```bash
   pip install -e ".[dev]"
   ```
2. Run everything with coverage (mirrors the workflow job):
   ```bash
   pytest tests/ --cov=pytestlab --cov-report=xml
   ```
   The run emits `coverage.xml`, which the GitHub Action uploads to Codecov for
   the coverage badge in the root README.

### Useful Targets

```bash
# Fast checks – skip real hardware paths
pytest tests/ -m "not requires_real_hw"

# Only hardware validation (when instruments are wired up)
pytest tests/ -m requires_real_hw

# Uncertainty feature gate: focused tests plus per-file coverage targets
coverage erase
coverage run -m pytest \
  tests/test_uncertainty.py \
  tests/test_uncertainty_hardening.py \
  tests/test_uncertainty_profile_fixtures.py \
  tests/unit/test_multimeter_uncertainty.py
coverage report --include='pytestlab/uncertainty/*.py' --fail-under=85
coverage report --include='pytestlab/instruments/uncertainty_adapters.py' --fail-under=90
coverage report --include='pytestlab/experiments/uncertainty_serialization.py' --fail-under=90

# Specific areas
pytest tests/instruments/                 # all instrument suites
pytest tests/experiments/test_database.py # single file
pytest tests/unit -k schema               # subset by keyword
```

Pytest options such as `-vv`, `-s`, `--lf`, or `--pdb` all work as usual.

## Markers & Pytest Config

Defined in `pytest.ini`:
- `requires_real_hw` – opt-in tests that expect actual instruments/benches.
- `ci_example` – placeholder for doctest-like examples that must stay CI-safe
  (the marker keeps pytest from warning when it appears in future tests).

Apply them with `pytest -m requires_real_hw` or `pytest -m "not ci_example"`.

## Continuous Integration

`.github/workflows/test.yml` runs `pytest tests/ --cov=pytestlab --cov-report=xml`
on Ubuntu for Python 3.11 - 3.14. If you match the commands above you replicate
the exact matrix locally. Coverage uploads use `codecov/codecov-action@v4` and
feed the badge linked from the main README.

## Writing New Tests

1. Pick the closest folder (unit, instruments, experiments, plotting, smoke).
2. Prefer simulation fixtures; add `@pytest.mark.requires_real_hw` only when a
   device is indispensable.
3. Reuse helpers from `conftest.py` (tmp files, experiments, simulated scopes).
4. Keep CLI and workflow parity—if a test needs additional data files, add them
   under `tests/<area>/` and reference them by relative path.

Follow these conventions and every new test will run identically on laptops,
hardware benches, and CI.
