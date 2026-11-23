# PyTestLab examples

Run these from a PyTestLab source checkout with PyTestLab installed. Python
examples may write plots or databases to the current directory. The examples
below do not connect to hardware.

## Start here

| Workflow | Command |
| --- | --- |
| Simulated power supply | `python examples/simple_hello_world.py` |
| Simulated bench | `python examples/simple_bench.py` |
| Simulated measurement and parameter sweep | `python examples/measurement_session_example.py` or `python examples/simple_sweep.py` |
| Synthetic scope capture and plot | `python examples/simulation/capture_scope.py` |
| Strict replay of a synthetic scope trace | `ptl replay run examples/replay_mode/capture_scope.py --session examples/replay_mode/scope_session.yaml` |
| Independent PSU and DMM simulations | `python examples/simulation/psu_dmm_sweep.py` |

The scope fixture is a source-only profile under `examples/simulation/`.
It demonstrates acquisition and plotting without modeling a physical instrument.
The two instruments in the PSU/DMM sweep are independent simulators.

## More offline examples

- Bench-backed measurements: `python examples/bench_session_integration.py`
  and `python examples/bench_sweep_integration_example.py`. The bench session
  also has an [interactive notebook](bench_session_integration.ipynb).
- Concurrent simulated acquisitions:
  `python examples/parallel/parallel_sweep_example.py`.
- Sweep decorators: `python examples/sweep_decorator_example.py`; compare fixed
  and adaptive sampling with `python examples/advanced_sweep_strategies.py`.
- Experiment records and persistence: `python examples/example_experiment.py`
  and `python examples/simple_database.py`.
- Compliance metadata: `python examples/auto_compliance_demo.py`
  and `python examples/compliance_decorator_example.py`.
- Plotting generated data: `python examples/simple_plotting.py`,
  `python examples/plot_experiment.py`, and
  `python examples/plot_measurement_result_array.py`.
- Native capabilities against an in-memory fake transport:
  `python examples/native_capabilities_offline.py`.
- Declarative operation introspection:
  `python examples/profile_instrument_bench.py`.
- Bench declarations: `ptl bench validate examples/bench.yaml --strict`.
  Inspect a declared measurement route with
  `ptl bench measurement examples/auditable_bench.yaml input_ripple_vpp`.
- [Interactive instrument controls](gui.ipynb) require Jupyter and ipywidgets
  in your notebook environment. The instruments are simulated.

## Live hardware templates

The files below are templates, not offline examples. Copy and review them
before use. Confirm exact addresses, backend host, station wiring, and
applicable safety limits. Do not run them against placeholders.

- [LAMB bench](lamb_bench.yaml): native instruments, camera, and prober.
- [Legacy LAMB profile bench](profile_instrument_bench.yaml): illustrative
  GPIB addresses for legacy generic profile usage.
- [USB cameras](ugreen_cameras.yaml): copy the complete camera resource
  strings from discovery into your bench copy. To actually capture, supply that
  file explicitly: `python examples/ugreen_cameras.py --bench PATH_TO_YOUR_BENCH`.
