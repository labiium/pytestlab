from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Any

import yaml

from .dataset import CalibrationDataset
from .parameters import ParameterSet
from .report import ValidationReport

_REQUIRED = {
    "manifest.yaml",
    "calibrated_netlist.sp",
    "parameters.json",
    "calibration_dataset.csv",
    "validation_report.json",
    "validation_report.md",
    "provenance.json",
}


@dataclass(frozen=True)
class TwinPackage:
    root: Path
    manifest: dict[str, Any]
    parameters: dict[str, Any]
    provenance: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, root: str | Path) -> TwinPackage:
        root = Path(root)
        missing = sorted(name for name in _REQUIRED if not (root / name).exists())
        if missing:
            raise ValueError(f"twin package missing required files: {', '.join(missing)}")
        manifest = yaml.safe_load((root / "manifest.yaml").read_text()) or {}
        parameters = json.loads((root / "parameters.json").read_text())
        provenance = json.loads((root / "provenance.json").read_text())
        return cls(root=root, manifest=manifest, parameters=parameters, provenance=provenance)

    @property
    def calibrated_netlist_path(self) -> Path:
        return self.root / "calibrated_netlist.sp"

    @property
    def parameter_values(self) -> dict[str, float]:
        values = {}
        for item in self.parameters.get("parameters", []):
            values[str(item["name"])] = float(item["value"])
        return values


def save_twin_package(
    root: str | Path,
    *,
    netlist_text: str,
    parameter_set: ParameterSet,
    dataset: CalibrationDataset,
    report: ValidationReport,
    provenance: dict[str, Any] | None = None,
    manifest: dict[str, Any] | None = None,
    overwrite: bool = False,
) -> TwinPackage:
    root = Path(root)
    if root.exists() and overwrite:
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=not overwrite)
    provenance_payload = provenance or {}
    manifest_payload = {
        "schema_version": 1,
        "package_type": "pytestlab_sim.twin",
        "dataset_hash": dataset.content_hash(),
        "parameter_hash": parameter_set.parameter_hash(),
        "validation_passed": report.passed,
    }
    if manifest:
        manifest_payload.update(manifest)

    (root / "manifest.yaml").write_text(yaml.safe_dump(manifest_payload, sort_keys=True))
    (root / "calibrated_netlist.sp").write_text(netlist_text)
    (root / "parameters.json").write_text(
        json.dumps(parameter_set.manifest_payload(), indent=2, sort_keys=True) + "\n"
    )
    dataset.save_csv(root / "calibration_dataset.csv")
    report.write_json(root / "validation_report.json")
    report.write_markdown(root / "validation_report.md")
    (root / "provenance.json").write_text(
        json.dumps(provenance_payload, indent=2, sort_keys=True) + "\n"
    )
    return TwinPackage.load(root)
