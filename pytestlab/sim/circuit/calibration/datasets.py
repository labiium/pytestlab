from __future__ import annotations

import csv
import json
from collections.abc import Iterable
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class MeasurementRow:
    inputs: dict[str, float] = field(default_factory=dict)
    outputs: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"inputs": self.inputs, "outputs": self.outputs, "metadata": self.metadata}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> MeasurementRow:
        if "inputs" in data or "outputs" in data:
            return cls(
                inputs={str(k): float(v) for k, v in dict(data.get("inputs", {})).items()},
                outputs={str(k): float(v) for k, v in dict(data.get("outputs", {})).items()},
                metadata=dict(data.get("metadata", {})),
            )
        inputs: dict[str, float] = {}
        outputs: dict[str, float] = {}
        metadata: dict[str, Any] = {}
        for key, value in data.items():
            if key.startswith(("in_", "input_", "bias_", "sweep_")):
                inputs[str(key)] = float(value)
            elif isinstance(value, int | float):
                outputs[str(key)] = float(value)
            else:
                metadata[str(key)] = value
        return cls(inputs=inputs, outputs=outputs, metadata=metadata)


@dataclass(frozen=True)
class CalibrationDataset:
    rows: tuple[MeasurementRow, ...]
    metadata: dict[str, Any] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.rows)

    def to_dict(self) -> dict[str, Any]:
        return {"metadata": self.metadata, "rows": [row.to_dict() for row in self.rows]}

    @classmethod
    def from_rows(
        cls, rows: Iterable[MeasurementRow | Mapping[str, Any]], *, metadata: Mapping[str, Any] | None = None
    ) -> CalibrationDataset:
        return cls(
            rows=tuple(row if isinstance(row, MeasurementRow) else MeasurementRow.from_dict(row) for row in rows),
            metadata=dict(metadata or {}),
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CalibrationDataset:
        return cls.from_rows(data.get("rows", []), metadata=data.get("metadata", {}))

    @classmethod
    def from_wide_csv(cls, path: str | Path, *, input_prefixes: tuple[str, ...] = ("in_", "input_", "bias_", "sweep_")) -> CalibrationDataset:
        rows: list[MeasurementRow] = []
        with Path(path).open(newline="") as fh:
            for raw in csv.DictReader(fh):
                inputs: dict[str, float] = {}
                outputs: dict[str, float] = {}
                metadata: dict[str, Any] = {}
                for key, value in raw.items():
                    if value is None or value == "":
                        continue
                    try:
                        numeric = float(value)
                    except ValueError:
                        metadata[key] = value
                        continue
                    if key.startswith(input_prefixes):
                        inputs[key] = numeric
                    else:
                        outputs[key] = numeric
                rows.append(MeasurementRow(inputs=inputs, outputs=outputs, metadata=metadata))
        return cls(rows=tuple(rows), metadata={"source": str(path), "format": "wide_csv"})


def split_dataset(dataset: CalibrationDataset, *, validation_fraction: float = 0.2, seed: int = 1337) -> tuple[CalibrationDataset, CalibrationDataset]:
    if not 0.0 <= validation_fraction < 1.0:
        raise ValueError("validation_fraction must be in [0, 1)")
    import random

    rng = random.Random(int(seed))
    indices = list(range(len(dataset.rows)))
    rng.shuffle(indices)
    val_count = int(round(len(indices) * validation_fraction))
    validation_idx = set(indices[:val_count])
    train = [row for i, row in enumerate(dataset.rows) if i not in validation_idx]
    validation = [row for i, row in enumerate(dataset.rows) if i in validation_idx]
    meta = dict(dataset.metadata)
    meta.update({"split_seed": int(seed), "validation_fraction": float(validation_fraction)})
    return CalibrationDataset(tuple(train), meta), CalibrationDataset(tuple(validation), meta)


def load_dataset(path: str | Path) -> CalibrationDataset:
    p = Path(path)
    if p.suffix.lower() == ".csv":
        return CalibrationDataset.from_wide_csv(p)
    data = json.loads(p.read_text()) if p.suffix.lower() == ".json" else yaml.safe_load(p.read_text())
    return CalibrationDataset.from_dict(data)


def save_dataset(dataset: CalibrationDataset, path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.suffix.lower() in {".yaml", ".yml"}:
        p.write_text(yaml.safe_dump(dataset.to_dict(), sort_keys=True))
    else:
        p.write_text(json.dumps(dataset.to_dict(), indent=2, sort_keys=True))
