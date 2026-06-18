"""Hardware replay fixtures and sim-vs-hardware parity checks."""

from __future__ import annotations

import base64
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

from pytestlab.instruments.scpi_binary import definite_length_block_to_array
from pytestlab.uncertainty.quantity_array import QuantityArray


@dataclass(frozen=True)
class WaveformMetric:
    name: str
    nominal: float
    standard_uncertainty: float
    method: str


@dataclass(frozen=True)
class ParityRow:
    name: str
    hardware_nominal: float
    expected_nominal: float
    difference: float
    combined_standard_uncertainty: float
    coverage_factor: float
    passed: bool
    layer: str
    detail: str


@dataclass(frozen=True)
class HardwareParityReport:
    generated_utc: str
    fixture_path: str
    payload_sha256: str
    parity_mode: str
    rows: list[ParityRow]
    replay_log_entries: int

    @property
    def passed(self) -> bool:
        return all(row.passed for row in self.rows)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class HardwareParityError(RuntimeError):
    """Raised when replay fixture or parity evidence is invalid."""


def decode_keysight_byte_waveform(raw_block: bytes, preamble: str) -> np.ndarray:
    """Decode BYTE-format Keysight waveform data using a 10-field preamble."""

    raw = definite_length_block_to_array(raw_block, dtype=np.uint8).astype(float)
    fields = [part.strip() for part in preamble.split(",")]
    if len(fields) < 10:
        raise HardwareParityError("waveform preamble must contain at least 10 CSV fields")
    points = int(float(fields[2]))
    yinc = float(fields[7])
    yorg = float(fields[8])
    yref = float(fields[9])
    if raw.size != points:
        raise HardwareParityError(
            f"waveform point count mismatch: raw={raw.size}, preamble={points}"
        )
    return (raw - yref) * yinc + yorg


def summarize_waveform(values: np.ndarray, *, unit: str = "V") -> dict[str, WaveformMetric]:
    """Return QuantityArray-derived metrics for a replayed hardware waveform."""

    values = np.asarray(values, dtype=float)
    if values.ndim != 1 or values.size < 2:
        raise HardwareParityError(
            "waveform values must be a one-dimensional array with >=2 samples"
        )
    # Conservative replay uncertainty floor: one least-significant observed step
    # or a tiny scale-relative floor for flat captures.
    diffs = np.diff(np.unique(np.round(values, decimals=12)))
    step = float(np.min(diffs[diffs > 0])) if np.any(diffs > 0) else max(np.ptp(values), 1.0) * 1e-6
    qa = QuantityArray.from_samples(values, unit=unit, independent_std=step / math.sqrt(12.0))
    mean = qa.mean(dof_method="validated_independent")
    rms = qa.rms(dof_method="lag1_autocorrelation")
    if values.size <= 4096:
        vpp = qa.peak_to_peak_monte_carlo(samples=3000, seed=20_260_618)
    else:
        # Large real hardware captures are replayed frequently in CI; avoid a
        # samples × points allocation while still preserving a conservative,
        # explicitly non-report-grade Vpp method marker.
        vpp = qa.peak_to_peak()
    return {
        "mean": WaveformMetric("mean", mean.nominal, mean.u, _method_name(mean)),
        "rms": WaveformMetric("rms", rms.nominal, rms.u, _method_name(rms)),
        "peak_to_peak": WaveformMetric(
            "peak_to_peak",
            vpp.nominal,
            vpp.u,
            _method_name(vpp),
        ),
    }


def build_replay_fixture(
    *,
    model: str,
    idn: str,
    preamble: str,
    raw_block: bytes,
    sample_rate: str | None = None,
    source: str = "hardware_capture",
) -> dict[str, Any]:
    """Build a portable replay fixture from a real or synthetic scope capture."""

    values = decode_keysight_byte_waveform(raw_block, preamble)
    metrics = summarize_waveform(values)
    raw_sha = hashlib.sha256(raw_block).hexdigest()
    fixture: dict[str, Any] = {
        "schema": "pytestlab.hardware_replay_fixture.v1",
        "model": model,
        "source": source,
        "generated_utc": datetime.now(UTC).isoformat(),
        "waveform_sha256": raw_sha,
        "point_count": int(values.size),
        "log": [
            {"type": "query", "command": "*IDN?", "response": _redact_idn(idn)},
            {"type": "query", "command": ":SYSTem:ERRor?", "response": '+0,"No error"'},
            {
                "type": "query",
                "command": ":ACQuire:SRATe:ANALog?",
                "response": sample_rate or _sample_rate_from_preamble(preamble),
            },
            {"type": "query", "command": ":WAVeform:PREamble?", "response": preamble},
            {
                "type": "query_raw",
                "command": ":WAVeform:DATA?",
                "response_encoding": "base64",
                "response_base64": base64.b64encode(raw_block).decode("ascii"),
                "response_sha256": raw_sha,
            },
        ],
        "metrics": {name: asdict(metric) for name, metric in metrics.items()},
        "expected": {name: asdict(metric) for name, metric in metrics.items()},
        "classification": {
            "parity_mode": "fixture_integrity",
            "expected_source": "self_consistency_replay_fixture",
            "default_failure_layer": "replay_or_analysis",
            "stimulus_known": False,
            "notes": [
                "Expected values default to replay self-consistency; this is fixture integrity, not independent hardware-vs-truth parity.",
                "Set classification.parity_mode='independent_parity' only when expected values come from a pinned simulator/known-truth source.",
                "Raw binary is base64 encoded for deterministic non-hardware CI replay.",
            ],
        },
    }
    fixture["payload_sha256"] = _fixture_hash(fixture)
    return fixture


def write_replay_fixture(path: str | Path, fixture: dict[str, Any]) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(fixture, indent=2, sort_keys=True), encoding="utf-8")
    return out


def load_replay_fixture(path: str | Path) -> dict[str, Any]:
    fixture = json.loads(Path(path).read_text(encoding="utf-8"))
    recorded = fixture.get("payload_sha256")
    if not isinstance(recorded, str):
        raise HardwareParityError("fixture missing payload_sha256")
    actual = _fixture_hash(fixture)
    if actual != recorded:
        raise HardwareParityError(f"fixture payload hash mismatch: {actual} != {recorded}")
    return fixture


def replay_fixture_metrics(fixture: dict[str, Any]) -> dict[str, WaveformMetric]:
    log = fixture.get("log")
    if not isinstance(log, list):
        raise HardwareParityError("fixture log must be a list")
    preamble = _find_response(log, ":WAVeform:PREamble?")
    raw_block = _find_raw_response(log, ":WAVeform:DATA?")
    values = decode_keysight_byte_waveform(raw_block, preamble)
    return summarize_waveform(values)


def compare_replay_to_expected(
    fixture: dict[str, Any], *, coverage_factor: float = 2.0
) -> list[ParityRow]:
    """Compare replay-derived metrics to expected/simulator values in a fixture."""

    if coverage_factor <= 0:
        raise ValueError("coverage_factor must be positive")
    hardware = replay_fixture_metrics(fixture)
    expected_raw = fixture.get("expected")
    if not isinstance(expected_raw, dict):
        raise HardwareParityError("fixture missing expected metrics")
    classification = fixture.get("classification", {})
    parity_mode = (
        str(classification.get("parity_mode", "fixture_integrity"))
        if isinstance(classification, dict)
        else "fixture_integrity"
    )
    rows: list[ParityRow] = []
    for name, hw_metric in hardware.items():
        expected_metric = expected_raw.get(name)
        if not isinstance(expected_metric, dict):
            rows.append(
                ParityRow(
                    name=name,
                    hardware_nominal=hw_metric.nominal,
                    expected_nominal=math.nan,
                    difference=math.nan,
                    combined_standard_uncertainty=math.nan,
                    coverage_factor=coverage_factor,
                    passed=False,
                    layer="fixture",
                    detail="expected metric missing",
                )
            )
            continue
        expected_nominal = float(expected_metric["nominal"])
        expected_u = float(expected_metric.get("standard_uncertainty", 0.0))
        combined_u = math.hypot(hw_metric.standard_uncertainty, expected_u)
        diff = hw_metric.nominal - expected_nominal
        passed = abs(diff) <= coverage_factor * combined_u
        rows.append(
            ParityRow(
                name=name,
                hardware_nominal=hw_metric.nominal,
                expected_nominal=expected_nominal,
                difference=diff,
                combined_standard_uncertainty=combined_u,
                coverage_factor=coverage_factor,
                passed=passed,
                layer="analysis" if passed else "sim_vs_hardware",
                detail=(
                    f"within combined uncertainty; mode={parity_mode}; method={hw_metric.method}"
                    if passed
                    else (
                        "outside combined uncertainty; inspect stimulus, simulator, "
                        f"and decode layers; mode={parity_mode}; method={hw_metric.method}"
                    )
                ),
            )
        )
    return rows


def write_hardware_parity_report(
    fixture_path: str | Path,
    output_dir: str | Path,
    *,
    coverage_factor: float = 2.0,
) -> HardwareParityReport:
    fixture = load_replay_fixture(fixture_path)
    rows = compare_replay_to_expected(fixture, coverage_factor=coverage_factor)
    classification = fixture.get("classification", {})
    parity_mode = (
        str(classification.get("parity_mode", "fixture_integrity"))
        if isinstance(classification, dict)
        else "fixture_integrity"
    )
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "pytestlab.hardware_parity_report.v1",
        "generated_utc": datetime.now(UTC).isoformat(),
        "fixture_path": str(fixture_path),
        "parity_mode": parity_mode,
        "fixture_payload_sha256": fixture["payload_sha256"],
        "rows": [asdict(row) for row in rows],
        "passed": all(row.passed for row in rows),
    }
    payload_sha = _payload_hash(payload)
    payload["payload_sha256"] = payload_sha
    report_path = out / "hardware_parity_report.json"
    report_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return HardwareParityReport(
        generated_utc=str(payload["generated_utc"]),
        fixture_path=str(fixture_path),
        payload_sha256=payload_sha,
        parity_mode=parity_mode,
        rows=rows,
        replay_log_entries=len(fixture.get("log", [])),
    )


def _find_response(log: list[dict[str, Any]], command: str) -> str:
    for entry in log:
        if entry.get("type") == "query" and entry.get("command") == command:
            response = entry.get("response")
            if isinstance(response, str):
                return response
    raise HardwareParityError(f"fixture missing query response for {command}")


def _find_raw_response(log: list[dict[str, Any]], command: str) -> bytes:
    for entry in log:
        if entry.get("type") == "query_raw" and entry.get("command") == command:
            if entry.get("response_encoding") == "base64":
                encoded = entry.get("response_base64")
                if not isinstance(encoded, str):
                    raise HardwareParityError("base64 raw response must be a string")
                raw = base64.b64decode(encoded.encode("ascii"), validate=True)
                expected_sha = entry.get("response_sha256")
                if (
                    isinstance(expected_sha, str)
                    and hashlib.sha256(raw).hexdigest() != expected_sha
                ):
                    raise HardwareParityError("raw response hash mismatch")
                return raw
            response = entry.get("response")
            if isinstance(response, str):
                return response.encode("utf-8")
    raise HardwareParityError(f"fixture missing raw response for {command}")


def _sample_rate_from_preamble(preamble: str) -> str:
    fields = [part.strip() for part in preamble.split(",")]
    if len(fields) < 5:
        return ""
    xinc = float(fields[4])
    return f"{1.0 / xinc:.12g}" if xinc > 0 else ""


def _redact_idn(idn: str) -> str:
    parts = idn.strip().split(",")
    if len(parts) >= 4:
        parts[2] = "<redacted>"
        return ",".join(parts)
    return idn.strip()


def _method_name(quantity: Any) -> str:
    model = getattr(quantity, "measurement_model", None)
    method = getattr(model, "method", None)
    return str(method or "unknown")


def _fixture_hash(fixture: dict[str, Any]) -> str:
    clean = {k: v for k, v in fixture.items() if k not in {"generated_utc", "payload_sha256"}}
    return _payload_hash(clean)


def _payload_hash(payload: dict[str, Any]) -> str:
    clean = {key: value for key, value in payload.items() if key not in {"generated_utc"}}
    raw = json.dumps(clean, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
