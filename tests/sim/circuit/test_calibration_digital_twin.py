from __future__ import annotations

import numpy as np
import pytest

from pytestlab.sim.circuit.calibration import CalibrationDataset
from pytestlab.sim.circuit.calibration import CalibrationRow
from pytestlab.sim.circuit.calibration import MetricResult
from pytestlab.sim.circuit.calibration import build_validation_report
from pytestlab.sim.circuit.calibration import finite_difference_sensitivity
from pytestlab.sim.circuit.calibration import fit_parameters
from pytestlab.sim.circuit.calibration import load_twin_package
from pytestlab.sim.circuit.calibration import rmse
from pytestlab.sim.circuit.calibration import save_twin_package
from pytestlab.sim.circuit.calibration import split_dataset
from pytestlab.sim.circuit.calibration import transition_graph
from pytestlab.sim.circuit.calibration.parameters import ParameterDeclaration
from pytestlab.sim.circuit.calibration.parameters import ParameterSet
from pytestlab.sim.circuit.calibration.twin_package import TwinPackage
from pytestlab.sim.circuit.parameters import ParameterSet as RuntimeParameterSet
from pytestlab.sim.circuit.parameters import ParameterSpec
from pytestlab.sim.circuit.parameters import parameter_hash
from pytestlab.sim.circuit.spice import _assemble_netlist


def _row(i: int, split: str = "train") -> CalibrationRow:
    return CalibrationRow(
        observable="vout",
        measured_value=float(i * 2),
        measured_unit="V",
        experiment_id=f"row-{i}",
        split=split,
        vbias_v=float(i),
    )


def test_dataset_split_is_deterministic() -> None:
    dataset = CalibrationDataset.from_rows(_row(i) for i in range(10))

    train_a, val_a = split_dataset(dataset, validation_fraction=0.3, seed=42)
    train_b, val_b = split_dataset(dataset, validation_fraction=0.3, seed=42)

    assert [row.experiment_id for row in train_a.rows] == [
        row.experiment_id for row in train_b.rows
    ]
    assert [row.experiment_id for row in val_a.rows] == [row.experiment_id for row in val_b.rows]
    assert len(train_a) + len(val_a) == 10
    assert len(val_a) >= 1


def test_metrics_and_transition_graph() -> None:
    assert rmse([1.0, 2.0], [1.0, 4.0]) == pytest.approx(np.sqrt(2.0))
    graph = transition_graph([(0.0, "HIGH"), (0.5, "HIGH"), (1.0, "LOW")])
    assert graph == [
        {"start": 0.0, "stop": 0.5, "state": "HIGH"},
        {"start": 1.0, "stop": 1.0, "state": "LOW"},
    ]


def test_runtime_parameter_set_validation_hash_and_rendering() -> None:
    spec = ParameterSpec("bf", nominal=120.0, min_value=50.0, max_value=300.0, unit="1")
    params = RuntimeParameterSet.from_values({"rc": 10_000.0}, specs={"bf": spec})

    assert params.resolve()["bf"] == 120.0
    assert params.resolve({"bf": 150.0})["bf"] == 150.0
    with pytest.raises(ValueError, match="above max_value"):
        params.resolve({"bf": 301.0})
    assert parameter_hash(params) == parameter_hash(RuntimeParameterSet.from_dict(params.to_dict()))
    rendered = _assemble_netlist(["R1 out 0 {rc}"], [".control", "quit", ".endc"], params.resolve())
    assert ".param bf=120" in rendered
    assert ".param rc=10000" in rendered


def test_validation_report_records_provenance_and_non_claims() -> None:
    dataset = CalibrationDataset.from_rows([_row(1), _row(2, split="validation")])
    report = build_validation_report(
        dataset,
        metrics={"train": [MetricResult("rmse", rmse([1.0], [1.1]), passed=True)]},
        parameters={"bf": 120.0},
        operating_region={"source": "synthetic_ci"},
        provenance={
            "base_netlist_hash": "base",
            "rendered_netlist_hash": "rendered",
            "parameter_hash": parameter_hash({"bf": 120.0}),
            "hardware_validated": False,
        },
    )

    assert report.passed is True
    assert report.provenance["hardware_validated"] is False
    assert report.provenance["base_netlist_hash"] == "base"
    assert report.provenance["rendered_netlist_hash"] == "rendered"
    assert "parameter_hash" in report.provenance


def test_builtin_fitter_and_sensitivity() -> None:
    params = ParameterSet.from_declarations(
        [ParameterDeclaration("gain", initial=1.0, lower=0.0, upper=5.0, unit="1")]
    )

    def loss(values: dict[str, float]) -> float:
        return (values["gain"] - 2.5) ** 2

    result = fit_parameters(params, loss, max_evaluations=80, seed=7)

    assert result.final_loss < result.initial_loss
    assert result.fitted_values["gain"] == pytest.approx(2.5, abs=0.2)
    sensitivity = finite_difference_sensitivity(params.with_values(result.fitted_values), loss)
    assert "gain" in sensitivity.derivatives


def test_twin_package_roundtrip(tmp_path) -> None:
    params = RuntimeParameterSet.from_values(
        {"bf": 120.0}, specs={"bf": ParameterSpec("bf", 100.0, 50.0, 300.0)}
    )
    package = TwinPackage(
        netlist_text="R1 out 0 {rc}\n.end\n",
        parameters=params,
        manifest={"base_netlist_hash": "base", "rendered_netlist_hash": "rendered"},
        validation_report={"status": "synthetic_only"},
    )
    path = tmp_path / "amp.twin"

    save_twin_package(package, path)
    loaded = load_twin_package(path)

    assert loaded.netlist_text == package.netlist_text
    assert loaded.model_params == {"bf": 120.0}
    assert loaded.manifest["parameter_hash"] == parameter_hash(params)
