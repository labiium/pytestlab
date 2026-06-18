"""Deterministic known-truth oscilloscope digital-twin validation."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from pytestlab.sim.circuit.bench import BenchLimits
from pytestlab.sim.circuit.bench import Scope
from pytestlab.sim.circuit.instruments.twins import ScopeTwin
from pytestlab.uncertainty.atoms import AtomRegistry
from pytestlab.uncertainty.atoms import Distribution
from pytestlab.uncertainty.atoms import Kind
from pytestlab.uncertainty.metrology import TraceabilityRef
from pytestlab.uncertainty.quantity_array import QuantityArray

DEFAULT_SCOPE_TWIN_SEED = 20_260_618
DEFAULT_SCOPE_TWIN_SAMPLES = 3_000


@dataclass(frozen=True)
class KnownTruthMetric:
    """One known-truth acceptance result for a derived waveform quantity."""

    name: str
    true_value: float
    nominal: float
    standard_uncertainty: float
    coverage_factor: float
    interval_low: float
    interval_high: float
    passed: bool
    method: str


@dataclass(frozen=True)
class ScopeTwinValidationReport:
    """Report emitted by the canonical scope twin known-truth experiment."""

    generated_utc: str
    payload_sha256: str
    waveform_sha256: str
    report_path: str
    manifest_path: str
    parameters: dict[str, float | int | str]
    metrics: list[KnownTruthMetric]

    @property
    def passed(self) -> bool:
        return all(metric.passed for metric in self.metrics)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ScopeTwinValidationError(RuntimeError):
    """Raised when a known-truth validation bundle is missing or tampered."""


def run_scope_twin_known_truth_validation(
    output_dir: str | Path,
    *,
    mc_samples: int = DEFAULT_SCOPE_TWIN_SAMPLES,
    seed: int = DEFAULT_SCOPE_TWIN_SEED,
    coverage_factor: float = 2.0,
) -> ScopeTwinValidationReport:
    """Generate a deterministic known-truth waveform validation bundle.

    The experiment feeds a mathematically-known sine wave through the circuit
    simulator's oscilloscope twin, wraps the acquired samples in a
    :class:`QuantityArray`, then proves mean/RMS/Vpp expanded intervals bracket
    the analytical truth. The output JSON records hashes of both the waveform and
    the canonical payload so the artifact can be rechecked for tampering.
    """

    if mc_samples < 1_000:
        raise ValueError("mc_samples must be at least 1000 for stable Vpp validation")
    if coverage_factor <= 0:
        raise ValueError("coverage_factor must be positive")

    parameters = {
        "seed": seed,
        "record_length": 1024,
        "sample_rate_sps": 1_000_000.0,
        "cycles": 16,
        "frequency_hz": 15_625.0,
        "amplitude_peak_v": 0.75,
        "offset_v": 0.1,
        "vertical_scale_v_per_div": 0.25,
        "vertical_offset_v": 0.0,
        "enob": 12.0,
        "bandwidth_hz": 100_000_000.0,
        "mc_samples": mc_samples,
        "coverage_factor": coverage_factor,
        "source": "pytestlab.sim.circuit.ScopeTwin.acquire",
    }
    waveform, quantity_array = _run_scope_twin_waveform(parameters)
    truth = _truth_values(parameters)
    metrics = _evaluate_metrics(
        quantity_array,
        truth,
        mc_samples=mc_samples,
        seed=seed,
        coverage_factor=coverage_factor,
    )
    waveform_sha = _sha256_array(waveform)
    payload = {
        "schema": "pytestlab.scope_twin_known_truth.v1",
        "parameters": parameters,
        "waveform_sha256": waveform_sha,
        "metrics": [asdict(metric) for metric in metrics],
        "claim": (
            "Deterministic simulator known-truth waveform reductions bracket analytical truth. "
            "This is validation evidence, not accreditation by itself."
        ),
    }
    payload_sha = _payload_hash(payload)
    payload["payload_sha256"] = payload_sha
    payload["generated_utc"] = datetime.now(UTC).isoformat()

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    report_path = out / "scope_twin_known_truth_report.json"
    manifest_path = out / "manifest.json"
    report_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    manifest = {
        "schema": "pytestlab.scope_twin_known_truth.manifest.v1",
        "generated_utc": payload["generated_utc"],
        "report": report_path.name,
        "payload_sha256": payload_sha,
        "waveform_sha256": waveform_sha,
        "passed": all(metric.passed for metric in metrics),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return ScopeTwinValidationReport(
        generated_utc=str(payload["generated_utc"]),
        payload_sha256=payload_sha,
        waveform_sha256=waveform_sha,
        report_path=str(report_path),
        manifest_path=str(manifest_path),
        parameters=parameters,
        metrics=metrics,
    )


def check_scope_twin_known_truth_validation(output_dir: str | Path) -> ScopeTwinValidationReport:
    """Verify hashes and pass/fail status for a generated validation bundle."""

    out = Path(output_dir)
    report_path = out / "scope_twin_known_truth_report.json"
    manifest_path = out / "manifest.json"
    if not report_path.is_file() or not manifest_path.is_file():
        raise ScopeTwinValidationError("scope twin validation report or manifest is missing")
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    recorded_sha = payload.get("payload_sha256")
    if not isinstance(recorded_sha, str):
        raise ScopeTwinValidationError("report missing payload_sha256")
    actual_sha = _payload_hash({k: v for k, v in payload.items() if k != "payload_sha256"})
    if actual_sha != recorded_sha:
        raise ScopeTwinValidationError(
            f"scope twin report payload hash mismatch: {actual_sha} != {recorded_sha}"
        )
    if manifest.get("payload_sha256") != recorded_sha:
        raise ScopeTwinValidationError("manifest payload_sha256 does not match report")
    if manifest.get("schema") != "pytestlab.scope_twin_known_truth.manifest.v1":
        raise ScopeTwinValidationError("manifest schema is not recognized")
    if manifest.get("report") != report_path.name:
        raise ScopeTwinValidationError(
            "manifest report does not reference the expected report file"
        )
    if manifest.get("waveform_sha256") != payload.get("waveform_sha256"):
        raise ScopeTwinValidationError("manifest waveform_sha256 does not match report")
    if manifest.get("passed") is not True:
        raise ScopeTwinValidationError("manifest passed flag is not true")
    metrics = [KnownTruthMetric(**metric) for metric in payload.get("metrics", [])]
    if not metrics or not all(metric.passed for metric in metrics):
        raise ScopeTwinValidationError("scope twin known-truth metrics did not all pass")
    return ScopeTwinValidationReport(
        generated_utc=str(payload.get("generated_utc", "")),
        payload_sha256=recorded_sha,
        waveform_sha256=str(payload.get("waveform_sha256", "")),
        report_path=str(report_path),
        manifest_path=str(manifest_path),
        parameters=dict(payload.get("parameters", {})),
        metrics=metrics,
    )


def _run_scope_twin_waveform(
    parameters: dict[str, float | int | str],
) -> tuple[np.ndarray, QuantityArray]:
    n = int(parameters["record_length"])
    sample_rate = float(parameters["sample_rate_sps"])
    frequency = float(parameters["frequency_hz"])
    amplitude = float(parameters["amplitude_peak_v"])
    offset = float(parameters["offset_v"])
    time = np.arange(n, dtype=float) / sample_rate
    true_waveform = offset + amplitude * np.sin(2.0 * math.pi * frequency * time)

    scope = Scope(
        channels=1,
        bandwidth_hz=float(parameters["bandwidth_hz"]),
        sample_rate_sps_max=sample_rate,
        enob=float(parameters["enob"]),
    )
    twin = ScopeTwin(
        int(parameters["seed"]),
        scope,
        BenchLimits(soft={"max_scope_record_points": float(n)}),
    )
    twin.set_state(
        sample_rate=sample_rate,
        record_length=n,
        vertical_scale_v=float(parameters["vertical_scale_v_per_div"]),
        vertical_offset_v=float(parameters["vertical_offset_v"]),
        enob=float(parameters["enob"]),
        bandwidth_hz=float(parameters["bandwidth_hz"]),
    )
    result = twin.acquire(true_waveform)
    acquired = np.asarray(result.values["v"], dtype=float)

    full_scale = float(parameters["vertical_scale_v_per_div"]) * 8.0
    lsb = full_scale / (2 ** int(round(float(parameters["enob"]))))
    reg = AtomRegistry()
    offset_atom = reg.mint(
        nominal=0.0,
        std_uncertainty=0.002,
        label="scope_twin_offset_bound",
        unit="V",
        distribution=Distribution.STANDARD,
        kind=Kind.TYPE_B,
        source="digital_twin_known_truth",
        traceability=TraceabilityRef(source="assumed"),
        key="scope_twin_offset_bound",
    )
    gain_atom = reg.mint(
        nominal=0.0,
        std_uncertainty=0.003,
        label="scope_twin_gain_bound",
        unit="1",
        distribution=Distribution.STANDARD,
        kind=Kind.TYPE_B,
        source="digital_twin_known_truth",
        traceability=TraceabilityRef(source="assumed"),
        key="scope_twin_gain_bound",
    )
    quantity_array = QuantityArray(
        acquired,
        unit="V",
        diagonal_variance=np.full_like(acquired, (lsb / math.sqrt(12.0)) ** 2),
        atom_sensitivities={offset_atom.uid: np.ones_like(acquired), gain_atom.uid: acquired},
        registry=reg,
    )
    return acquired, quantity_array


def _truth_values(parameters: dict[str, float | int | str]) -> dict[str, float]:
    amplitude = float(parameters["amplitude_peak_v"])
    offset = float(parameters["offset_v"])
    return {
        "mean": offset,
        "rms": math.sqrt(offset**2 + amplitude**2 / 2.0),
        "peak_to_peak": 2.0 * amplitude,
    }


def _evaluate_metrics(
    quantity_array: QuantityArray,
    truth: dict[str, float],
    *,
    mc_samples: int,
    seed: int,
    coverage_factor: float,
) -> list[KnownTruthMetric]:
    quantities = {
        "mean": quantity_array.mean(dof_method="validated_independent"),
        "rms": quantity_array.rms(dof_method="lag1_autocorrelation"),
        "peak_to_peak": quantity_array.peak_to_peak_monte_carlo(samples=mc_samples, seed=seed),
    }
    metrics = []
    for name, quantity in quantities.items():
        low = quantity.nominal - coverage_factor * quantity.u
        high = quantity.nominal + coverage_factor * quantity.u
        true_value = truth[name]
        metrics.append(
            KnownTruthMetric(
                name=name,
                true_value=true_value,
                nominal=quantity.nominal,
                standard_uncertainty=quantity.u,
                coverage_factor=coverage_factor,
                interval_low=low,
                interval_high=high,
                passed=low <= true_value <= high,
                method=getattr(quantity.measurement_model, "method", "unknown"),
            )
        )
    return metrics


def _sha256_array(values: np.ndarray) -> str:
    arr = np.asarray(values, dtype="<f8")
    return hashlib.sha256(arr.tobytes()).hexdigest()


def _payload_hash(payload: dict[str, Any]) -> str:
    clean = {
        key: value
        for key, value in payload.items()
        if key not in {"generated_utc", "payload_sha256"}
    }
    raw = json.dumps(clean, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
