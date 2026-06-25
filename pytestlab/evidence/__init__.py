"""Deterministic validation-evidence artifacts for PyTestLab.

The evidence bundle is a software-validation record.  It intentionally records
standards alignment, schema hashes, source tests, and reproducibility metadata;
it is not an accreditation certificate and does not claim ISO/IEC 17025 status.
"""

from __future__ import annotations

import hashlib
import json
import platform
import tomllib
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from pathlib import Path
from typing import Any
from typing import cast

from pytestlab.uncertainty.digital_export import verify_cached_schema_files
from pytestlab.uncertainty.metrology import current_git_sha

EVIDENCE_SCHEMA_VERSION = "0.1"
MANIFEST_NAME = "manifest.json"
REPORT_NAME = "report.md"

_ALLOWED_VOLATILE_FIELDS = {"generated_utc"}


class EvidenceDriftError(AssertionError):
    """Raised when a checked evidence bundle no longer matches the repository."""


@dataclass(frozen=True)
class EvidenceBundle:
    """Paths and payload emitted by evidence generation."""

    output_dir: Path
    manifest_path: Path
    report_path: Path
    manifest: dict[str, Any]


def generate_evidence(output_dir: str | Path, *, section: str = "all") -> EvidenceBundle:
    """Generate a deterministic evidence manifest and Markdown report."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest(section=section)
    manifest["payload_sha256"] = payload_hash(manifest)

    manifest_path = output / MANIFEST_NAME
    report_path = output / REPORT_NAME
    report_text = render_markdown_report(manifest)
    manifest["report_sha256"] = hashlib.sha256(report_text.encode("utf-8")).hexdigest()
    manifest_path.write_text(_json_dumps(manifest) + "\n", encoding="utf-8")
    report_path.write_text(report_text, encoding="utf-8")
    return EvidenceBundle(output, manifest_path, report_path, manifest)


def check_evidence(output_dir: str | Path) -> dict[str, Any]:
    """Check an evidence bundle against the current repository state.

    The generated timestamp is deliberately ignored; scientific payload and
    reproducibility metadata must match exactly.
    """

    output = Path(output_dir)
    existing_path = output / MANIFEST_NAME
    if not existing_path.exists():
        raise FileNotFoundError(f"Evidence manifest not found: {existing_path}")
    existing = json.loads(existing_path.read_text(encoding="utf-8"))
    recorded_hash = existing.get("payload_sha256")
    actual_existing_hash = payload_hash(existing)
    if recorded_hash != actual_existing_hash:
        raise EvidenceDriftError(
            "Evidence manifest payload_sha256 does not match its normalized payload."
        )
    report_path = output / REPORT_NAME
    if not report_path.exists():
        raise FileNotFoundError(f"Evidence report not found: {report_path}")
    recorded_report_hash = existing.get("report_sha256")
    if not isinstance(recorded_report_hash, str):
        raise EvidenceDriftError("Evidence manifest missing report_sha256.")
    report_text = report_path.read_text(encoding="utf-8")
    actual_report_hash = hashlib.sha256(report_text.encode("utf-8")).hexdigest()
    if actual_report_hash != recorded_report_hash:
        raise EvidenceDriftError(
            "Evidence report hash does not match manifest report_sha256: "
            f"recorded={recorded_report_hash}, actual={actual_report_hash}."
        )
    expected_report = render_markdown_report(existing)
    if _strip_report_volatile(report_text) != _strip_report_volatile(expected_report):
        raise EvidenceDriftError("Evidence report content does not match the manifest payload.")

    current = build_manifest(section=str(existing.get("section", "all")))
    current_hash = payload_hash(current)
    if recorded_hash != current_hash:
        raise EvidenceDriftError(
            "Evidence bundle is stale for the current repository state: "
            f"recorded={recorded_hash}, current={current_hash}."
        )
    return {
        "status": "ok",
        "payload_sha256": current_hash,
        "report_sha256": actual_report_hash,
        "manifest": str(existing_path),
        "report": str(report_path),
    }


def build_manifest(*, section: str = "all") -> dict[str, Any]:
    """Build the evidence payload before its self-hash is attached."""

    if section not in {"all", "jcgm"}:
        raise ValueError("section must be one of: all, jcgm")
    manifest = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "section": section,
        "generated_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "non_accreditation_notice": (
            "PyTestLab evidence artifacts are software-validation records, not "
            "accreditation certificates; PyTestLab does not confer ISO/IEC 17025 "
            "accreditation, DCC certification, or GUM certification."
        ),
        "environment": _environment_payload(),
        "repository": _repository_payload(),
        "schema_hashes": verify_cached_schema_files(),
        "release_hygiene": build_release_hygiene_payload(),
        "source_artifacts": _source_artifacts_payload(),
        "conformance": build_jcgm_conformance_rows(),
        "digital_exports": build_digital_export_evidence(),
        "claim_scan": scan_claim_boundaries(),
        "evidence_index": build_evidence_index(),
        "verification_commands": [
            "uv run pytest tests/uncertainty/test_validation_artifacts.py "
            "tests/uncertainty/test_quantity_array_compliance.py -q",
            "uv run pytest tests/uncertainty/test_gum_annex_h.py "
            "tests/uncertainty/test_jcgm101_examples.py "
            "tests/uncertainty/test_jcgm102_examples.py -q",
            "uv run pytest tests/ -m 'not requires_real_hw' -q",
            "uv run ruff check .",
            "uv run ruff format --check .",
            "uv run ty check",
        ],
    }
    return manifest


def build_digital_export_evidence() -> dict[str, Any]:
    """Build a compact DCC/D-SI validation sample for waveform reductions."""

    from pytestlab.uncertainty import DataOrigin
    from pytestlab.uncertainty import EvidencePurpose
    from pytestlab.uncertainty import QuantityArray
    from pytestlab.uncertainty import ResultProvenance
    from pytestlab.uncertainty import validate_dcc_profile_xml
    from pytestlab.uncertainty import waveform_reductions_to_digital_exports

    waveform = QuantityArray.from_samples([0.0, 0.5, -0.5, 0.25], unit="V", independent_std=0.01)
    waveform.provenance = ResultProvenance.current(
        input_data=waveform.nominal.tobytes(),
        data_origin=DataOrigin.SYNTHETIC_KNOWN_TRUTH,
        evidence_purpose=EvidencePurpose.SOFTWARE_VALIDATION,
        origin_detail="deterministic evidence-generation sample",
        validation_report_id="pytestlab_evidence_digital_export_sample",
        provenance_complete=False,
    )
    reductions = {
        "mean": waveform.mean(),
        "rms": waveform.rms(),
        "peak_to_peak": waveform.peak_to_peak_monte_carlo(samples=2000, seed=20_260_618),
    }
    exports = waveform_reductions_to_digital_exports(
        reductions,
        identifier_prefix="evidence-waveform",
        allow_incomplete=True,
    )
    rows = []
    for name, item in exports["reductions"].items():
        validate_dcc_profile_xml(str(item["dcc_xml"]))
        rows.append(
            {
                "name": name,
                "identifier": item["identifier"],
                "dsi_unit": item["dsi"]["unit"],
                "dsi_schema_version": item["dsi"]["dsi_schema_version"],
                "dcc_xml_sha256": hashlib.sha256(str(item["dcc_xml"]).encode()).hexdigest(),
                "method": item["measurement_model_method"],
                "data_origin": item["data_origin"],
                "evidence_purpose": item["evidence_purpose"],
                "status": "pass",
            }
        )
    return {
        "schema": "pytestlab.digital_export_evidence.v1",
        "unsigned_dcc_subset": True,
        "non_claim": exports["non_claim"],
        "rows": rows,
    }


def build_release_hygiene_payload() -> dict[str, Any]:
    """Build version and report-grade gate metadata for release evidence."""

    from pytestlab import __version__

    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    commitizen_version = str(pyproject.get("tool", {}).get("commitizen", {}).get("version", ""))
    runtime_version = str(__version__)
    version_consistent = bool(runtime_version and runtime_version == commitizen_version)
    gate_policy = {
        "measured_report_grade_requires": [
            "data_origin=measured",
            "evidence_purpose in {measurement_result, calibration_support}",
            "provenance_complete=true",
            "measurement_model present",
            "degrees-of-freedom method resolved",
            "D-SI-resolvable unit",
            "uncertainty inputs have SI-supporting traceability",
        ],
        "non_measured_exports": (
            "Non-measured, replayed, simulated, twin, or unknown-origin evidence must be "
            "machine-labeled and requires allow_non_measured=True for local XML export."
        ),
        "dcc_boundary": (
            "PyTestLab may emit unsigned local evidence XML but does not issue signed DCCs "
            "or accreditation certificates."
        ),
    }
    return {
        "schema": "pytestlab.release_hygiene.v1",
        "status": "pass" if version_consistent else "fail",
        "runtime_version": runtime_version,
        "commitizen_version": commitizen_version,
        "version_consistent": version_consistent,
        "dynamic_project_version": pyproject.get("project", {}).get("dynamic", []),
        "report_grade_gate_policy": gate_policy,
    }


def build_evidence_index() -> list[dict[str, str]]:
    """Index the validation artifacts a reviewer should inspect first."""

    paths = [
        (
            "docs/validation/CLAIMS.md",
            "Claim boundary: validated software claims and explicit non-claims.",
        ),
        (
            "CITATION.cff",
            "Citation metadata for scientific software reuse.",
        ),
        (
            "CHANGELOG.md",
            "Release notes including validation and non-accreditation boundary.",
        ),
        (
            "docs/validation/uncertainty_engine_validation_20260618.md",
            "Uncertainty engine validation baseline and schema pins.",
        ),
        (
            "tests/fixtures/hardware_replay/hd304mso_lamb_capture.json",
            "Redacted HD304MSO replay fixture for non-hardware CI parity checks.",
        ),
        (
            ".omx/evidence/scope-twin/manifest.json",
            "Generated digital-twin known-truth evidence manifest.",
        ),
        (
            ".omx/evidence/hardware-parity/hardware_parity_report.json",
            "Generated hardware replay parity report.",
        ),
    ]
    return [
        {
            "path": path,
            "description": description,
            "sha256": _file_sha256(Path(path)) or "not-generated",
        }
        for path, description in paths
    ]


def scan_claim_boundaries() -> dict[str, Any]:
    """Scan public claim surfaces for prohibited over-claiming phrases."""

    prohibited = [
        "PyTestLab is ISO/IEC 17025 accredited",
        "PyTestLab confers accreditation",
        "automatically ISO/IEC 17025 compliant",
        "DCC certified by PyTestLab",
        "GUM certified by PyTestLab",
        "PyTestLab emits accredited DCC certificates",
        "<digitalCalibrationCertificate",
    ]
    paths = [
        Path("README.md"),
        Path("paper/joss/paper.md"),
        Path("pytestlab/cli.py"),
        Path("pytestlab/uncertainty/digital_export.py"),
        Path("docs/en/user_guide/uncertainty.md"),
        Path("docs/validation/CLAIMS.md"),
        Path("docs/validation/uncertainty_engine_validation_20260618.md"),
    ]
    findings = []
    for path in paths:
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        for phrase in prohibited:
            if phrase in text:
                findings.append({"path": path.as_posix(), "phrase": phrase})
    return {
        "status": "pass" if not findings else "fail",
        "prohibited_phrases": prohibited,
        "findings": findings,
    }


def build_jcgm_conformance_rows() -> list[dict[str, Any]]:
    """Compute the JCGM/GUM rows reported by the evidence bundle."""

    import math

    import numpy as np

    from pytestlab.uncertainty import AtomRegistry
    from pytestlab.uncertainty import Distribution
    from pytestlab.uncertainty import Quantity
    from pytestlab.uncertainty import functions as fn
    from pytestlab.uncertainty.montecarlo import monte_carlo
    from pytestlab.uncertainty.multivariate import ComplexQuantity
    from pytestlab.uncertainty.multivariate import QuantityVector
    from pytestlab.uncertainty.multivariate import covariance_between

    rows: list[dict[str, Any]] = []

    def add_row(
        *,
        standard: str,
        example: str,
        measurand: str,
        expected: float,
        actual: float,
        tolerance: float,
        unit: str,
        source_test: str,
    ) -> None:
        delta = abs(actual - expected)
        rows.append(
            {
                "standard": standard,
                "example": example,
                "measurand": measurand,
                "expected": expected,
                "actual": actual,
                "delta": delta,
                "tolerance": tolerance,
                "unit": unit,
                "status": "pass" if delta <= tolerance else "fail",
                "source_test": source_test,
                "non_claim": "software-validation row; not an accreditation certificate",
            }
        )

    reg = AtomRegistry()
    components = [25.0, 9.7, 16.6, 10.4]
    actual_h1 = math.sqrt(sum(u**2 for u in components))
    add_row(
        standard="JCGM 100:2008",
        example="GUM Annex H.1 end gauge",
        measurand="combined standard uncertainty",
        expected=32.0,
        actual=actual_h1,
        tolerance=2.0,
        unit="nm",
        source_test="tests/uncertainty/test_gum_annex_h.py::test_annex_h1_end_gauge_combination",
    )

    def atom_quantity(nominal: float, u: float, label: str, unit: str = "") -> Quantity:
        atom = reg.mint(
            nominal=nominal, std_uncertainty=u, label=label, unit=unit, degrees_of_freedom=4
        )
        return Quantity.from_atom(atom, reg)

    v = atom_quantity(4.999, 0.0032, "V", "V")
    current = atom_quantity(19.661e-3, 0.0095e-3, "I", "A")
    phi = atom_quantity(1.04446, 0.00075, "phi", "")
    (u_v,), (u_i,), (u_phi,) = list(v.grad), list(current.grad), list(phi.grad)
    reg.set_correlation(u_v, u_i, -0.36)
    reg.set_correlation(u_v, u_phi, 0.86)
    reg.set_correlation(u_i, u_phi, -0.65)
    resistance = (v / current) * fn.cos(phi)
    reactance = (v / current) * fn.sin(phi)
    impedance = v / current
    for measurand, expected, actual in [
        ("u(R)", 0.071, resistance.u),
        ("u(X)", 0.295, reactance.u),
        ("u(Z)", 0.236, impedance.u),
        (
            "corr(R,X)",
            -0.588,
            covariance_between(resistance, reactance) / (resistance.u * reactance.u),
        ),
    ]:
        add_row(
            standard="JCGM 100:2008",
            example="GUM Annex H.2 correlated impedance",
            measurand=measurand,
            expected=expected,
            actual=float(actual),
            tolerance=0.005 if measurand.startswith("corr") else 0.002,
            unit="" if measurand.startswith("corr") else "ohm",
            source_test="tests/uncertainty/test_gum_annex_h.py::test_annex_h2_resistance_reactance_correlated",
        )

    reg = AtomRegistry()
    xs = {}
    for idx in range(1, 5):
        atom = reg.mint(
            nominal=0.0,
            std_uncertainty=1.0 / math.sqrt(3.0),
            label=f"x{idx}",
            distribution=Distribution.RECTANGULAR,
        )
        xs[f"x{idx}"] = Quantity.from_atom(atom, reg)

    def additive_model(x1: Any, x2: Any, x3: Any, x4: Any) -> Any:
        return x1 + x2 + x3 + x4

    analytical = cast(Quantity, additive_model(**xs))
    add_row(
        standard="JCGM 101:2008",
        example="Supplement 1 section 9.2 additive rectangular model",
        measurand="u(y)",
        expected=2.0 / math.sqrt(3.0),
        actual=analytical.u,
        tolerance=1e-12,
        unit="",
        source_test="tests/uncertainty/test_jcgm101_examples.py::test_jcgm101_additive_model_section_9_2",
    )
    mc = monte_carlo(cast(Any, additive_model), xs, samples=200_000, seed=7, confidence=0.95)
    add_row(
        standard="JCGM 101:2008",
        example="Supplement 1 section 9.2 additive rectangular model",
        measurand="MC std(y)",
        expected=2.0 / math.sqrt(3.0),
        actual=mc.std,
        tolerance=0.006,
        unit="",
        source_test="tests/uncertainty/test_jcgm101_examples.py::test_jcgm101_additive_model_section_9_2",
    )

    cov = np.array([[4.0, 1.0], [1.0, 2.0]])
    reg = AtomRegistry()
    vec = QuantityVector.from_covariance([0.0, 0.0], cov, registry=reg)
    y1 = 2 * vec[0] + vec[1]
    y2 = vec[0] - 3 * vec[1]
    jacobian = np.array([[2.0, 1.0], [1.0, -3.0]])
    expected_cov = jacobian @ cov @ jacobian.T
    actual_cov = QuantityVector([y1, y2]).covariance_matrix()
    add_row(
        standard="JCGM 102:2011",
        example="linear vector covariance propagation",
        measurand="max abs covariance delta",
        expected=0.0,
        actual=float(np.max(np.abs(actual_cov - expected_cov))),
        tolerance=1e-9,
        unit="",
        source_test="tests/uncertainty/test_jcgm102_examples.py::test_propagated_covariance_is_J_Sigma_Jt",
    )

    cov_complex = np.array([[1e-4, 0.3e-4], [0.3e-4, 4e-4]])
    complex_vec = QuantityVector.from_covariance([0.6, 0.2], cov_complex, registry=AtomRegistry())
    gamma = ComplexQuantity(complex_vec[0], complex_vec[1])
    mag = gamma.magnitude()
    expected_mag_u = math.sqrt(
        (0.6**2 * 1e-4 + 0.2**2 * 4e-4 + 2 * 0.6 * 0.2 * 0.3e-4) / (0.6**2 + 0.2**2)
    )
    add_row(
        standard="JCGM 102:2011",
        example="complex measurand magnitude",
        measurand="u(|Γ|)",
        expected=expected_mag_u,
        actual=mag.u,
        tolerance=1e-12,
        unit="",
        source_test="tests/uncertainty/test_jcgm102_examples.py::test_complex_magnitude_and_phase_propagation",
    )

    return rows


def payload_hash(payload: dict[str, Any]) -> str:
    """Return the stable hash for the non-volatile evidence payload."""

    normalized = _strip_volatile(payload)
    return hashlib.sha256(_json_dumps(normalized).encode("utf-8")).hexdigest()


def render_markdown_report(manifest: dict[str, Any]) -> str:
    """Render a concise human-readable evidence report from the manifest."""

    lines = [
        "# PyTestLab Evidence Bundle",
        "",
        f"Generated UTC: {manifest['generated_utc']}",
        f"Payload SHA256: `{manifest['payload_sha256']}`",
        "",
        "## Boundary",
        "",
        manifest["non_accreditation_notice"],
        "",
        "## Repository",
        "",
    ]
    for key, value in sorted(manifest["repository"].items()):
        lines.append(f"- {key}: `{value}`")
    hygiene = manifest.get("release_hygiene", {})
    lines.extend(["", "## Release Hygiene", ""])
    lines.append(f"- status: `{hygiene.get('status', 'unknown')}`")
    lines.append(f"- runtime_version: `{hygiene.get('runtime_version', 'unknown')}`")
    lines.append(f"- commitizen_version: `{hygiene.get('commitizen_version', 'unknown')}`")
    gate_policy = hygiene.get("report_grade_gate_policy", {})
    for requirement in gate_policy.get("measured_report_grade_requires", []):
        lines.append(f"- report-grade gate: {requirement}")
    if gate_policy.get("non_measured_exports"):
        lines.append(f"- non-measured export gate: {gate_policy['non_measured_exports']}")
    lines.extend(["", "## Schema Hashes", ""])
    for key, value in sorted(manifest["schema_hashes"].items()):
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Source Artifacts", ""])
    for artifact in manifest["source_artifacts"]:
        lines.append(f"- `{artifact['path']}` — `{artifact['sha256']}`")
    lines.extend(["", "## JCGM/GUM Conformance Rows", ""])
    lines.append(
        "| Standard | Example | Measurand | Expected | Actual | Delta | Tolerance | Status | Source test |"
    )
    lines.append("|---|---|---:|---:|---:|---:|---:|---|---|")
    for row in manifest.get("conformance", []):
        lines.append(
            "| {standard} | {example} | {measurand} | {expected:.12g} | {actual:.12g} | "
            "{delta:.3g} | {tolerance:.3g} | {status} | `{source_test}` |".format(**row)
        )
    lines.extend(["", "## Digital Export Evidence", ""])
    for row in manifest.get("digital_exports", {}).get("rows", []):
        lines.append(
            "- {name}: D-SI `{dsi_unit}` / {dsi_schema_version}, DCC XML "
            "`{dcc_xml_sha256}`, method `{method}`, status {status}".format(**row)
        )
    lines.extend(["", "## Claims Scan", ""])
    scan = manifest.get("claim_scan", {})
    lines.append(f"- status: `{scan.get('status', 'unknown')}`")
    for finding in scan.get("findings", []):
        lines.append(f"- finding: `{finding['phrase']}` in `{finding['path']}`")
    lines.extend(["", "## Evidence Index", ""])
    for item in manifest.get("evidence_index", []):
        lines.append(f"- `{item['path']}` — {item['description']} — `{item['sha256']}`")
    lines.extend(["", "## Verification Commands", ""])
    for command in manifest["verification_commands"]:
        lines.append(f"- `{command}`")
    lines.append("")
    return "\n".join(lines)


def _environment_payload() -> dict[str, str]:
    import numpy as np

    try:
        import scipy

        scipy_version = scipy.__version__
    except Exception:  # pragma: no cover - scipy is a dependency, keep robust
        scipy_version = "unavailable"
    pytestlab_version: str
    try:
        from pytestlab import __version__

        pytestlab_version = str(__version__)
    except Exception:  # pragma: no cover
        pytestlab_version = "unknown"
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "numpy": np.__version__,
        "scipy": scipy_version,
        "pytestlab": pytestlab_version,
    }


def _repository_payload() -> dict[str, str | None]:
    return {
        "git_sha": current_git_sha(),
        "pyproject_sha256": _file_sha256(Path("pyproject.toml")),
        "uv_lock_sha256": _file_sha256(Path("uv.lock")),
    }


def _source_artifacts_payload() -> list[dict[str, str]]:
    paths = [
        Path("docs/validation/uncertainty_engine_validation_20260618.md"),
        Path("tests/uncertainty/test_gum_annex_h.py"),
        Path("tests/uncertainty/test_jcgm101_examples.py"),
        Path("tests/uncertainty/test_jcgm102_examples.py"),
        Path("tests/uncertainty/test_quantity_array_compliance.py"),
        Path("tests/uncertainty/test_oscilloscope_quantity_array.py"),
        Path("tests/test_dcc_dsi_claims.py"),
        Path("docs/validation/CLAIMS.md"),
        Path("CITATION.cff"),
        Path("CHANGELOG.md"),
        Path("paper/joss/paper.md"),
        Path("pytestlab/uncertainty/quantity_array.py"),
        Path("pytestlab/uncertainty/digital_export.py"),
        Path("pytestlab/evidence/__init__.py"),
    ]
    return [{"path": path.as_posix(), "sha256": _file_sha256(path) or "missing"} for path in paths]


def _file_sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _strip_volatile(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _strip_volatile(item)
            for key, item in value.items()
            if key not in _ALLOWED_VOLATILE_FIELDS
            and key not in {"payload_sha256", "report_sha256"}
        }
    if isinstance(value, list):
        return [_strip_volatile(item) for item in value]
    return value


def _strip_report_volatile(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.startswith("Generated UTC:"))


def _json_dumps(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False)
