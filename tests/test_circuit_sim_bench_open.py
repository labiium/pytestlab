from __future__ import annotations

import math

import pytest

from pytestlab.bench import Bench
from pytestlab.common.enums import SCPIOnOff
from pytestlab.config.multimeter_config import DMMFunction
from pytestlab.devices.registry import BackendBuildContext
from pytestlab.errors import InstrumentConfigurationError
from pytestlab.instruments.backends.circuit_sim_backend import CircuitSimBackend
from pytestlab.instruments.backends.circuit_sim_backend import build_circuit_sim_backend


def run_experiment(bench):
    bench.psu1.set_voltage(1, 2.5)
    bench.psu1.set_current(1, 0.1)
    bench.psu1.output(1, True)
    bench.awg1.set_frequency(1, 1_000.0)
    bench.awg1.set_amplitude(1, 1.0)
    bench.awg1.set_output_state(1, SCPIOnOff.ON)
    bench.scope1.run()
    voltage = bench.dmm1.measure(DMMFunction.VOLTAGE_DC)
    current = bench.psu1.read_current(1)
    waveform = bench.scope1.read_channels(1)
    return {"voltage": voltage, "current": current, "waveform": waveform}


def _nominal(value):
    return getattr(value, "nominal_value", value)


def test_bench_open_circuit_sim_uses_runtime_session(tmp_path):
    pytest.importorskip("pytestlab_sim")
    netlist_path = tmp_path / "circuit.sp"
    netlist_path.write_text("RLOAD vload 0 100\n.end\n")
    bench_path = tmp_path / "bench_sim.yaml"
    bench_path.write_text(
        """
bench_name: "Circuit Sim Bench"
simulate: true
instruments:
  psu1:
    profile: "keysight/EDU36311A"
    simulate: true
    backend:
      type: circuit_sim
sim_circuit:
  netlist: circuit.sp
  seed: 42
  wiring:
    psu1.CH1+: vload
    psu1.CH1-: "0"
"""
    )

    bench = Bench.open(bench_path)
    try:
        backend = bench.psu1._backend
        assert isinstance(backend, CircuitSimBackend)
        assert bench._sim_session is not None
        assert backend._inner.session is bench._sim_session
        assert "_sim_session" not in (bench._config.instruments["psu1"].backend or {})

        bench.psu1.set_voltage(1, 2.5)
        channel_state = bench._sim_session.psus["psu1"].state.channels["CH1"]
        assert channel_state.voltage_setpoint == pytest.approx(2.5)
    finally:
        bench.close_all()


def test_branch_free_driver_experiment_runs_against_circuit_sim_yaml(tmp_path):
    pytest.importorskip("pytestlab_sim")
    netlist_path = tmp_path / "rc_test.sp"
    netlist_path.write_text(
        """
RLOAD vload 0 100
R1 vin vout 1000
C1 vout 0 1u
.end
"""
    )
    bench_path = tmp_path / "bench_sim.yaml"
    bench_path.write_text(
        """
bench_name: "Circuit Sim Experiment Bench"
simulate: true
instruments:
  psu1:
    profile: "keysight/EDU36311A"
    simulate: true
    backend:
      type: circuit_sim
  awg1:
    profile: "keysight/EDU33212A"
    simulate: true
    backend:
      type: circuit_sim
  dmm1:
    profile: "keysight/EDU34450A"
    simulate: true
    backend:
      type: circuit_sim
  scope1:
    profile: "keysight/DSOX1204G"
    simulate: true
    backend:
      type: circuit_sim
sim_circuit:
  netlist: rc_test.sp
  seed: 42
  wiring:
    psu1.CH1+: vload
    psu1.CH1-: "0"
    awg1.HI: vin
    awg1.LO: "0"
    dmm1.V.HI: vout
    dmm1.V.LO: "0"
    scope1.CH1+: vout
    scope1.CH1-: "0"
"""
    )

    bench = Bench.open(bench_path)
    try:
        result = run_experiment(bench)
        assert _nominal(result["voltage"].values) == pytest.approx(0.0, abs=1e-3)
        assert math.isfinite(float(result["current"]))
        channel_state = bench._sim_session.psus["psu1"].state.channels["CH1"]
        assert channel_state.enabled is True
        assert channel_state.current_limit == pytest.approx(0.1)
        frame = result["waveform"].values
        assert frame.height > 100
        assert {"Time (s)", "Channel 1 (V)"}.issubset(frame.columns)
    finally:
        bench.close_all()


def test_circuit_sim_backend_rejects_private_session_in_backend_spec(tmp_path):
    pytest.importorskip("pytestlab_sim")
    bench_path = tmp_path / "bench_sim.yaml"
    bench_path.write_text(
        """
bench_name: "Circuit Sim Bench"
simulate: true
instruments:
  psu1:
    profile: "keysight/EDU36311A"
    simulate: true
    backend:
      type: circuit_sim
      _sim_session: sentinel
sim_circuit:
  netlist: circuit.sp
  wiring:
    psu1.CH1+: vload
    psu1.CH1-: "0"
"""
    )
    (tmp_path / "circuit.sp").write_text("RLOAD vload 0 100\n.end\n")
    bench = Bench.open(bench_path)
    try:
        assert bench._sim_session is not None
        assert bench._config.instruments["psu1"].backend["_sim_session"] == "sentinel"
    finally:
        bench.close_all()

    context = BackendBuildContext(
        config=bench._config.instruments["psu1"],
        config_source="keysight/EDU36311A",
        address=None,
        timeout_ms=5_000,
        simulate=True,
        backend_type="circuit_sim",
        backend_spec={"type": "circuit_sim", "_sim_session": "sentinel", "instrument_id": "psu1"},
    )
    with pytest.raises(RuntimeError, match="shared Session"):
        build_circuit_sim_backend(context)


def test_bench_open_dict_rejects_sim_circuit_without_base_path():
    pytest.importorskip("pytestlab_sim")
    with pytest.raises(InstrumentConfigurationError, match="filesystem path"):
        Bench.open(
            {
                "bench_name": "Dict Sim Bench",
                "instruments": {
                    "psu1": {
                        "profile": "keysight/EDU36311A",
                        "backend": {"type": "circuit_sim"},
                    }
                },
                "sim_circuit": {"netlist": "circuit.sp"},
            }
        )


def test_circuit_sim_unknown_profile_fails_closed(tmp_path):
    pytest.importorskip("pytestlab_sim")
    bench_path = tmp_path / "bench_sim.yaml"
    bench_path.write_text(
        """
bench_name: "Unsupported Circuit Sim Bench"
simulate: true
instruments:
  pm1:
    profile: "keysight/U2000A_PM"
    simulate: true
    backend:
      type: circuit_sim
sim_circuit:
  netlist: circuit.sp
  wiring:
    pm1.HI: vload
    pm1.LO: "0"
"""
    )
    (tmp_path / "circuit.sp").write_text("RLOAD vload 0 100\n.end\n")

    with pytest.raises(InstrumentConfigurationError, match="does not support"):
        Bench.open(bench_path)
