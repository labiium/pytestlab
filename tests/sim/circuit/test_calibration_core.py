from __future__ import annotations

import csv
import json

import numpy as np
import pytest

from pytestlab.sim.circuit import CalibrationDataset
from pytestlab.sim.circuit import CalibrationRow
from pytestlab.sim.circuit import MetricResult
from pytestlab.sim.circuit import build_validation_report
from pytestlab.sim.circuit import finite_difference_sensitivity
from pytestlab.sim.circuit import fit_parameters
from pytestlab.sim.circuit import netlist_hash
from pytestlab.sim.circuit import render_param_block
from pytestlab.sim.circuit import save_twin_package
from pytestlab.sim.circuit.calibration.metrics import gain_db_error
from pytestlab.sim.circuit.calibration.metrics import mae
from pytestlab.sim.circuit.calibration.metrics import percent_error
from pytestlab.sim.circuit.calibration.metrics import phase_deg_error
from pytestlab.sim.circuit.calibration.metrics import rmse
from pytestlab.sim.circuit.calibration.metrics import transition_accuracy
from pytestlab.sim.circuit.calibration.package import TwinPackage
from pytestlab.sim.circuit.calibration.parameters import ParameterDeclaration
from pytestlab.sim.circuit.calibration.parameters import ParameterSet


def test_long_dataset_round_trip_hash_and_split(tmp_path) -> None:
    dataset = CalibrationDataset.from_rows(
        [
            CalibrationRow("vout", 1.0, "V", experiment_id="a"),
            CalibrationRow("vout", 2.0, "V", experiment_id="b"),
            CalibrationRow("icc", 3.0, "mA", experiment_id="c"),
        ]
    )
    split = dataset.with_split(validation_fraction=1 / 3, seed=7)
    assert split.split_counts() == {"train": 2, "validation": 1}
    assert split.content_hash().startswith("sha256:")

    path = tmp_path / "dataset.csv"
    split.save_csv(path)
    loaded = CalibrationDataset.load_csv(path, wide=False)

    assert len(loaded) == 3
    assert loaded.content_hash() == split.content_hash()


def test_wide_amplifier_csv_normalizes_observables(tmp_path) -> None:
    path = tmp_path / "wide.csv"
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["experiment", "vbias_v", "vin_v", "vout_v", "icc_ma", "split"],
        )
        writer.writeheader()
        writer.writerow(
            {
                "experiment": "p1",
                "vbias_v": "0.7",
                "vin_v": "0.1",
                "vout_v": "4.2",
                "icc_ma": "1.5",
                "split": "train",
            }
        )

    dataset = CalibrationDataset.load_csv(path)
    observables = {(row.observable, row.measured_unit) for row in dataset}

    assert ("vout", "V") in observables
    assert ("icc", "mA") in observables
    assert all(row.vbias_v == 0.7 for row in dataset)


def test_dataset_rejects_missing_required_long_fields(tmp_path) -> None:
    path = tmp_path / "bad.csv"
    path.write_text("observable,measured_value\nvout,1.0\n")

    with pytest.raises(ValueError, match="measured_unit"):
        CalibrationDataset.load_csv(path, wide=False)


def test_parameter_declarations_render_and_hash_deterministically() -> None:
    params = ParameterSet.from_declarations(
        [
            ParameterDeclaration("bf", 100.0, 50.0, 200.0, "ratio"),
            ParameterDeclaration("rc", 1_000.0, 100.0, 10_000.0, "ohm", frozen=True),
        ]
    )

    assert params.free_declarations()[0].name == "bf"
    assert params.render_param_lines({"bf": 250.0}) == [".param bf=200", ".param rc=1000"]
    assert render_param_block({"bf": 123.0}) == ".param bf=123"
    assert params.parameter_hash() == params.parameter_hash(dict(reversed(params.values.items())))
    assert netlist_hash("R1 a b {rc}", {"rc": 1_000.0}) != netlist_hash(
        "R1 a b {rc}", {"rc": 2_000.0}
    )


def test_metrics_cover_voltage_current_gain_phase_and_transition() -> None:
    assert np.isclose(rmse([1, 2], [2, 4]), np.sqrt(2.5))
    assert mae([1, 2], [2, 4]) == 1.5
    assert percent_error(10, 9).value == 10.0
    assert gain_db_error(3, 1).value == 2.0
    assert phase_deg_error(179, -179).value == 2.0
    assert transition_accuracy(["HIGH", "LOW"], ["HIGH", "MID"]).value == 0.5


def test_deterministic_fitter_reduces_synthetic_loss() -> None:
    params = ParameterSet.from_declarations(
        [ParameterDeclaration("gain", 0.0, -10.0, 10.0, "V/V")]
    )

    def loss(values: dict[str, float]) -> float:
        return (values["gain"] - 3.0) ** 2

    result = fit_parameters(params, loss, max_evaluations=80, seed=123)

    assert result.improved
    assert result.final_loss < result.initial_loss * 0.1
    assert abs(result.fitted_values["gain"] - 3.0) < 1.0


def test_sensitivity_marks_observable_free_parameters() -> None:
    params = ParameterSet.from_declarations(
        [
            ParameterDeclaration("active", 1.0, 0.0, 2.0, "ratio"),
            ParameterDeclaration("frozen", 1.0, 0.0, 2.0, "ratio", frozen=True),
        ]
    )

    result = finite_difference_sensitivity(params, lambda values: values["active"] ** 2)

    assert "active" in result.observable_parameters()
    assert "frozen" not in result.derivatives


def test_report_and_twin_package_round_trip(tmp_path) -> None:
    dataset = CalibrationDataset.from_rows(
        [CalibrationRow("vout", 1.0, "V", split="train"), CalibrationRow("vout", 1.1, "V", split="validation")]
    )
    params = ParameterSet.from_declarations(
        [ParameterDeclaration("bf", 100.0, 50.0, 200.0, "ratio")]
    )
    report = build_validation_report(
        dataset,
        metrics={"validation": [MetricResult("rmse", 0.01, "V", passed=True, threshold=0.1)]},
        parameters=params.values,
        operating_region={"vin_v": [-0.1, 0.1]},
        provenance={"seed": 123},
    )
    root = tmp_path / "amp.twin"

    package = save_twin_package(
        root,
        netlist_text=".param bf=100\n.end\n",
        parameter_set=params,
        dataset=dataset,
        report=report,
        provenance={"seed": 123},
        overwrite=True,
    )
    loaded = TwinPackage.load(root)

    assert package.parameter_values == {"bf": 100.0}
    assert loaded.parameter_values == {"bf": 100.0}
    assert "Not validated outside" in (root / "validation_report.md").read_text()
    assert json.loads((root / "validation_report.json").read_text())["passed"] is True
