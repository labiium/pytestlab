from __future__ import annotations

import hashlib
import json

import pytest

from pytestlab.sim.circuit.calibration import HardwareValidationStatus
from pytestlab.sim.circuit.calibration import load_twin_package
from pytestlab.sim.circuit.calibration import resolve_validation_status
from pytestlab.sim.circuit.calibration import save_twin_package
from pytestlab.sim.circuit.calibration import validation_report_hash
from pytestlab.sim.circuit.calibration.twin_package import TwinPackage
from pytestlab.sim.circuit.parameters import ParameterSet
from pytestlab.sim.circuit.parameters import parameter_hash

_REQUIRED_METRICS = {
    "vout_mae_v": (0.02, 0.05, "<=", "V"),
    "supply_current_mae_ma": (0.03, 0.1, "<=", "mA"),
    "state_classification_accuracy": (1.0, 0.98, ">=", "ratio"),
    "transition_boundary_mae_v": (0.01, 0.05, "<=", "V"),
    "transition_boundary_max_error_v": (0.02, 0.08, "<=", "V"),
}


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _package_hashes(netlist_text: str, params: ParameterSet) -> dict[str, str]:
    provisional = TwinPackage(netlist_text=netlist_text, parameters=params)
    return {
        "base_netlist_hash": _sha256_text(netlist_text),
        "rendered_netlist_hash": _sha256_text(provisional.rendered_netlist_text()),
        "parameter_hash": parameter_hash(params),
    }


def _report_v2(
    *,
    status: str = "hardware_validated",
    hardware_validated: bool = True,
    source: str = "hardware",
    package_hashes: dict[str, str] | None = None,
    failed_metric: str | None = None,
) -> dict:
    metrics = {}
    thresholds = {}
    for name, (value, limit, comparator, units) in _REQUIRED_METRICS.items():
        passed = value <= limit if comparator == "<=" else value >= limit
        if failed_metric == name:
            passed = False
            value = limit * 2 if comparator == "<=" else limit / 2
        metrics[name] = {"value": value, "passed": passed, "units": units}
        thresholds[name] = {"limit": limit, "comparator": comparator}
    return {
        "schema_version": 2,
        "validation_status": status,
        "hardware_validated": hardware_validated,
        "source": source,
        "circuit_id": "two_transistor_amp",
        "dataset_hashes": {"train": "sha256:train", "validation": "sha256:validation"},
        "package_hashes": package_hashes
        or {
            "base_netlist_hash": "base",
            "rendered_netlist_hash": "rendered",
            "parameter_hash": "params",
        },
        "thresholds": thresholds,
        "metrics": metrics,
        "split": {
            "strategy": "sweep_id_holdout",
            "train_sweep_ids": ["sweep-train"],
            "validation_sweep_ids": ["sweep-validation"],
        },
        "environment": {"temperature_c": 23.0},
        "provenance": {"bench_yaml_hash": "bench"},
        "non_claim": None,
    }


def test_validation_report_hash_is_deterministic() -> None:
    report = _report_v2()
    shuffled = json.loads(json.dumps(report, sort_keys=True))

    assert validation_report_hash(report) == validation_report_hash(shuffled)


def test_resolve_v2_hardware_validated_report() -> None:
    report = _report_v2()
    manifest = {
        "schema_version": 2,
        "validation_status": "hardware_validated",
        "hardware_validated": True,
        "validation_report_hash": validation_report_hash(report),
    }

    resolution = resolve_validation_status(manifest, report)

    assert resolution.status is HardwareValidationStatus.HARDWARE_VALIDATED
    assert resolution.hardware_validated is True


@pytest.mark.parametrize(
    ("manifest", "report", "expected"),
    [
        ({"schema_version": 1}, {}, HardwareValidationStatus.HARDWARE_UNVALIDATED),
        (
            {"schema_version": 1, "validation_status": "synthetic_only"},
            {},
            HardwareValidationStatus.SYNTHETIC_ONLY,
        ),
        (
            {"schema_version": 1},
            {"status": "synthetic_only"},
            HardwareValidationStatus.SYNTHETIC_ONLY,
        ),
        (
            {"schema_version": 2, "validation_status": "synthetic_only"},
            {},
            HardwareValidationStatus.SYNTHETIC_ONLY,
        ),
        ({"schema_version": 2}, {}, HardwareValidationStatus.HARDWARE_UNVALIDATED),
    ],
)
def test_status_resolution_legacy_and_missing_report_matrix(manifest, report, expected) -> None:
    resolution = resolve_validation_status(manifest, report)

    assert resolution.status is expected
    assert resolution.hardware_validated is False


@pytest.mark.parametrize(
    ("manifest", "report", "match"),
    [
        (
            {
                "schema_version": 2,
                "validation_status": "hardware_validated",
                "hardware_validated": True,
            },
            {},
            "without validation_report",
        ),
        (
            {"schema_version": 2, "validation_report_hash": "bad"},
            _report_v2(),
            "validation_report_hash",
        ),
        (
            {
                "schema_version": 2,
                "validation_status": "hardware_failed",
                "hardware_validated": True,
                "validation_report_hash": "filled",
            },
            _report_v2(),
            "validation_report_hash|disagrees",
        ),
    ],
)
def test_v2_integrity_failures_hard_reject(manifest, report, match) -> None:
    if report and manifest.get("validation_report_hash") == "filled":
        manifest = dict(manifest, validation_report_hash=validation_report_hash(report))

    with pytest.raises(ValueError, match=match):
        resolve_validation_status(manifest, report)


def test_hardware_failed_is_threshold_outcome_not_integrity_failure() -> None:
    report = _report_v2(
        status="hardware_failed",
        hardware_validated=False,
        failed_metric="vout_mae_v",
    )
    manifest = {
        "schema_version": 2,
        "validation_status": "hardware_failed",
        "hardware_validated": False,
        "validation_report_hash": validation_report_hash(report),
    }

    resolution = resolve_validation_status(manifest, report)

    assert resolution.status is HardwareValidationStatus.HARDWARE_FAILED
    assert resolution.hardware_validated is False


def test_hardware_failed_with_malformed_thresholds_hard_rejects() -> None:
    report = _report_v2(
        status="hardware_failed",
        hardware_validated=False,
        failed_metric="vout_mae_v",
    )
    report["thresholds"] = {"vout_mae_v": 0.05}
    manifest = {
        "schema_version": 2,
        "validation_status": "hardware_failed",
        "hardware_validated": False,
        "validation_report_hash": validation_report_hash(report),
    }

    with pytest.raises(ValueError, match="thresholds.vout_mae_v"):
        resolve_validation_status(manifest, report)


def test_hardware_validated_requires_full_two_transistor_metrics() -> None:
    report = _report_v2()
    report["metrics"].pop("transition_boundary_max_error_v")
    manifest = {
        "schema_version": 2,
        "validation_status": "hardware_validated",
        "hardware_validated": True,
        "validation_report_hash": validation_report_hash(report),
    }

    with pytest.raises(ValueError, match="missing metrics"):
        resolve_validation_status(manifest, report)


def test_twin_package_writes_and_loads_v2_validation_summary(tmp_path) -> None:
    netlist = "R1 out 0 1k\n.end\n"
    params = ParameterSet.from_values({"gain": 2.0})
    report = _report_v2(package_hashes=_package_hashes(netlist, params))
    package = TwinPackage(
        netlist_text=netlist,
        parameters=params,
        validation_report=report,
    )
    path = tmp_path / "amp.twin"

    save_twin_package(package, path)
    manifest = json.loads((path / "manifest.json").read_text())
    loaded = load_twin_package(path)

    assert manifest["schema_version"] == 2
    assert manifest["validation_report_hash"] == validation_report_hash(report)
    assert loaded.manifest["validation_status"] == "hardware_validated"
    assert loaded.manifest["hardware_validated"] is True


def test_twin_package_rejects_v2_report_tamper(tmp_path) -> None:
    netlist = "R1 out 0 1k\n.end\n"
    params = ParameterSet.from_values({"gain": 2.0})
    report = _report_v2(package_hashes=_package_hashes(netlist, params))
    package = TwinPackage(
        netlist_text=netlist,
        parameters=params,
        validation_report=report,
    )
    path = tmp_path / "amp.twin"
    save_twin_package(package, path)
    tampered = dict(report)
    tampered["hardware_validated"] = False
    (path / "validation_report.json").write_text(json.dumps(tampered))

    with pytest.raises(ValueError, match="hardware_validated must match|validation_report_hash"):
        load_twin_package(path)


def test_hardware_validated_rejects_metric_pass_flag_contradiction() -> None:
    report = _report_v2()
    report["metrics"]["vout_mae_v"]["value"] = 999.0
    report["metrics"]["vout_mae_v"]["passed"] = True
    manifest = {
        "schema_version": 2,
        "validation_status": "hardware_validated",
        "hardware_validated": True,
        "validation_report_hash": validation_report_hash(report),
    }

    with pytest.raises(ValueError, match="passed disagrees with threshold"):
        resolve_validation_status(manifest, report)


def test_hardware_failed_rejects_metric_pass_flag_contradiction() -> None:
    report = _report_v2(
        status="hardware_failed",
        hardware_validated=False,
        failed_metric="vout_mae_v",
    )
    report["metrics"]["vout_mae_v"]["value"] = 0.01
    report["metrics"]["vout_mae_v"]["passed"] = False
    manifest = {
        "schema_version": 2,
        "validation_status": "hardware_failed",
        "hardware_validated": False,
        "validation_report_hash": validation_report_hash(report),
    }

    with pytest.raises(ValueError, match="passed disagrees with threshold"):
        resolve_validation_status(manifest, report)


def test_twin_package_round_trips_v2_report_without_non_claim(tmp_path) -> None:
    netlist = "R1 out 0 1k\n.end\n"
    params = ParameterSet.from_values({"gain": 2.0})
    report = _report_v2(package_hashes=_package_hashes(netlist, params))
    report.pop("non_claim")
    package = TwinPackage(
        netlist_text=netlist,
        parameters=params,
        validation_report=report,
    )
    path = tmp_path / "amp.twin"

    save_twin_package(package, path)
    loaded = load_twin_package(path)

    assert loaded.manifest["validation_status"] == "hardware_validated"
    assert loaded.validation_report.get("non_claim") is None


def test_twin_package_rejects_stale_transplanted_v2_report(tmp_path) -> None:
    first_netlist = "R1 out 0 1k\n.end\n"
    second_netlist = "R1 out 0 2k\n.end\n"
    params = ParameterSet.from_values({"gain": 2.0})
    report = _report_v2(package_hashes=_package_hashes(first_netlist, params))
    package = TwinPackage(
        netlist_text=second_netlist,
        parameters=params,
        validation_report=report,
    )
    path = tmp_path / "amp.twin"

    save_twin_package(package, path)

    with pytest.raises(ValueError, match="package_hashes.base_netlist_hash"):
        load_twin_package(path)
