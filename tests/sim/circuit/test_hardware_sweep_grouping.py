from __future__ import annotations

import pytest

from pytestlab.sim.circuit.calibration import CalibrationDataset
from pytestlab.sim.circuit.calibration import CalibrationRow
from pytestlab.sim.circuit.calibration import split_hardware_dataset


def _rows() -> list[CalibrationRow]:
    rows: list[CalibrationRow] = []
    for sweep_id in ("sweep-a", "sweep-b", "sweep-c", "sweep-d"):
        for index in range(3):
            rows.append(
                CalibrationRow(
                    observable="vout",
                    measured_value=float(index),
                    measured_unit="V",
                    experiment_id="amp-run-1",
                    sweep_id=sweep_id,
                    vbias_v=float(index),
                )
            )
    return rows


def test_hardware_split_groups_entire_sweeps() -> None:
    dataset = CalibrationDataset.from_rows(_rows(), metadata={"source": "hardware"})

    train, validation = split_hardware_dataset(
        dataset, validation_fraction=0.25, seed=11
    )

    train_sweeps = {row.sweep_id for row in train.rows}
    validation_sweeps = {row.sweep_id for row in validation.rows}
    assert train_sweeps
    assert validation_sweeps
    assert train_sweeps.isdisjoint(validation_sweeps)
    assert len(train.rows) + len(validation.rows) == len(dataset.rows)
    assert train.metadata["split_strategy"] == "sweep_id_holdout"


def test_hardware_split_requires_sweep_id() -> None:
    dataset = CalibrationDataset.from_rows(
        [
            CalibrationRow(
                observable="vout",
                measured_value=1.0,
                measured_unit="V",
                experiment_id="amp-run-1",
            )
        ],
        metadata={"source": "hardware"},
    )

    with pytest.raises(ValueError, match="requires sweep_id"):
        split_hardware_dataset(dataset)


def test_sweep_ids_round_trip_jsonl(tmp_path) -> None:
    dataset = CalibrationDataset.from_rows(_rows())
    path = tmp_path / "rows.jsonl"

    dataset.save_jsonl(path)
    loaded = CalibrationDataset.load_jsonl(path)

    assert loaded.rows[0].sweep_id == "sweep-a"
