"""Calibration primitives for pytestlab_sim digital-twin workflows."""

from __future__ import annotations

import random
from pathlib import Path

from .dataset import CalibrationDataset
from .dataset import CalibrationRow
from .dataset import split_hardware_dataset
from .datasets import MeasurementRow
from .fit import FitResult as DatasetFitResult
from .fit import fit_parameters as _fit_dataset_parameters
from .fit import scipy_fit_parameters
from .fitter import FitResult as SpecFitResult
from .fitter import fit_parameters as _fit_spec_parameters
from .metrics import MetricResult
from .metrics import classify_transition
from .metrics import compare_scalar
from .metrics import gain_db_error
from .metrics import mae
from .metrics import percent_error
from .metrics import phase_deg_error
from .metrics import rmse
from .metrics import summarize_by_split
from .metrics import transition_accuracy
from .metrics import transition_boundaries
from .metrics import transition_boundary_error
from .metrics import transition_graph
from .metrics import two_transistor_validation_metrics
from .package import TwinPackage as DirectoryTwinPackage
from .package import save_twin_package as _save_directory_twin_package
from .parameters import ParameterDeclaration
from .parameters import ParameterSet
from .parameters import netlist_hash
from .parameters import render_param_block
from .report import HardwareValidationStatus
from .report import ValidationReport
from .report import ValidationResolution
from .report import ValidationStatus
from .report import build_validation_report
from .report import canonical_json_bytes
from .report import normalize_validation_report_v2
from .report import report_from_fit
from .report import resolve_validation_status
from .report import validation_report_hash
from .sensitivity import SensitivityResult
from .sensitivity import check_parameter_sensitivity
from .sensitivity import finite_difference_sensitivity
from .twin_package import TwinPackage as ZipTwinPackage
from .twin_package import load_twin_package
from .twin_package import save_twin_package as _save_zip_twin_package

TwinPackage = ZipTwinPackage
FitResult = DatasetFitResult


def fit_parameters(first, *args, **kwargs):
    if isinstance(first, ParameterSet):
        return _fit_dataset_parameters(first, *args, **kwargs)
    return _fit_spec_parameters(first, *args, **kwargs)


def save_twin_package(*args, **kwargs):
    if args and isinstance(args[0], ZipTwinPackage):
        return _save_zip_twin_package(*args, **kwargs)
    return _save_directory_twin_package(*args, **kwargs)


def load_dataset(path: str | Path) -> CalibrationDataset:
    p = Path(path)
    if p.suffix.lower() == ".jsonl":
        return CalibrationDataset.load_jsonl(p)
    return CalibrationDataset.load_csv(p)


def save_dataset(dataset: CalibrationDataset, path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.suffix.lower() == ".jsonl":
        dataset.save_jsonl(p)
    else:
        dataset.save_csv(p)


def split_dataset(
    dataset: CalibrationDataset,
    *,
    validation_fraction: float = 0.2,
    seed: int = 1337,
) -> tuple[CalibrationDataset, CalibrationDataset]:
    rows = tuple(dataset.rows)
    if rows and hasattr(rows[0], "inputs"):
        rng = random.Random(int(seed))
        indices = list(range(len(rows)))
        rng.shuffle(indices)
        val_count = int(round(len(indices) * validation_fraction))
        validation_idx = set(indices[:val_count])
        train = [row for index, row in enumerate(rows) if index not in validation_idx]
        validation = [row for index, row in enumerate(rows) if index in validation_idx]
        return CalibrationDataset(
            tuple(train), dict(getattr(dataset, "metadata", {}))
        ), CalibrationDataset(tuple(validation), dict(getattr(dataset, "metadata", {})))
    split = dataset.with_split(validation_fraction=validation_fraction, seed=seed)
    train = tuple(row for row in split.rows if row.split == "train")
    validation = tuple(row for row in split.rows if row.split == "validation")
    return CalibrationDataset(train, dict(split.metadata)), CalibrationDataset(
        validation, dict(split.metadata)
    )


__all__ = [
    "CalibrationDataset",
    "CalibrationRow",
    "DatasetFitResult",
    "DirectoryTwinPackage",
    "FitResult",
    "validation_report_hash",
    "resolve_validation_status",
    "normalize_validation_report_v2",
    "canonical_json_bytes",
    "ValidationResolution",
    "HardwareValidationStatus",
    "MeasurementRow",
    "MetricResult",
    "ParameterDeclaration",
    "ParameterSet",
    "SensitivityResult",
    "SpecFitResult",
    "TwinPackage",
    "ValidationReport",
    "ValidationStatus",
    "ZipTwinPackage",
    "build_validation_report",
    "check_parameter_sensitivity",
    "classify_transition",
    "compare_scalar",
    "finite_difference_sensitivity",
    "fit_parameters",
    "gain_db_error",
    "load_dataset",
    "load_twin_package",
    "mae",
    "netlist_hash",
    "percent_error",
    "phase_deg_error",
    "render_param_block",
    "report_from_fit",
    "rmse",
    "save_dataset",
    "save_twin_package",
    "scipy_fit_parameters",
    "split_dataset",
    "split_hardware_dataset",
    "summarize_by_split",
    "transition_accuracy",
    "two_transistor_validation_metrics",
    "transition_boundary_error",
    "transition_boundaries",
    "transition_graph",
]
