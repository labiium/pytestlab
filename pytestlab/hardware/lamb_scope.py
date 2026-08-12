"""Skip-safe LAMB oscilloscope verification helpers.

The checks in this module are deliberately conservative: normal operation only
uses read-only SCPI queries, records metadata instead of payload data, and keeps
binary waveform transfer behind an explicit opt-in flag.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import yaml

from pytestlab.config.loader import resolve_profile_key_to_path
from pytestlab.instruments.backends.lamb import LambBackend
from pytestlab.instruments.scpi_engine import SCPIEngine

DEFAULT_LAMB_SCOPE_URL = "http://lamb-server:8000"
# Keep these explicit because this is the lab acceptance rig for the
# oscilloscope-heavy scientific validation lane. The serials remain server-side;
# model auto-connect avoids committing VISA addresses or serial numbers into
# tests/artifacts.
REQUIRED_READONLY_ALIASES = (
    "identify",
    "get_error",
    "acquire_sample_rate",
    "acquire_points",
    "wave_preamble",
    "wave_data",
)


@dataclass(frozen=True)
class LambScopeSpec:
    """Expected oscilloscope on the remote LAMB acceptance rig."""

    model: str
    profile: str


DEFAULT_LAMB_SCOPE_SPECS: tuple[LambScopeSpec, ...] = (
    LambScopeSpec(model="MXR404A", profile="keysight/MXR404A"),
    LambScopeSpec(model="HD304MSO", profile="keysight/HD304MSO"),
)


@dataclass(frozen=True)
class LambScopeRow:
    """One verification observation suitable for JSON evidence."""

    model: str
    check: str
    status: str
    detail: str
    command: str | None = None
    response_len: int | None = None
    response_sha256: str | None = None
    response_preview: str | None = None


@dataclass(frozen=True)
class LambScopeReport:
    """Complete skip-safe LAMB oscilloscope verification report."""

    generated_utc: str
    lamb_url: str
    capture_waveform: bool
    strict: bool
    active_resources: list[str]
    inactive_resources: list[str]
    rows: list[LambScopeRow]
    waveform_reductions: list[dict[str, Any]]
    artifact_path: str | None = None

    @property
    def failures(self) -> list[LambScopeRow]:
        return [row for row in self.rows if row.status == "fail"]

    @property
    def passes(self) -> list[LambScopeRow]:
        return [row for row in self.rows if row.status == "pass"]

    @property
    def skips(self) -> list[LambScopeRow]:
        return [row for row in self.rows if row.status == "skip"]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


BackendFactory = Callable[..., LambBackend]


def fetch_lamb_resources(url: str, *, timeout_ms: int = 5000) -> tuple[list[str], list[str]]:
    """Return active/inactive resource labels from a LAMB server."""

    if timeout_ms <= 0:
        raise ValueError("timeout_ms must be positive")
    base_url = url.rstrip("/")
    with httpx.Client(timeout=timeout_ms / 1000.0) as client:
        response = client.get(f"{base_url}/list_resources")
        response.raise_for_status()
        payload = response.json()
    active = payload.get("active", [])
    inactive = payload.get("inactive", [])
    return _string_list(active), _string_list(inactive)


def validate_scope_profile(profile: str) -> list[LambScopeRow]:
    """Validate that a scope profile can build the read-only acceptance aliases."""

    rows: list[LambScopeRow] = []
    profile_path = _resolve_profile(profile)
    model = profile_path.stem
    with profile_path.open(encoding="utf-8") as fh:
        profile_data = yaml.safe_load(fh) or {}
    scpi_section = profile_data.get("scpi")
    if not isinstance(scpi_section, dict):
        return [
            LambScopeRow(
                model=model,
                check="profile_readonly_scpi",
                status="fail",
                detail="profile has no scpi mapping for read-only LAMB validation",
            )
        ]

    engine = SCPIEngine(scpi_section)
    for alias in REQUIRED_READONLY_ALIASES:
        try:
            command = _build_alias(engine, alias)[0]
        except Exception as exc:
            rows.append(
                LambScopeRow(
                    model=model,
                    check=f"profile_alias:{alias}",
                    status="fail",
                    detail=str(exc),
                )
            )
        else:
            status = "pass" if command.strip().endswith("?") else "fail"
            detail = (
                "query alias builds read-only SCPI"
                if status == "pass"
                else "alias is not read-only"
            )
            rows.append(
                LambScopeRow(
                    model=model,
                    check=f"profile_alias:{alias}",
                    status=status,
                    detail=detail,
                    command=command,
                )
            )
    return rows


def run_lamb_scope_checks(
    *,
    url: str | None = None,
    specs: tuple[LambScopeSpec, ...] = DEFAULT_LAMB_SCOPE_SPECS,
    timeout_ms: int = 5000,
    capture_waveform: bool = False,
    strict: bool = True,
    output_dir: str | Path | None = None,
    backend_factory: BackendFactory = LambBackend,
) -> LambScopeReport:
    """Run skip-safe oscilloscope checks against the remote LAMB acceptance rig.

    Parameters
    ----------
    capture_waveform:
        When false, binary ``query_raw`` transfer is recorded as an explicit
        skip.  When true, ``wave_data`` is fetched via ``query_raw`` and only
        length/hash metadata is retained.
    strict:
        When true, expected active resources and failed I/O checks are failures.
        When false, missing/unresponsive instruments are represented as skips so
        opt-in pytest runs can document lab state without destabilising local CI.
    """

    resolved_url = _resolve_lamb_url(url)
    rows: list[LambScopeRow] = []
    reductions: list[dict[str, Any]] = []
    active: list[str] = []
    inactive: list[str] = []
    try:
        active, inactive = fetch_lamb_resources(resolved_url, timeout_ms=timeout_ms)
    except Exception as exc:
        rows.append(
            LambScopeRow(
                model="LAMB",
                check="active_resource_preflight",
                status="fail" if strict else "skip",
                detail=f"could not list LAMB resources: {exc}",
            )
        )

    for spec in specs:
        rows.extend(validate_scope_profile(spec.profile))
        model_active = _contains_model(active, spec.model)
        rows.append(
            LambScopeRow(
                model=spec.model,
                check="active_resource_preflight",
                status="pass" if model_active else ("fail" if strict else "skip"),
                detail=(
                    "expected model appears in LAMB active resources"
                    if model_active
                    else "expected model is not active on LAMB server"
                ),
            )
        )
        if not model_active:
            rows.extend(_skipped_io_rows(spec.model, "resource not active"))
            continue

        query_rows, query_reductions = _run_instrument_queries(
            spec,
            url=resolved_url,
            timeout_ms=timeout_ms,
            capture_waveform=capture_waveform,
            strict=strict,
            backend_factory=backend_factory,
        )
        rows.extend(query_rows)
        reductions.extend(query_reductions)

    artifact_path = _write_report(
        output_dir, resolved_url, capture_waveform, strict, active, inactive, rows, reductions
    )
    return LambScopeReport(
        generated_utc=datetime.now(UTC).isoformat(),
        lamb_url=resolved_url.rstrip("/"),
        capture_waveform=capture_waveform,
        strict=strict,
        active_resources=active,
        inactive_resources=inactive,
        rows=rows,
        waveform_reductions=reductions,
        artifact_path=str(artifact_path) if artifact_path is not None else None,
    )


def _run_instrument_queries(
    spec: LambScopeSpec,
    *,
    url: str,
    timeout_ms: int,
    capture_waveform: bool,
    strict: bool,
    backend_factory: BackendFactory,
) -> tuple[list[LambScopeRow], list[dict[str, Any]]]:
    rows: list[LambScopeRow] = []
    reductions: list[dict[str, Any]] = []
    profile_path = _resolve_profile(spec.profile)
    with profile_path.open(encoding="utf-8") as fh:
        profile_data = yaml.safe_load(fh) or {}
    scpi_section = profile_data.get("scpi") if isinstance(profile_data, dict) else None
    engine = SCPIEngine(scpi_section or {})

    try:
        backend = backend_factory(
            address=None,
            url=url,
            timeout_ms=timeout_ms,
            model_name=spec.model,
            serial_number=None,
        )
        backend.connect()
    except Exception as exc:
        return [
            LambScopeRow(
                model=spec.model,
                check="connect",
                status="fail" if strict else "skip",
                detail=f"LAMB model auto-connect failed: {exc}",
            )
        ] + _skipped_io_rows(spec.model, "connect failed"), reductions

    rows.append(_query_check(backend, engine, spec.model, "idn", "identify", spec.model, strict))
    rows.append(_query_check(backend, engine, spec.model, "error_queue", "get_error", None, strict))
    rows.append(
        _query_check(
            backend, engine, spec.model, "sample_rate", "acquire_sample_rate", None, strict
        )
    )
    preamble_row, preamble_response = _query_check_with_response(
        backend, engine, spec.model, "preamble", "wave_preamble", None, strict
    )
    rows.append(preamble_row)

    if capture_waveform:
        raw_row, raw_response = _query_raw_check_with_response(
            backend, engine, spec.model, "wave_data", strict
        )
        rows.append(raw_row)
        if preamble_response is not None and raw_response is not None:
            try:
                reduction = _waveform_reduction_payload(
                    model=spec.model,
                    preamble=preamble_response,
                    raw_response=raw_response,
                )
            except Exception as exc:
                rows.append(
                    LambScopeRow(
                        model=spec.model,
                        check="waveform_reductions",
                        status="fail" if strict else "skip",
                        detail=f"waveform reduction/export failed: {exc}",
                    )
                )
            else:
                reductions.append(reduction)
                rows.append(
                    LambScopeRow(
                        model=spec.model,
                        check="waveform_reductions",
                        status="pass",
                        detail=(
                            "live waveform decoded to uncertainty-bearing reductions "
                            f"and digital exports; encoding={reduction['waveform_encoding']}"
                        ),
                    )
                )
    else:
        rows.append(
            LambScopeRow(
                model=spec.model,
                check="query_raw_waveform",
                status="skip",
                detail="binary waveform transfer requires explicit --capture-waveform opt-in",
                command=_safe_command(engine, "wave_data"),
            )
        )
    return rows, reductions


def _query_check(
    backend: LambBackend,
    engine: SCPIEngine,
    model: str,
    check: str,
    alias: str,
    expected_token: str | None,
    strict: bool,
) -> LambScopeRow:
    row, _response = _query_check_with_response(
        backend, engine, model, check, alias, expected_token, strict
    )
    return row


def _query_check_with_response(
    backend: LambBackend,
    engine: SCPIEngine,
    model: str,
    check: str,
    alias: str,
    expected_token: str | None,
    strict: bool,
) -> tuple[LambScopeRow, str | None]:
    command: str | None = None
    try:
        command = _required_command(engine, alias)
        response = backend.query(command)
        parsed = _safe_parse(engine, alias, response)
        status, detail = _evaluate_query(check, response, parsed, expected_token)
    except Exception as exc:
        return (
            LambScopeRow(
                model=model,
                check=check,
                status="fail" if strict else "skip",
                detail=str(exc),
                command=command,
            ),
            None,
        )

    return (
        LambScopeRow(
            model=model,
            check=check,
            status=status,
            detail=detail,
            command=command,
            response_len=len(response.encode("utf-8")),
            response_sha256=_sha256_bytes(response.encode("utf-8")),
            response_preview=_response_preview(response),
        ),
        response if status == "pass" else None,
    )


def _query_raw_check(
    backend: LambBackend, engine: SCPIEngine, model: str, alias: str, strict: bool
) -> LambScopeRow:
    row, _response = _query_raw_check_with_response(backend, engine, model, alias, strict)
    return row


def _query_raw_check_with_response(
    backend: LambBackend, engine: SCPIEngine, model: str, alias: str, strict: bool
) -> tuple[LambScopeRow, bytes | None]:
    command: str | None = None
    try:
        command = _required_command(engine, alias)
        response = backend.query_raw(command)
        if not response:
            raise ValueError("empty binary waveform response")
    except Exception as exc:
        return (
            LambScopeRow(
                model=model,
                check="query_raw_waveform",
                status="fail" if strict else "skip",
                detail=str(exc),
                command=command,
            ),
            None,
        )
    return (
        LambScopeRow(
            model=model,
            check="query_raw_waveform",
            status="pass",
            detail="SCPI waveform response received; payload omitted from artifact; no preview retained",
            command=command,
            response_len=len(response),
            response_sha256=_sha256_bytes(response),
            response_preview=None,
        ),
        response,
    )


def _evaluate_query(
    check: str, response: str, parsed: Any, expected_token: str | None
) -> tuple[str, str]:
    text = response.strip()
    if not text:
        return "fail", "empty response"
    if expected_token and expected_token.upper() not in text.upper():
        return "fail", f"response does not contain expected token {expected_token!r}"
    if check == "error_queue" and not _is_no_error(text):
        return "fail", "instrument error queue is not clear"
    if check == "sample_rate" and float(parsed) <= 0:
        return "fail", "sample rate is not positive"
    if check == "preamble" and len([part for part in text.split(",") if part.strip()]) < 5:
        return "fail", "preamble has fewer than five CSV fields"
    return "pass", "read-only query returned a valid response"


def _safe_command(engine: SCPIEngine, alias: str) -> str | None:
    try:
        return _build_alias(engine, alias)[0]
    except Exception:
        return None


def _resolve_lamb_url(url: str | None) -> str:
    if url is None:
        raise ValueError(
            "LAMB server URL is required; pass --url or set LAMB_SERVER/PYTESTLAB_LAMB_URL"
        )
    text = url.strip()
    if not text:
        raise ValueError(
            "LAMB server URL is required; pass --url or set LAMB_SERVER/PYTESTLAB_LAMB_URL"
        )
    return text


def _required_command(engine: SCPIEngine, alias: str) -> str:
    return _build_alias(engine, alias)[0]


def _build_alias(engine: SCPIEngine, alias: str) -> list[str]:
    params = {"channel": 1, "source": "CHANnel1", "sources": "CHANnel1"}
    return engine.build(alias, **params)


def _safe_parse(engine: SCPIEngine, alias: str, response: str) -> Any:
    try:
        return engine.parse(alias, response)
    except Exception:
        return response


def _waveform_reduction_payload(
    *, model: str, preamble: str, raw_response: bytes
) -> dict[str, Any]:
    from pytestlab.instruments.waveform_decode import WaveformDecodeError
    from pytestlab.instruments.waveform_decode import decode_waveform
    from pytestlab.uncertainty import waveform_reductions_to_digital_exports

    try:
        decoded = decode_waveform(raw_response, preamble)
    except WaveformDecodeError as exc:
        raise RuntimeError(str(exc)) from exc
    values = decoded.values
    encoding = decoded.encoding
    diffs = np.diff(np.unique(np.round(values, decimals=12)))
    step = (
        float(np.min(diffs[diffs > 0]))
        if np.any(diffs > 0)
        else max(float(np.ptp(values)), 1.0) * 1e-6
    )
    from pytestlab.uncertainty.waveform import WaveformUncertaintyModel

    waveform_model = WaveformUncertaintyModel.from_metadata(
        {
            "unit": "V",
            "resolution": step,
            "preamble": decoded.preamble.to_dict(),
            "source_key": f"lamb:{model}:waveform",
            "data_origin": "measured",
            "evidence_purpose": "measurement_result",
            "origin_detail": f"LAMB live waveform capture for {model}",
        },
        samples=values,
        unit="V",
    )
    waveform = waveform_model.quantity_array(values)
    reductions = {
        "mean": waveform.mean(dof_method="validated_independent"),
        "rms": waveform.rms(dof_method="lag1_autocorrelation"),
        "peak_to_peak": (
            waveform.peak_to_peak_monte_carlo(samples=3000, seed=20_260_618)
            if values.size <= 4096
            else waveform.peak_to_peak()
        ),
    }
    exports = waveform_reductions_to_digital_exports(
        reductions,
        identifier_prefix=f"lamb-{model.lower()}-waveform",
        allow_incomplete=True,
    )
    export_rows = {}
    for name, item in exports["reductions"].items():
        export_rows[name] = {
            "identifier": item["identifier"],
            "dsi": item["dsi"],
            "dcc_xml_sha256": _sha256_bytes(str(item["dcc_xml"]).encode("utf-8")),
            "measurement_model_method": item["measurement_model_method"],
        }
    return {
        "schema": "pytestlab.lamb_scope_waveform_reductions.v1",
        "model": model,
        "status": "pass",
        "waveform_encoding": encoding,
        "point_count": int(values.size),
        "waveform_sha256": _sha256_bytes(raw_response),
        "preamble_sha256": decoded.preamble_sha256,
        "decoder_metadata": decoded.metadata(),
        "uncertainty_model": waveform_model.to_dict(),
        "uncertainty_floor": "one observed LSB/sqrt(12) or scale-relative floor",
        "metrics": {
            name: {
                "nominal": quantity.nominal,
                "standard_uncertainty": quantity.u,
                "unit": quantity.unit,
                "method": getattr(quantity.measurement_model, "method", None),
            }
            for name, quantity in reductions.items()
        },
        "digital_exports": {
            "schema": exports["schema"],
            "unsigned_dcc_subset": exports["unsigned_dcc_subset"],
            "non_claim": exports["non_claim"],
            "reductions": export_rows,
        },
    }


def _skipped_io_rows(model: str, reason: str) -> list[LambScopeRow]:
    return [
        LambScopeRow(model=model, check="idn", status="skip", detail=reason),
        LambScopeRow(model=model, check="error_queue", status="skip", detail=reason),
        LambScopeRow(model=model, check="sample_rate", status="skip", detail=reason),
        LambScopeRow(model=model, check="preamble", status="skip", detail=reason),
        LambScopeRow(model=model, check="query_raw_waveform", status="skip", detail=reason),
    ]


def _write_report(
    output_dir: str | Path | None,
    url: str,
    capture_waveform: bool,
    strict: bool,
    active: list[str],
    inactive: list[str],
    rows: list[LambScopeRow],
    reductions: list[dict[str, Any]],
) -> Path | None:
    if output_dir is None:
        return None
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "lamb_scope_check.json"
    payload = {
        "generated_utc": datetime.now(UTC).isoformat(),
        "lamb_url": url.rstrip("/"),
        "capture_waveform": capture_waveform,
        "strict": strict,
        "active_resources": active,
        "inactive_resources": inactive,
        "rows": [asdict(row) for row in rows],
        "waveform_reductions": reductions,
        "raw_payload_retention": "none; binary/text responses are represented by length/hash/preview only",
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _resolve_profile(profile: str) -> Path:
    candidate = Path(profile)
    if candidate.is_file():
        return candidate
    return resolve_profile_key_to_path(profile)


def _contains_model(resources: list[str], model: str) -> bool:
    needle = model.upper()
    return any(needle in resource.upper() for resource in resources)


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


def _is_no_error(response: str) -> bool:
    normalized = response.strip().upper()
    return normalized.startswith("+0") or normalized.startswith("0") or "NO ERROR" in normalized


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _response_preview(response: str) -> str:
    text = response.strip().replace("\n", " ")
    if len(text) > 160:
        return f"{text[:157]}..."
    return text
