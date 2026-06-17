from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from pydantic import Field
from pydantic import model_validator

from .netlist import expand_includes
from .netlist import extract_nodes


class ManifestMetadata(BaseModel):
    title: str
    author: str
    license: str
    intended_analyses: list[str] = Field(..., min_length=1)


class ManifestConstraints(BaseModel):
    max_nodes: int = 2000
    max_elements: int = 5000
    max_tran_time_s: float = 0.5
    max_points: int = 5_000_000
    max_file_bytes: int = 2_000_000
    max_include_depth: int = 5
    max_include_files: int = 50


class Manifest(BaseModel):
    format_version: str = "1.0"
    entry_netlist: str
    allowed_includes: list[str] = Field(default_factory=list)
    metadata: ManifestMetadata
    constraints: ManifestConstraints = ManifestConstraints()
    hashes: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def ensure_entry_hash(self) -> Manifest:
        if self.entry_netlist not in self.hashes:
            raise ValueError("hashes must include entry_netlist")
        return self


class NetlistSummary(BaseModel):
    nodes: list[str]
    element_count: int
    sources: list[str]
    parameters: list[str]


class CircuitPackage:
    """Represents an uploaded circuit package following LABIIUM rules."""

    def __init__(self, root: Path, manifest: Manifest):
        self.root = root
        self.manifest = manifest
        self.metadata: dict[str, Any] = manifest.metadata.model_dump()

    @classmethod
    def from_path(cls, path: Path) -> CircuitPackage:
        if not path.exists():
            raise FileNotFoundError(path)
        if path.suffix == ".zip":
            with zipfile.ZipFile(path, "r") as zf:
                manifest_data = json.loads(zf.read("manifest.json"))
                manifest = Manifest(**manifest_data)
                extract_dir = Path(path).with_suffix("")
                if extract_dir.exists():
                    for item in extract_dir.iterdir():
                        if item.is_dir():
                            for child in item.rglob("*"):
                                child.unlink(missing_ok=True)
                        else:
                            item.unlink()
                zf.extractall(extract_dir)
                root = extract_dir
        else:
            manifest_path = path.with_suffix("").with_name("manifest.json")
            if not manifest_path.exists():
                raise FileNotFoundError("manifest.json not found next to netlist")
            manifest = Manifest(**json.loads(manifest_path.read_text()))
            root = path.parent
        cls._validate_files(root, manifest)
        return cls(root=root, manifest=manifest)

    @staticmethod
    def _validate_files(root: Path, manifest: Manifest) -> None:
        entry = root / manifest.entry_netlist
        if not entry.exists():
            raise FileNotFoundError(f"entry_netlist missing: {entry}")
        if not entry.resolve().is_relative_to(root.resolve()):
            raise ValueError("entry_netlist must reside inside the package root")
        if entry.stat().st_size > manifest.constraints.max_file_bytes:
            raise ValueError("entry_netlist exceeds max_file_bytes constraint")
        CircuitPackage._ensure_hash(entry, manifest.hashes[manifest.entry_netlist])
        entry_text = entry.read_text()
        expanded = expand_includes(
            entry_text,
            root=root,
            allowed_includes=set(manifest.allowed_includes),
            max_depth=manifest.constraints.max_include_depth,
            max_files=manifest.constraints.max_include_files,
            max_file_bytes=manifest.constraints.max_file_bytes,
        )
        CircuitPackage._reject_dangerous_directives(expanded.text)
        for include in manifest.allowed_includes:
            candidate = root / include
            if not candidate.exists():
                raise FileNotFoundError(f"allowed include missing: {candidate}")
            if not candidate.resolve().is_relative_to(root.resolve()):
                raise ValueError(f"allowed include outside package root: {include}")
            if candidate.stat().st_size > manifest.constraints.max_file_bytes:
                raise ValueError("allowed include exceeds max_file_bytes constraint")
        CircuitPackage._validate_constraints(expanded.text, manifest.constraints)

    @staticmethod
    def _ensure_hash(path: Path, expected: str) -> None:
        algo, _, digest = expected.partition(":")
        if not algo:
            raise ValueError("hash must be algorithm:digest")
        h = hashlib.new(algo)
        h.update(path.read_bytes())
        if h.hexdigest() != digest:
            raise ValueError(f"hash mismatch for {path}")

    def canonicalize(self) -> str:
        """Return normalized netlist text for deterministic hashing."""
        entry = self.root / self.manifest.entry_netlist
        return "\n".join(line.rstrip() for line in entry.read_text().splitlines())

    def summarize(self) -> NetlistSummary:
        entry = self.root / self.manifest.entry_netlist
        expanded = expand_includes(
            entry.read_text(),
            root=self.root,
            allowed_includes=set(self.manifest.allowed_includes),
            max_depth=self.manifest.constraints.max_include_depth,
            max_files=self.manifest.constraints.max_include_files,
            max_file_bytes=self.manifest.constraints.max_file_bytes,
        )
        return self._summarize_netlist_text(expanded.text)

    def to_content_hash(self) -> str:
        normalized = self.canonicalize().encode()
        digest = hashlib.sha256(normalized).hexdigest()
        return f"sha256:{digest}"

    @staticmethod
    def _summarize_netlist_text(text: str) -> NetlistSummary:
        nodes = extract_nodes(text)
        sources = []
        params = []
        element_count = 0
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("*"):
                continue
            if stripped.startswith("."):
                if stripped.lower().startswith((".param", "param")):
                    params.append(stripped)
                continue
            parts = stripped.split()
            if not parts:
                continue
            element_count += 1
            if parts[0][0].upper() in {"V", "I"}:
                sources.append(parts[0])
        return NetlistSummary(
            nodes=sorted(nodes),
            element_count=element_count,
            sources=sources,
            parameters=params,
        )

    @staticmethod
    def _validate_constraints(text: str, constraints: ManifestConstraints) -> None:
        summary = CircuitPackage._summarize_netlist_text(text)
        if len(summary.nodes) > constraints.max_nodes:
            raise ValueError("netlist exceeds max_nodes constraint")
        if summary.element_count > constraints.max_elements:
            raise ValueError("netlist exceeds max_elements constraint")

    @staticmethod
    def _reject_dangerous_directives(text: str) -> None:
        blocked = {"control", "shell", "exec", "system"}
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("*"):
                continue
            if not stripped.startswith("."):
                continue
            directive = stripped[1:].split()[0].lower()
            if directive in blocked:
                raise ValueError(f"unsupported directive: .{directive}")
