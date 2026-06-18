from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from enum import Enum
from pathlib import Path
from typing import Any

from ..parameters import parameter_hash
from .dataset import CalibrationDataset
from .fit import FitResult
from .metrics import MetricResult

_NOT_VALIDATED = "Not validated outside the declared operating region."

_REQUIRED_PACKAGE_HASH_KEYS = {
    "base_netlist_hash",
    "rendered_netlist_hash",
    "parameter_hash",
}
_REQUIRED_DATASET_HASH_KEYS = {"train", "validation"}
_REQUIRED_TWO_TRANSISTOR_METRICS = {
    "vout_mae_v",
    "supply_current_mae_ma",
    "state_classification_accuracy",
    "transition_boundary_mae_v",
    "transition_boundary_max_error_v",
}


class ValidationStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    SYNTHETIC_ONLY = "synthetic_only"
    WARNING = "warning"


@dataclass(frozen=True)
class ValidationReport:
    dataset_hash: str = ""
    split_counts: dict[str, int] = field(default_factory=dict)
    metrics: dict[str, list[MetricResult]] = field(default_factory=dict)
    parameters: dict[str, float] = field(default_factory=dict)
    passed: bool = False
    operating_region: dict[str, Any] = field(default_factory=dict)
    known_limitations: list[str] = field(default_factory=lambda: [_NOT_VALIDATED])
    provenance: dict[str, Any] = field(default_factory=dict)
    status: ValidationStatus = ValidationStatus.WARNING
    train_metrics: dict[str, float] = field(default_factory=dict)
    validation_metrics: dict[str, float] = field(default_factory=dict)

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "dataset_hash": self.dataset_hash,
            "split_counts": self.split_counts,
            "metrics": {
                split: [asdict(metric) for metric in metrics]
                for split, metrics in self.metrics.items()
            },
            "parameters": self.parameters,
            "passed": self.passed,
            "status": self.status.value,
            "train_metrics": self.train_metrics,
            "validation_metrics": self.validation_metrics,
            "operating_region": self.operating_region,
            "known_limitations": self.known_limitations,
            "provenance": self.provenance,
        }

    def write_json(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_json_dict(), indent=2, sort_keys=True) + "\n")

    def write_markdown(self, path: str | Path) -> None:
        Path(path).write_text(self.to_markdown())

    def to_markdown(self) -> str:
        status = self.status.value.upper() if self.status else ("PASS" if self.passed else "FAIL")
        lines = ["# Calibration Validation Report", "", f"Status: **{status}**", ""]
        if self.dataset_hash:
            lines += [f"Dataset hash: `{self.dataset_hash}`", ""]
        if self.split_counts:
            lines.append("## Split counts")
            for split, count in sorted(self.split_counts.items()):
                lines.append(f"- {split}: {count}")
            lines.append("")
        lines.append("## Metrics")
        for split, metrics in sorted(self.metrics.items()):
            lines.append(f"### {split}")
            for metric in metrics:
                threshold = "" if metric.threshold is None else f" (threshold {metric.threshold:g})"
                passed = (
                    "" if metric.passed is None else f" [{'PASS' if metric.passed else 'FAIL'}]"
                )
                unit = f" {metric.unit}" if metric.unit else ""
                lines.append(f"- {metric.name}: {metric.value:g}{unit}{threshold}{passed}")
        for name, group in (
            ("train", self.train_metrics),
            ("validation", self.validation_metrics),
        ):
            if group:
                lines.append(f"### {name}")
                for key, value in sorted(group.items()):
                    lines.append(f"- {key}: {value:g}")
        lines += ["", "## Parameters"]
        for name, value in sorted(self.parameters.items()):
            lines.append(f"- {name}: {value:g}")
        lines += ["", "## Known limitations"]
        for item in self.known_limitations:
            lines.append(f"- {item}")
        return "\n".join(lines) + "\n"


def build_validation_report(*args, **kwargs) -> ValidationReport:
    if args and isinstance(args[0], CalibrationDataset):
        dataset = args[0]
        metrics = kwargs["metrics"]
        metric_statuses = [metric.passed for split in metrics.values() for metric in split]
        passed = all(status is not False for status in metric_statuses)
        return ValidationReport(
            dataset_hash=dataset.content_hash(),
            split_counts=dataset.split_counts(),
            metrics=metrics,
            parameters=dict(kwargs["parameters"]),
            passed=passed,
            status=ValidationStatus.PASS if passed else ValidationStatus.FAIL,
            operating_region=dict(kwargs["operating_region"]),
            known_limitations=kwargs.get("known_limitations") or [_NOT_VALIDATED],
            provenance=kwargs.get("provenance") or {},
        )

    parameters = dict(kwargs.get("parameters", {}))
    provenance = {
        "hardware_validated": not bool(kwargs.get("synthetic_only", False)),
        "base_netlist_hash": kwargs.get("base_netlist_hash"),
        "rendered_netlist_hash": kwargs.get("rendered_netlist_hash"),
        "parameter_hash": parameter_hash(parameters)
        if parameters
        else hashlib.sha256(b"{}").hexdigest(),
    }
    return ValidationReport(
        parameters=parameters,
        passed=not bool(kwargs.get("synthetic_only", False)),
        status=ValidationStatus.SYNTHETIC_ONLY
        if kwargs.get("synthetic_only", False)
        else ValidationStatus.PASS,
        train_metrics=dict(kwargs.get("train_metrics", {})),
        validation_metrics=dict(kwargs.get("validation_metrics", {})),
        known_limitations=[_NOT_VALIDATED],
        provenance=provenance,
    )


def report_from_fit(
    dataset: CalibrationDataset,
    fit_result: FitResult,
    *,
    operating_region: dict[str, Any],
    provenance: dict[str, Any] | None = None,
) -> ValidationReport:
    train = MetricResult(
        "loss_reduction",
        fit_result.initial_loss - fit_result.final_loss,
        passed=fit_result.final_loss < fit_result.initial_loss,
    )
    return build_validation_report(
        dataset,
        metrics={"train": [train]},
        parameters=fit_result.fitted_values,
        operating_region=operating_region,
        provenance=provenance,
    )


class HardwareValidationStatus(str, Enum):
    SYNTHETIC_ONLY = "synthetic_only"
    HARDWARE_UNVALIDATED = "hardware_unvalidated"
    HARDWARE_VALIDATED = "hardware_validated"
    HARDWARE_FAILED = "hardware_failed"


@dataclass(frozen=True)
class ValidationResolution:
    status: HardwareValidationStatus
    hardware_validated: bool
    schema_version: int
    legacy: bool = False
    reason: str = ""


def canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    """Return deterministic JSON bytes used for report hashing."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def validation_report_hash(report: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(report)).hexdigest()


def canonicalize_validation_report_v2(report: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(report)
    normalized.setdefault("non_claim", None)
    return normalized


def normalize_validation_report_v2(report: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize the canonical hardware-validation report v2 shape."""
    required = {
        "schema_version",
        "validation_status",
        "hardware_validated",
        "source",
        "circuit_id",
        "dataset_hashes",
        "package_hashes",
        "thresholds",
        "metrics",
        "split",
        "environment",
        "provenance",
    }
    missing = sorted(required.difference(report))
    if missing:
        raise ValueError(f"validation_report.json v2 missing required fields: {', '.join(missing)}")
    if int(report["schema_version"]) != 2:
        raise ValueError("validation_report.json must use schema_version=2")

    status = HardwareValidationStatus(str(report["validation_status"]))
    hardware_validated = bool(report["hardware_validated"])
    if hardware_validated != (status == HardwareValidationStatus.HARDWARE_VALIDATED):
        raise ValueError("hardware_validated must match validation_status")
    source = str(report["source"])
    if source not in {"synthetic", "hardware", "mixed"}:
        raise ValueError("validation_report source must be synthetic, hardware, or mixed")
    if status == HardwareValidationStatus.HARDWARE_VALIDATED and source == "synthetic":
        raise ValueError("synthetic reports cannot be hardware_validated")

    _require_hash_mapping(
        report.get("dataset_hashes"), _REQUIRED_DATASET_HASH_KEYS, "dataset_hashes"
    )
    _require_hash_mapping(
        report.get("package_hashes"), _REQUIRED_PACKAGE_HASH_KEYS, "package_hashes"
    )

    split = report["split"]
    if not isinstance(split, dict) or split.get("strategy") != "sweep_id_holdout":
        if status in {
            HardwareValidationStatus.HARDWARE_VALIDATED,
            HardwareValidationStatus.HARDWARE_FAILED,
        }:
            raise ValueError("hardware validation requires split.strategy=sweep_id_holdout")
    train_sweeps = list(split.get("train_sweep_ids", [])) if isinstance(split, dict) else []
    validation_sweeps = (
        list(split.get("validation_sweep_ids", [])) if isinstance(split, dict) else []
    )
    if status in {
        HardwareValidationStatus.HARDWARE_VALIDATED,
        HardwareValidationStatus.HARDWARE_FAILED,
    }:
        if not train_sweeps or not validation_sweeps:
            raise ValueError(
                "hardware validation reports require train and held-out validation_sweep_ids"
            )
        if set(train_sweeps).intersection(validation_sweeps):
            raise ValueError("train_sweep_ids and validation_sweep_ids must be disjoint")

    thresholds = _validate_thresholds(report.get("thresholds"))
    metrics = _validate_metrics(report.get("metrics"))
    if status in {
        HardwareValidationStatus.HARDWARE_VALIDATED,
        HardwareValidationStatus.HARDWARE_FAILED,
    }:
        missing_thresholds = sorted(_REQUIRED_TWO_TRANSISTOR_METRICS.difference(thresholds))
        if missing_thresholds:
            raise ValueError(
                "hardware validation reports missing thresholds: " + ", ".join(missing_thresholds)
            )
        missing_metrics = sorted(_REQUIRED_TWO_TRANSISTOR_METRICS.difference(metrics))
        if missing_metrics:
            raise ValueError(
                "hardware validation reports missing metrics: " + ", ".join(missing_metrics)
            )
        passed_values = [bool(metrics[name]["passed"]) for name in _REQUIRED_TWO_TRANSISTOR_METRICS]
        if status == HardwareValidationStatus.HARDWARE_VALIDATED and not all(passed_values):
            raise ValueError("hardware_validated reports require all metrics to pass")
        for name in _REQUIRED_TWO_TRANSISTOR_METRICS:
            _verify_metric_pass_matches_threshold(name, metrics[name], thresholds[name])
        if status == HardwareValidationStatus.HARDWARE_FAILED and all(passed_values):
            raise ValueError("hardware_failed reports require at least one failed metric")

    return canonicalize_validation_report_v2(report)


def _require_hash_mapping(value: Any, required_keys: set[str], name: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"validation_report {name} must be an object")
    missing = sorted(required_keys.difference(value))
    if missing:
        raise ValueError(f"validation_report {name} missing required keys: {', '.join(missing)}")
    for key in required_keys:
        item = value.get(key)
        if not isinstance(item, str) or not item:
            raise ValueError(f"validation_report {name}.{key} must be a non-empty string")


def _validate_thresholds(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        raise ValueError("validation_report thresholds must be an object")
    for name, item in value.items():
        if not isinstance(item, dict):
            raise ValueError(f"validation_report thresholds.{name} must be an object")
        if item.get("comparator") not in {"<=", ">="}:
            raise ValueError(f"validation_report thresholds.{name}.comparator must be <= or >=")
        try:
            float(item["limit"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"validation_report thresholds.{name}.limit must be numeric") from exc
    return value


def _validate_metrics(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        raise ValueError("validation_report metrics must be an object")
    for name, item in value.items():
        if not isinstance(item, dict):
            raise ValueError(f"validation_report metrics.{name} must be an object")
        try:
            float(item["value"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"validation_report metrics.{name}.value must be numeric") from exc
        if not isinstance(item.get("passed"), bool):
            raise ValueError(f"validation_report metrics.{name}.passed must be boolean")
        if "units" in item and not isinstance(item["units"], str):
            raise ValueError(f"validation_report metrics.{name}.units must be a string")
    return value


def _verify_metric_pass_matches_threshold(
    name: str, metric: dict[str, Any], threshold: dict[str, Any]
) -> None:
    value = float(metric["value"])
    limit = float(threshold["limit"])
    comparator = str(threshold["comparator"])
    expected = value <= limit if comparator == "<=" else value >= limit
    if bool(metric["passed"]) != expected:
        raise ValueError(f"validation_report metrics.{name}.passed disagrees with threshold")


def _hash_matches(declared: Any, actual: Any) -> bool:
    declared_text = str(declared)
    actual_text = str(actual)
    return declared_text in {actual_text, f"sha256:{actual_text}"}


def _verify_report_package_hashes(
    manifest: dict[str, Any], normalized_report: dict[str, Any]
) -> None:
    report_hashes = normalized_report.get("package_hashes") or {}
    manifest_keys = {
        "base_netlist_hash": manifest.get("base_netlist_hash")
        or manifest.get("package_netlist_hash"),
        "rendered_netlist_hash": manifest.get("rendered_netlist_hash")
        or manifest.get("rendered_with_params_hash"),
        "parameter_hash": manifest.get("parameter_hash"),
    }
    for key, manifest_value in manifest_keys.items():
        if manifest_value is None:
            continue
        if not _hash_matches(report_hashes.get(key), manifest_value):
            raise ValueError(
                f"validation_report package_hashes.{key} does not match package manifest"
            )


def resolve_validation_status(
    manifest: dict[str, Any],
    validation_report: dict[str, Any] | None,
) -> ValidationResolution:
    """Resolve package hardware-validity status from manifest + report.

    The report is canonical for v2 packages. Manifest summaries are only
    discovery/display hints and contradictions fail closed.
    """
    schema_version = int(manifest.get("schema_version", 1) or 1)
    report = validation_report or {}
    manifest_status = manifest.get("validation_status")
    manifest_hardware = manifest.get("hardware_validated")

    if schema_version < 2:
        if not report:
            status = (
                HardwareValidationStatus.SYNTHETIC_ONLY
                if manifest_status == HardwareValidationStatus.SYNTHETIC_ONLY.value
                else HardwareValidationStatus.HARDWARE_UNVALIDATED
            )
        else:
            raw_status = str(report.get("validation_status") or report.get("status") or "")
            status = (
                HardwareValidationStatus.SYNTHETIC_ONLY
                if raw_status == HardwareValidationStatus.SYNTHETIC_ONLY.value
                else HardwareValidationStatus.HARDWARE_UNVALIDATED
            )
        return ValidationResolution(status, False, schema_version, legacy=True)

    if not report:
        if (
            manifest_hardware is True
            or manifest_status == HardwareValidationStatus.HARDWARE_VALIDATED.value
        ):
            raise ValueError(
                "v2 twin package claims hardware validation without validation_report.json"
            )
        if manifest_status == HardwareValidationStatus.SYNTHETIC_ONLY.value:
            return ValidationResolution(
                HardwareValidationStatus.SYNTHETIC_ONLY, False, schema_version
            )
        return ValidationResolution(
            HardwareValidationStatus.HARDWARE_UNVALIDATED, False, schema_version
        )

    normalized = normalize_validation_report_v2(report)
    _verify_report_package_hashes(manifest, normalized)
    declared_hash = manifest.get("validation_report_hash")
    if not declared_hash:
        raise ValueError("v2 twin package validation_report_hash is required")
    actual_hash = validation_report_hash(normalized)
    declared_text = str(declared_hash)
    if declared_text not in {actual_hash, f"sha256:{actual_hash}"}:
        raise ValueError("validation_report_hash does not match validation_report.json")

    report_status = HardwareValidationStatus(str(normalized["validation_status"]))
    report_hardware = bool(normalized["hardware_validated"])
    if manifest_status is not None and str(manifest_status) != report_status.value:
        raise ValueError("manifest validation_status disagrees with validation_report.json")
    if manifest_hardware is not None and bool(manifest_hardware) != report_hardware:
        raise ValueError("manifest hardware_validated disagrees with validation_report.json")
    return ValidationResolution(report_status, report_hardware, schema_version)
