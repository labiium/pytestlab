from __future__ import annotations

import hashlib
import json
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any

import yaml

from ..parameters import ParameterSet
from ..parameters import parameter_hash
from .report import canonicalize_validation_report_v2
from .report import resolve_validation_status
from .report import validation_report_hash

MANIFEST_NAME = "manifest.json"
PARAMETERS_NAME = "parameters.json"
REPORT_NAME = "validation_report.json"
RENDERED_NETLIST_NAME = "rendered_netlist.sp"
LEGACY_NETLIST_NAME = "netlist.sp"
LEGACY_CALIBRATED_NETLIST_NAME = "calibrated_netlist.sp"
PARAM_BLOCK_BEGIN = "* pytestlab_sim:BEGIN_CALIBRATED_PARAMETERS"
PARAM_BLOCK_END = "* pytestlab_sim:END_CALIBRATED_PARAMETERS"


@dataclass(frozen=True)
class TwinPackage:
    """Canonical pytestlab_sim twin package payload.

    V1 package directories contain ``manifest.json``, ``rendered_netlist.sp``,
    ``parameters.json``, and ``validation_report.json``.  The manifest shape is
    intentionally the same contract that pytestlab's ``sim_circuit.twin_package``
    loader consumes, so a package produced here can be used directly from bench
    YAML without user-side branching.
    """

    netlist_text: str
    parameters: ParameterSet
    manifest: dict[str, Any] = field(default_factory=dict)
    validation_report: dict[str, Any] = field(default_factory=dict)

    @property
    def model_params(self) -> dict[str, float]:
        return dict(self.parameters.values)

    def to_manifest(self) -> dict[str, Any]:
        base_netlist_hash = str(
            self.manifest.get("base_netlist_hash") or _sha256_text(self.netlist_text)
        )
        rendered_hash = _sha256_text(self.rendered_netlist_text())
        manifest = dict(self.manifest)
        report = dict(self.validation_report or {})
        report_schema = int(report.get("schema_version", 1) or 1) if report else 1
        if report_schema >= 2 and report:
            report = canonicalize_validation_report_v2(report)
        schema_version = max(int(manifest.get("schema_version", 1) or 1), report_schema)
        manifest.update(
            {
                "schema_version": schema_version,
                "format": "pytestlab_sim.twin",
                "package_type": "pytestlab_sim.twin",
                "rendered_netlist": RENDERED_NETLIST_NAME,
                "base_netlist_hash": base_netlist_hash,
                "rendered_netlist_hash": rendered_hash,
                "package_netlist_hash": _sha256_text(self.netlist_text),
                "rendered_with_params_hash": rendered_hash,
                "parameter_hash": parameter_hash(self.parameters),
                "parameter_values_hash": parameter_hash(self.parameters.values),
                "parameters": _manifest_parameters(self.parameters),
            }
        )
        if report_schema >= 2 and report:
            manifest.update(
                {
                    "validation_status": report.get("validation_status"),
                    "hardware_validated": bool(report.get("hardware_validated", False)),
                    "validation_report_hash": validation_report_hash(report),
                }
            )
        return manifest

    def rendered_netlist_text(self) -> str:
        return _render_with_parameter_block(self.netlist_text, self.parameters)


def save_twin_package(package: TwinPackage, path: str | Path) -> None:
    """Save a canonical package directory, or a zip when path ends in ``.zip``."""

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.suffix == ".zip":
        with zipfile.ZipFile(p, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            _write_zip_package(zf, package)
        return

    if p.exists() and p.is_file():
        p.unlink()
    p.mkdir(parents=True, exist_ok=True)
    (p / MANIFEST_NAME).write_text(
        json.dumps(package.to_manifest(), indent=2, sort_keys=True) + "\n"
    )
    (p / RENDERED_NETLIST_NAME).write_text(package.rendered_netlist_text())
    (p / PARAMETERS_NAME).write_text(
        json.dumps(package.parameters.to_dict(), indent=2, sort_keys=True) + "\n"
    )
    (p / REPORT_NAME).write_text(
        json.dumps(package.validation_report, indent=2, sort_keys=True) + "\n"
    )


def load_twin_package(path: str | Path) -> TwinPackage:
    p = Path(path)
    if p.is_dir():
        return _load_directory_package(p)
    if p.suffix == ".json":
        return _load_manifest_package(p)
    with zipfile.ZipFile(p, "r") as zf:
        names = set(zf.namelist())
        manifest = json.loads(zf.read(MANIFEST_NAME).decode("utf-8"))
        params = _parameters_from_payload(
            json.loads(zf.read(PARAMETERS_NAME).decode("utf-8"))
            if PARAMETERS_NAME in names
            else manifest.get("parameters", {})
        )
        report = json.loads(zf.read(REPORT_NAME).decode("utf-8")) if REPORT_NAME in names else {}
        netlist_name = str(
            manifest.get("rendered_netlist")
            or manifest.get("rendered_netlist_path")
            or (RENDERED_NETLIST_NAME if RENDERED_NETLIST_NAME in names else LEGACY_NETLIST_NAME)
        )
        _validate_zip_member_path(netlist_name)
        netlist = zf.read(netlist_name).decode("utf-8")
        _verify_declared_rendered_hash(manifest, netlist)
    _resolve_and_store_validation(manifest, report)
    return TwinPackage(
        netlist_text=_strip_calibration_parameter_block(netlist, params),
        parameters=params,
        manifest=manifest,
        validation_report=report,
    )


def package_from_mapping(
    *,
    netlist_text: str,
    values: Mapping[str, float],
    manifest: Mapping[str, Any] | None = None,
) -> TwinPackage:
    return TwinPackage(
        netlist_text=netlist_text,
        parameters=ParameterSet.from_values(values),
        manifest=dict(manifest or {}),
    )


def _write_zip_package(zf: zipfile.ZipFile, package: TwinPackage) -> None:
    zf.writestr(MANIFEST_NAME, json.dumps(package.to_manifest(), indent=2, sort_keys=True))
    zf.writestr(RENDERED_NETLIST_NAME, package.rendered_netlist_text())
    zf.writestr(
        PARAMETERS_NAME,
        json.dumps(package.parameters.to_dict(), indent=2, sort_keys=True),
    )
    zf.writestr(REPORT_NAME, json.dumps(package.validation_report, indent=2, sort_keys=True))


def _load_directory_package(root: Path) -> TwinPackage:
    manifest_json = root / MANIFEST_NAME
    if manifest_json.exists():
        return _load_manifest_package(manifest_json)

    # Legacy directory package produced by calibration/package.py.
    manifest_yaml = root / "manifest.yaml"
    if not manifest_yaml.exists():
        raise FileNotFoundError(f"twin package manifest not found in {root}")
    manifest = yaml.safe_load(manifest_yaml.read_text()) or {}
    netlist_path = root / LEGACY_CALIBRATED_NETLIST_NAME
    params_path = root / PARAMETERS_NAME
    report_path = root / REPORT_NAME
    params = _parameters_from_payload(json.loads(params_path.read_text()))
    report = json.loads(report_path.read_text()) if report_path.exists() else {}
    manifest.setdefault("rendered_netlist", LEGACY_CALIBRATED_NETLIST_NAME)
    manifest = dict(manifest)
    _resolve_and_store_validation(manifest, report)
    return TwinPackage(
        netlist_text=_strip_calibration_parameter_block(netlist_path.read_text(), params),
        parameters=params,
        manifest=manifest,
        validation_report=report,
    )


def _load_manifest_package(manifest_path: Path) -> TwinPackage:
    manifest = json.loads(manifest_path.read_text())
    root = manifest_path.parent
    rendered_name = str(
        manifest.get("rendered_netlist")
        or manifest.get("rendered_netlist_path")
        or RENDERED_NETLIST_NAME
    )
    netlist_path = (root / rendered_name).resolve()
    if not netlist_path.is_relative_to(root.resolve()):
        raise ValueError("twin package rendered netlist path escapes package root")
    params_path = root / PARAMETERS_NAME
    params = _parameters_from_payload(
        json.loads(params_path.read_text())
        if params_path.exists()
        else manifest.get("parameters", {})
    )
    report_path = root / REPORT_NAME
    report = json.loads(report_path.read_text()) if report_path.exists() else {}
    netlist = netlist_path.read_text()
    _verify_declared_rendered_hash(manifest, netlist)
    manifest = dict(manifest)
    _resolve_and_store_validation(manifest, report)
    return TwinPackage(
        netlist_text=_strip_calibration_parameter_block(netlist, params),
        parameters=params,
        manifest=manifest,
        validation_report=report,
    )


def _resolve_and_store_validation(manifest: dict[str, Any], report: dict[str, Any]) -> None:
    resolution = resolve_validation_status(manifest, report)
    manifest["validation_status"] = resolution.status.value
    manifest["hardware_validated"] = resolution.hardware_validated


def _validate_zip_member_path(name: str) -> None:
    path = PurePosixPath(name)
    if (
        not name
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
        or ":" in path.parts[0]
    ):
        raise ValueError("twin package rendered netlist path escapes package root")


def _verify_declared_rendered_hash(manifest: Mapping[str, Any], rendered_text: str) -> None:
    declared = manifest.get("rendered_netlist_hash")
    if declared is None:
        return
    actual = _sha256_text(rendered_text)
    declared_text = str(declared)
    if declared_text not in {actual, f"sha256:{actual}"}:
        raise ValueError(
            "twin package rendered_netlist_hash does not match rendered netlist content"
        )


def _parameters_from_payload(payload: Mapping[str, Any]) -> ParameterSet:
    if "values" in payload or "specs" in payload:
        return ParameterSet.from_dict(payload)
    values: dict[str, float] = {}
    specs: dict[str, dict[str, Any]] = {}
    for name, item in payload.items():
        if isinstance(item, Mapping):
            raw_value = item.get("value", item.get("nominal", item.get("initial")))
            values[str(name)] = float(raw_value)
            bounds = item.get("bounds")
            specs[str(name)] = {
                "name": str(name),
                "nominal": float(raw_value),
                "min_value": float(bounds[0])
                if isinstance(bounds, list | tuple) and len(bounds) == 2
                else item.get("min_value"),
                "max_value": float(bounds[1])
                if isinstance(bounds, list | tuple) and len(bounds) == 2
                else item.get("max_value"),
                "unit": str(item.get("unit", "")),
                "description": str(item.get("description", "")),
                "free": bool(item.get("free", True)),
            }
        else:
            values[str(name)] = float(item)
    return ParameterSet.from_values(values, specs=specs)


def _manifest_parameters(params: ParameterSet) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, value in sorted(params.values.items()):
        spec = params.specs.get(name)
        item: dict[str, Any] = {"value": float(value)}
        if spec is not None:
            item.update(
                {
                    "unit": spec.unit,
                    "bounds": [spec.min_value, spec.max_value],
                    "description": spec.description,
                    "free": spec.free,
                }
            )
        out[name] = item
    return out


def _render_with_parameter_block(text: str, params: ParameterSet) -> str:
    base_lines = text.rstrip().splitlines()
    block = [PARAM_BLOCK_BEGIN]
    block.extend(
        f".param {name}={float(value):.12g}" for name, value in sorted(params.values.items())
    )
    block.append(PARAM_BLOCK_END)

    for index in range(len(base_lines) - 1, -1, -1):
        if base_lines[index].strip().lower() == ".end":
            return "\n".join(base_lines[:index] + block + base_lines[index:]) + "\n"
    return "\n".join(base_lines + block) + "\n"


def _strip_calibration_parameter_block(text: str, params: ParameterSet) -> str:
    lines = text.splitlines()
    try:
        begin = next(i for i, line in enumerate(lines) if line.strip() == PARAM_BLOCK_BEGIN)
        end = next(i for i in range(begin + 1, len(lines)) if lines[i].strip() == PARAM_BLOCK_END)
    except StopIteration:
        return _strip_legacy_trailing_parameter_lines(text, params)
    return "\n".join(lines[:begin] + lines[end + 1 :]).rstrip() + "\n"


def _strip_legacy_trailing_parameter_lines(text: str, params: ParameterSet) -> str:
    lines = text.splitlines()
    names = set(params.values)
    while lines:
        stripped = lines[-1].strip()
        if not stripped.lower().startswith(".param "):
            break
        assignment = stripped[7:].strip()
        name = assignment.split("=", 1)[0].strip()
        if name not in names:
            break
        lines.pop()
    return "\n".join(lines).rstrip() + "\n"


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
