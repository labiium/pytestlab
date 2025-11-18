# Command-Line Guide (CLI)

This guide explains how to run the examples, utilities, and replay workflows from the command line in this `examples` folder. It covers quick-start commands, simulation vs. hardware modes, and the `pytestlab replay` CLI.

## Prerequisites

- Python 3.9+ recommended
- Optional: virtual environment
- The `pytestlab` package installed and importable in your environment
- For hardware mode: a reachable Lamb server and connected instruments

## Quick Start

- Run the simple bench verification:
  - `python simple_bench_test.py`
- Run the comprehensive bench tests:
  - `python test_smarbench.py`
- Run direct instrument test (no bench YAML):
  - `python test_direct_instruments.py`

All the example scripts in this folder are runnable directly with `python <script>.py`.

## Simulation vs. Hardware

- Simulation is controlled by the bench YAML (`simulate: true|false`).
- To run fully simulated examples, use a YAML with `simulate: true` (e.g., `bench.yaml`).
- To target real instruments, set `simulate: false` and ensure Lamb server is reachable in `smarbench.yaml`.

Common configs:
- `bench.yaml` — simulated bench with safety/automation examples
- `smarbench.yaml` — production-style bench with four instruments; defaults to Lamb backend

## Common Example Commands

- Load the smart bench and print instrument information:
  - `python simple_bench_test.py`
- Example experiment walkthrough (structured steps):
  - `python example_experiment.py`
- Measurement session and sweep:
  - `python measurement_session_example.py`
  - `python measurement_session_sweep.py`
- Bench/session integration examples:
  - `python bench_session_integration.py`
  - `python bench_sweep_integration_example.py`
- Parallel demo:
  - `python parallel/parallel_sweep_example.py`
  - `python parallel_measurement_demo.py`
- Facade and measurement patterns:
  - `python facade_example.py`
  - `python measurement_patterns.py`
- Plot helpers (produce simple plots/prints):
  - `python plot_experiment.py`
  - `python plot_measurement_result_array.py`
  - `python plot_dsx1204g_channel.py`

Most scripts do not take arguments; they read configuration from YAML files in this directory.

## Pre/Post Hooks Utilities

The `scripts/` folder contains utility helpers designed for bench automation hooks:
- `scripts/setup_environment.py` — pre-experiment environment setup
  - Creates `data/` and `logs/`, logs start in `logs/experiment.log`
  - Run directly: `python scripts/setup_environment.py`
- `scripts/save_results.py` — post-experiment results archiver
  - Scans `data/` for common outputs and writes JSON summary to `results/`
  - Run directly: `python scripts/save_results.py`

These are ideal to reference from YAML `automation.pre_experiment` and `automation.post_experiment` sections.

## Using the Replay CLI

PyTestLab provides a replay system to record and deterministically replay instrument I/O.

- Show help:
  - `pytestlab replay --help`

- Record a session (runs your measurement script against real/sim bench and captures I/O):
  - `pytestlab replay record example_measurement.py --bench replay_mode/example_bench.yaml --output replay_mode/recorded_session.yaml`

- Replay a session (runs your script against a replay backend):
  - `pytestlab replay run example_measurement.py --session replay_mode/recorded_session.yaml`

Additional examples and walkthroughs:
- `python replay_mode/replay_system_demo.py` — success + mismatch detection demo
- `python replay_mode/test_real_replay.py` — replay validations
- Shell workflows:
  - `bash replay_mode/replay_system_final_demo.sh`
  - `bash replay_mode/replay_workflow_example.sh`

Notes:
- For hardware capture, ensure `simulate: false` in your bench YAML and Lamb is reachable.
- The replay YAML (session) is self-contained and can be checked into version control for auditability.

## YAML Automation and Safety

- Safety limits are enforced via YAML (e.g., PSU channel maximums). Attempts to exceed are rejected.
- Automation hooks run before/after experiments. Example (from `smarbench.yaml`):
  - `automation.pre_experiment`: disable outputs, initialize instruments
  - `automation.post_experiment`: restore to safe state

Tip: Point hooks to the scripts above to structure setup/teardown and result capture.

## Troubleshooting

- Name resolution for Lamb server errors:
  - Add `127.0.0.1 lamb-server` to `/etc/hosts` when running locally
- 404s from Lamb `/add` or backend connection issues:
  - Use simulation: set `simulate: true` in your YAML to bypass hardware
- Import errors for `pytestlab`:
  - Verify your virtualenv and installation; ensure `python -c "import pytestlab; print(pytestlab.__version__)"` succeeds

## Tips

- Keep logs and outputs organized (`logs/`, `results/`, `data/`). The helpers create/populate these folders.
- Start with `simulation` for development and CI; switch to hardware after scripts are stable.
- Use replay to turn lab interactions into fast, deterministic tests for CI.

## Reference Scripts Map

- Bench and integration: `simple_bench_test.py`, `test_smarbench.py`, `bench_session_integration.py`, `bench_example.py`
- Sessions and sweeps: `measurement_session_example.py`, `measurement_session_sweep.py`, `bench_sweep_integration_example.py`
- Parallelization: `parallel/parallel_sweep_example.py`, `parallel_measurement_demo.py`
- Replay system: `replay_mode/*` (see README-style comments in those scripts)
- Utilities: `scripts/setup_environment.py`, `scripts/save_results.py`
- Plotting: `plot_experiment.py`, `plot_measurement_result_array.py`, `plot_dsx1204g_channel.py`

---

If you want, I can add CLI argument parsing to specific scripts (e.g., select YAML path or toggle simulate) and update this guide accordingly.
