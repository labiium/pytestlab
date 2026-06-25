from __future__ import annotations

import json
import math
import zipfile
from typing import Any
from typing import cast

import pytest

from pytestlab.bench import Bench
from pytestlab.common.enums import SCPIOnOff
from pytestlab.config.device_config import DeviceConfig
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
    pytest.importorskip("pytestlab.sim.circuit")
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

        cast(Any, bench.psu1).set_voltage(1, 2.5)
        channel_state = bench._sim_session.psus["psu1"].state.channels["CH1"]
        assert channel_state.voltage_setpoint == pytest.approx(2.5)
    finally:
        bench.close_all()


def test_circuit_sim_psu_uses_profile_channels_and_scpi_channel_selectors(tmp_path):
    pytest.importorskip("pytestlab.sim.circuit")
    netlist_path = tmp_path / "circuit.sp"
    netlist_path.write_text("R1 vcc 0 100\nR2 vbias 0 100\n.end\n")
    bench_path = tmp_path / "bench_sim.yaml"
    bench_path.write_text(
        """
bench_name: "Circuit Sim Multichannel PSU Bench"
simulate: true
instruments:
  psu:
    profile: "keysight/EDU36311A"
    simulate: true
    backend:
      type: circuit_sim
sim_circuit:
  netlist: circuit.sp
  seed: 42
  wiring:
    psu.CH1+: vcc
    psu.CH1-: "0"
    psu.CH2+: vbias
    psu.CH2-: "0"
"""
    )

    bench = Bench.open(bench_path)
    try:
        assert set(bench._sim_session.psus["psu"].state.channels) == {"CH1", "CH2", "CH3"}

        cast(Any, bench.psu).set_voltage(1, 5.0)
        cast(Any, bench.psu).set_current(1, 0.1)
        cast(Any, bench.psu).output(1, True)
        cast(Any, bench.psu).set_voltage(2, 2.0)
        cast(Any, bench.psu).set_current(2, 0.1)
        cast(Any, bench.psu).output(2, True)

        channels = bench._sim_session.psus["psu"].state.channels
        assert channels["CH1"].voltage_setpoint == pytest.approx(5.0)
        assert channels["CH2"].voltage_setpoint == pytest.approx(2.0)
        assert _nominal(cast(Any, bench.psu).read_voltage(2)) == pytest.approx(2.0, abs=0.02)
    finally:
        bench.close_all()


def test_branch_free_driver_experiment_runs_against_circuit_sim_yaml(tmp_path):
    pytest.importorskip("pytestlab.sim.circuit")
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
        assert math.isfinite(_nominal(result["current"]))
        assert bench._sim_session is not None
        channel_state = bench._sim_session.psus["psu1"].state.channels["CH1"]
        assert channel_state.enabled is True
        assert channel_state.current_limit == pytest.approx(0.1)
        frame = result["waveform"].values
        assert frame.height > 100
        assert {"Time (s)", "Channel 1 (V)"}.issubset(frame.columns)
    finally:
        bench.close_all()


def test_circuit_sim_backend_rejects_private_session_in_backend_spec(tmp_path):
    pytest.importorskip("pytestlab.sim.circuit")
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
        backend_config = bench._config.instruments["psu1"].backend
        assert backend_config is not None
        assert backend_config["_sim_session"] == "sentinel"
    finally:
        bench.close_all()

    context = BackendBuildContext(
        config=cast(DeviceConfig, bench._config.instruments["psu1"]),
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
    pytest.importorskip("pytestlab.sim.circuit")
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
    pytest.importorskip("pytestlab.sim.circuit")
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


def _write_real_twin_package(path):
    from pytestlab.sim.circuit.calibration import TwinPackage
    from pytestlab.sim.circuit.calibration import save_twin_package
    from pytestlab.sim.circuit.parameters import ParameterSet
    from pytestlab.sim.circuit.parameters import ParameterSpec

    params = ParameterSet.from_values(
        {"rload": 100.0, "gain": 2.5},
        specs={"rload": ParameterSpec("rload", 100.0, 10.0, 1000.0, unit="ohm")},
    )
    package = TwinPackage(
        netlist_text="RLOAD vload 0 {rload}\n.end\n",
        parameters=params,
        manifest={"base_netlist_hash": "base-hash"},
        validation_report={"validation_status": "synthetic_only", "hardware_validated": False},
    )
    save_twin_package(package, path)
    return package


def _validation_report_v2(netlist_text, parameters):
    import hashlib

    from pytestlab.sim.circuit.calibration import TwinPackage
    from pytestlab.sim.circuit.calibration import validation_report_hash
    from pytestlab.sim.circuit.parameters import parameter_hash

    provisional = TwinPackage(netlist_text=netlist_text, parameters=parameters)
    metric_values = {
        "vout_mae_v": (0.02, 0.05, "<=", "V"),
        "supply_current_mae_ma": (0.03, 0.1, "<=", "mA"),
        "state_classification_accuracy": (1.0, 0.98, ">=", "ratio"),
        "transition_boundary_mae_v": (0.01, 0.05, "<=", "V"),
        "transition_boundary_max_error_v": (0.02, 0.08, "<=", "V"),
    }
    report = {
        "schema_version": 2,
        "validation_status": "hardware_validated",
        "hardware_validated": True,
        "source": "hardware",
        "circuit_id": "two_transistor_amp",
        "dataset_hashes": {"train": "sha256:train", "validation": "sha256:validation"},
        "package_hashes": {
            "base_netlist_hash": hashlib.sha256(netlist_text.encode()).hexdigest(),
            "rendered_netlist_hash": hashlib.sha256(
                provisional.rendered_netlist_text().encode()
            ).hexdigest(),
            "parameter_hash": parameter_hash(parameters),
        },
        "thresholds": {
            name: {"limit": limit, "comparator": comparator}
            for name, (_value, limit, comparator, _units) in metric_values.items()
        },
        "metrics": {
            name: {"value": value, "passed": True, "units": units}
            for name, (value, _limit, _comparator, units) in metric_values.items()
        },
        "split": {
            "strategy": "sweep_id_holdout",
            "train_sweep_ids": ["sweep-train"],
            "validation_sweep_ids": ["sweep-validation"],
        },
        "environment": {},
        "provenance": {},
        "non_claim": None,
    }
    return report, validation_report_hash(report)


def _write_v2_twin_package(path):
    from pytestlab.sim.circuit.calibration import TwinPackage
    from pytestlab.sim.circuit.calibration import save_twin_package
    from pytestlab.sim.circuit.parameters import ParameterSet

    netlist_text = "RLOAD vload 0 {rload}\n.end\n"
    parameters = ParameterSet.from_values({"rload": 100.0})
    report, _hash = _validation_report_v2(netlist_text, parameters)
    package = TwinPackage(
        netlist_text=netlist_text,
        parameters=parameters,
        validation_report=report,
    )
    save_twin_package(package, path)
    return package


def test_bench_open_circuit_sim_twin_package_loads_model_params(tmp_path):
    pytest.importorskip("pytestlab.sim.circuit")
    twin_dir = tmp_path / "amp.twin"
    package = _write_real_twin_package(twin_dir)
    bench_path = tmp_path / "bench_sim.yaml"
    bench_path.write_text(
        """
bench_name: "Circuit Sim Twin Bench"
simulate: true
instruments:
  psu1:
    profile: "keysight/EDU36311A"
    simulate: true
    backend:
      type: circuit_sim
sim_circuit:
  twin_package: amp.twin
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
        assert bench._sim_session.model_params == {"rload": 100.0, "gain": 2.5}
        assert (
            bench._sim_session.twin_package["parameter_hash"]
            == package.to_manifest()["parameter_hash"]
        )
        assert bench._sim_session.circuit.metadata["twin_package"].endswith("amp.twin")
    finally:
        bench.close_all()


def test_sim_circuit_requires_exactly_one_source():
    from pydantic import ValidationError

    from pytestlab.config.bench_loader import load_bench_yaml

    with pytest.raises(ValidationError, match="exactly one"):
        load_bench_yaml(
            {
                "bench_name": "Bad Sim Bench",
                "instruments": {
                    "psu1": {
                        "profile": "keysight/EDU36311A",
                        "backend": {"type": "circuit_sim"},
                    }
                },
                "sim_circuit": {"netlist": "circuit.sp", "twin_package": "amp.twin"},
            }
        )


def test_twin_package_manifest_loader_extracts_rendered_netlist_and_params(tmp_path):
    from pytestlab.config.bench_loader import _load_twin_package

    twin_dir = tmp_path / "amp.twin"
    package = _write_real_twin_package(twin_dir)

    netlist_path, payload = _load_twin_package(twin_dir)

    assert netlist_path == (twin_dir / "rendered_netlist.sp").resolve()
    assert payload["model_params"] == {"rload": 100.0, "gain": 2.5}
    assert payload["parameter_hash"] == package.to_manifest()["parameter_hash"]
    assert payload["package_path"] == twin_dir.resolve()


def test_twin_package_v2_validation_metadata_exposed_to_session(tmp_path):
    pytest.importorskip("pytestlab.sim.circuit")
    package = _write_v2_twin_package(tmp_path / "amp.twin")
    bench_path = tmp_path / "bench_sim.yaml"
    bench_path.write_text(
        """
bench_name: "Circuit Sim V2 Twin Bench"
simulate: true
instruments:
  psu1:
    profile: "keysight/EDU36311A"
    simulate: true
    backend:
      type: circuit_sim
sim_circuit:
  twin_package: amp.twin
  seed: 42
  wiring:
    psu1.CH1+: vload
    psu1.CH1-: "0"
"""
    )

    bench = Bench.open(bench_path)
    try:
        assert bench._sim_session is not None
        twin = bench._sim_session.twin_package
        assert twin["validation_status"] == "hardware_validated"
        assert twin["hardware_validated"] is True
        assert twin["validation_report_hash"] == package.to_manifest()["validation_report_hash"]
        assert twin["validation_report"]["schema_version"] == 2
        assert bench._sim_session.circuit.metadata["validation_status"] == "hardware_validated"
        assert bench._sim_session.circuit.metadata["hardware_validated"] is True
    finally:
        bench.close_all()


def test_twin_package_v2_validation_report_tamper_rejected_by_pytestlab(tmp_path):
    from pytestlab.config.bench_loader import _load_twin_package
    from pytestlab.errors import InstrumentConfigurationError

    twin_dir = tmp_path / "amp.twin"
    _write_v2_twin_package(twin_dir)
    report = json.loads((twin_dir / "validation_report.json").read_text())
    report["metrics"]["vout_mae_v"]["value"] = 999.0
    (twin_dir / "validation_report.json").write_text(json.dumps(report))

    with pytest.raises(
        InstrumentConfigurationError,
        match="validation_report_hash|passed disagrees with threshold",
    ):
        _load_twin_package(twin_dir)


def test_twin_package_rejects_rendered_netlist_escape(tmp_path):
    from pytestlab.config.bench_loader import _load_twin_package
    from pytestlab.errors import InstrumentConfigurationError

    twin_dir = tmp_path / "amp.twin"
    _write_real_twin_package(twin_dir)
    manifest_path = twin_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["rendered_netlist"] = "../escape.sp"
    manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(InstrumentConfigurationError, match="escapes package root"):
        _load_twin_package(twin_dir)


def test_twin_package_zip_rejects_rendered_netlist_escape(tmp_path):
    from pytestlab.config.bench_loader import _load_twin_package
    from pytestlab.errors import InstrumentConfigurationError

    twin_zip = tmp_path / "amp.twin.zip"
    package = _write_real_twin_package(twin_zip)
    manifest = package.to_manifest()
    manifest["rendered_netlist"] = "../escape.sp"

    with zipfile.ZipFile(twin_zip, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("parameters.json", json.dumps(package.parameters.to_dict()))
        zf.writestr("../escape.sp", package.rendered_netlist_text())

    with pytest.raises(InstrumentConfigurationError, match="escapes package root"):
        _load_twin_package(twin_zip)


def test_twin_package_zip_rejects_rendered_netlist_tamper(tmp_path):
    from pytestlab.config.bench_loader import _load_twin_package
    from pytestlab.errors import InstrumentConfigurationError

    twin_zip = tmp_path / "amp.twin.zip"
    package = _write_real_twin_package(twin_zip)
    manifest = package.to_manifest()
    tampered = package.rendered_netlist_text().replace(".param rload=100", ".param rload=999")

    with zipfile.ZipFile(twin_zip, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("parameters.json", json.dumps(package.parameters.to_dict()))
        zf.writestr("rendered_netlist.sp", tampered)

    with pytest.raises(InstrumentConfigurationError, match="rendered_netlist_hash"):
        _load_twin_package(twin_zip)


def test_twin_package_rejects_hash_mismatch(tmp_path):
    from pytestlab.config.bench_loader import _load_twin_package
    from pytestlab.errors import InstrumentConfigurationError

    twin_dir = tmp_path / "amp.twin"
    _write_real_twin_package(twin_dir)
    (twin_dir / "rendered_netlist.sp").write_text("RLOAD vload 0 101\n.end\n")

    with pytest.raises(InstrumentConfigurationError, match="rendered_netlist_hash"):
        _load_twin_package(twin_dir)


def test_bench_open_rejects_wiring_to_unknown_netlist_node(tmp_path):
    """A wiring target that is not a real netlist node must fail at open time
    with a did-you-mean suggestion, never silently float to ~0 V."""
    pytest.importorskip("pytestlab.sim.circuit")
    from pytestlab.sim.circuit.wiring import UnknownNode

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
    psu1.CH1+: vlod
    psu1.CH1-: "0"
"""
    )

    # 'vlod' is a typo for 'vload'; opening the bench must reject it.
    with pytest.raises(UnknownNode, match="vlod"):
        Bench.open(bench_path)
