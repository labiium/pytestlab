from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Iterable
from collections.abc import Iterator
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Any

_LONG_REQUIRED = {"observable", "measured_value", "measured_unit"}
_WIDE_OBSERVABLES = {
    "vout_v": ("vout", "V"),
    "vin_v": ("vin", "V"),
    "vcc_v": ("vcc", "V"),
    "vbias_v": ("vbias", "V"),
    "icc_ma": ("icc", "mA"),
    "gain_db": ("gain", "dB"),
    "phase_deg": ("phase", "deg"),
    "transition_state": ("transition_state", "state"),
}


@dataclass(frozen=True)
class CalibrationRow:
    observable: str
    measured_value: float | str
    measured_unit: str
    experiment_id: str = "default"
    sweep_id: str | None = None
    split: str = "train"
    analysis: str = "op"
    temperature_c: float | None = None
    vcc_v: float | None = None
    vbias_v: float | None = None
    vin_v: float | None = None
    freq_hz: float | None = None
    time_s: float | None = None
    uncertainty: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.observable:
            raise ValueError("observable is required")
        if not self.measured_unit:
            raise ValueError("measured_unit is required")
        if self.measured_value is None:  # type: ignore[comparison-overlap]
            raise ValueError("measured_value is required")
        if self.split not in {"train", "validation", "test"}:
            raise ValueError("split must be train, validation, or test")

    def stable_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["metadata"] = dict(sorted(self.metadata.items()))
        return payload


@dataclass(frozen=True)
class CalibrationDataset:
    rows: tuple[CalibrationRow, ...]
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.rows:
            raise ValueError("calibration dataset must contain at least one row")

    def __iter__(self) -> Iterator[CalibrationRow]:
        return iter(self.rows)

    def __len__(self) -> int:
        return len(self.rows)

    @classmethod
    def from_rows(
        cls, rows: Iterable[CalibrationRow], *, metadata: dict[str, Any] | None = None
    ) -> CalibrationDataset:
        return cls(tuple(rows), metadata or {})

    @classmethod
    def load_csv(
        cls, path: str | Path, *, wide: bool | None = None
    ) -> CalibrationDataset:
        path = Path(path)
        with path.open(newline="") as f:
            reader = csv.DictReader(f)
            fieldnames = set(reader.fieldnames or [])
            rows = list(reader)
        if wide is None:
            wide = not _LONG_REQUIRED.issubset(fieldnames)
        parsed = _parse_wide_rows(rows) if wide else _parse_long_rows(rows)
        return cls.from_rows(
            parsed, metadata={"source": str(path), "format": "wide" if wide else "long"}
        )

    @classmethod
    def load_jsonl(cls, path: str | Path) -> CalibrationDataset:
        path = Path(path)
        rows = []
        with path.open() as f:
            for lineno, line in enumerate(f, start=1):
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                    rows.append(_row_from_mapping(payload))
                except Exception as exc:  # pragma: no cover - defensive context
                    raise ValueError(
                        f"invalid calibration JSONL row {lineno}: {exc}"
                    ) from exc
        return cls.from_rows(rows, metadata={"source": str(path), "format": "jsonl"})

    def save_csv(self, path: str | Path) -> None:
        path = Path(path)
        fields = list(CalibrationRow.__dataclass_fields__)
        with path.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for row in self.rows:
                payload = asdict(row)
                payload["metadata"] = json.dumps(payload["metadata"], sort_keys=True)
                writer.writerow(payload)

    def save_jsonl(self, path: str | Path) -> None:
        path = Path(path)
        with path.open("w") as f:
            for row in self.rows:
                f.write(json.dumps(row.stable_payload(), sort_keys=True) + "\n")

    def with_split(
        self,
        *,
        validation_fraction: float = 0.2,
        seed: int = 1337,
        key: str = "experiment_id",
    ) -> CalibrationDataset:
        if not 0.0 < validation_fraction < 1.0:
            raise ValueError("validation_fraction must be between 0 and 1")
        groups = sorted({str(getattr(row, key)) for row in self.rows})
        scored = []
        for group in groups:
            digest = hashlib.sha256(f"{seed}:{group}".encode()).hexdigest()
            scored.append((int(digest[:16], 16), group))
        scored.sort()
        validation_count = max(1, round(len(groups) * validation_fraction))
        validation = {group for _, group in scored[:validation_count]}
        rows = []
        for row in self.rows:
            payload = asdict(row)
            payload["split"] = (
                "validation" if str(getattr(row, key)) in validation else "train"
            )
            rows.append(CalibrationRow(**payload))
        return CalibrationDataset(tuple(rows), dict(self.metadata))

    def require_sweep_ids(self) -> None:
        missing = [row.experiment_id for row in self.rows if not row.sweep_id]
        if missing:
            raise ValueError(
                "hardware validation requires sweep_id for every row; "
                f"missing rows include: {', '.join(missing[:5])}"
            )

    def with_sweep_holdout(
        self,
        *,
        validation_fraction: float = 0.2,
        seed: int = 1337,
    ) -> CalibrationDataset:
        """Split hardware validation data by sweep_id, never by row."""
        self.require_sweep_ids()
        split = self.with_split(
            validation_fraction=validation_fraction,
            seed=seed,
            key="sweep_id",
        )
        metadata = dict(split.metadata)
        metadata.update(
            {
                "split_strategy": "sweep_id_holdout",
                "split_seed": int(seed),
                "validation_fraction": float(validation_fraction),
            }
        )
        return CalibrationDataset(split.rows, metadata)

    def sweep_ids_by_split(self) -> dict[str, list[str]]:
        out: dict[str, set[str]] = {}
        for row in self.rows:
            if row.sweep_id:
                out.setdefault(row.split, set()).add(row.sweep_id)
        return {split: sorted(values) for split, values in sorted(out.items())}

    def split_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in self.rows:
            counts[row.split] = counts.get(row.split, 0) + 1
        return counts

    def content_hash(self) -> str:
        payload = [row.stable_payload() for row in self.rows]
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(raw.encode()).hexdigest()


def _parse_long_rows(rows: list[dict[str, str]]) -> list[CalibrationRow]:
    parsed = []
    for index, raw in enumerate(rows, start=1):
        missing = [name for name in sorted(_LONG_REQUIRED) if not raw.get(name)]
        if missing:
            raise ValueError(
                f"row {index} missing required fields: {', '.join(missing)}"
            )
        parsed.append(_row_from_mapping(raw))
    return parsed


def _parse_wide_rows(rows: list[dict[str, str]]) -> list[CalibrationRow]:
    parsed: list[CalibrationRow] = []
    for index, raw in enumerate(rows, start=1):
        base = {
            "experiment_id": raw.get("experiment")
            or raw.get("experiment_id")
            or f"row-{index}",
            "sweep_id": raw.get("sweep_id") or raw.get("sweep") or None,
            "split": raw.get("split") or "train",
            "analysis": raw.get("analysis") or "op",
            "temperature_c": _optional_float(
                raw.get("temp_c") or raw.get("temperature_c")
            ),
            "vcc_v": _optional_float(raw.get("vcc_v")),
            "vbias_v": _optional_float(raw.get("vbias_v")),
            "vin_v": _optional_float(raw.get("vin_v")),
            "freq_hz": _optional_float(raw.get("freq_hz")),
            "time_s": _optional_float(raw.get("time_s")),
            "uncertainty": _optional_float(raw.get("uncertainty")),
        }
        for column, (observable, unit) in _WIDE_OBSERVABLES.items():
            value = raw.get(column)
            if value in (None, ""):
                continue
            measured: float | str = (
                value if column == "transition_state" else float(value)
            )
            parsed.append(CalibrationRow(observable, measured, unit, **base))
    if not parsed:
        raise ValueError(
            "wide calibration CSV did not contain recognized observable columns"
        )
    return parsed


def _row_from_mapping(raw: dict[str, Any]) -> CalibrationRow:
    metadata = raw.get("metadata") or {}
    if isinstance(metadata, str):
        metadata = json.loads(metadata) if metadata else {}
    raw_measured = raw.get("measured_value")
    if raw_measured is None:
        raise ValueError("measured_value is required")
    measured: float | str
    try:
        measured = float(raw_measured)
    except (TypeError, ValueError):
        measured = str(raw_measured)
    return CalibrationRow(
        observable=str(raw.get("observable") or ""),
        measured_value=measured,
        measured_unit=str(raw.get("measured_unit") or ""),
        experiment_id=str(raw.get("experiment_id") or "default"),
        sweep_id=str(raw.get("sweep_id"))
        if raw.get("sweep_id") not in (None, "")
        else None,
        split=str(raw.get("split") or "train"),
        analysis=str(raw.get("analysis") or "op"),
        temperature_c=_optional_float(raw.get("temperature_c")),
        vcc_v=_optional_float(raw.get("vcc_v")),
        vbias_v=_optional_float(raw.get("vbias_v")),
        vin_v=_optional_float(raw.get("vin_v")),
        freq_hz=_optional_float(raw.get("freq_hz")),
        time_s=_optional_float(raw.get("time_s")),
        uncertainty=_optional_float(raw.get("uncertainty")),
        metadata=metadata,
    )


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def split_hardware_dataset(
    dataset: CalibrationDataset,
    *,
    validation_fraction: float = 0.2,
    seed: int = 1337,
) -> tuple[CalibrationDataset, CalibrationDataset]:
    """Return train/validation datasets split by sweep_id for hardware validation."""
    split = dataset.with_sweep_holdout(
        validation_fraction=validation_fraction,
        seed=seed,
    )
    train = tuple(row for row in split.rows if row.split == "train")
    validation = tuple(row for row in split.rows if row.split == "validation")
    metadata = dict(split.metadata)
    return CalibrationDataset(train, metadata), CalibrationDataset(validation, metadata)
