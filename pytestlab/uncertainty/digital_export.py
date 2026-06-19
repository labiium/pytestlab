"""D-SI and unsigned DCC XML export foundations."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from .metrology import report_grade_blockers
from .quantity import Quantity
from .quantity_array import QuantityArray
from .units import require_dsi_unit

DCC_SCHEMA_VERSION = "3.3.0"
DSI_SCHEMA_VERSION = "2.2.1"
DCC_SCHEMA_URL = "https://ptb.de/dcc/v3.3.0/dcc.xsd"
DSI_SCHEMA_URL = "https://www.ptb.de/si/v2.2.1/SI_Format.xsd"
SCHEMA_ROOT = Path(__file__).resolve().parents[2] / "schemas" / "metrology"


def quantity_to_dsi(
    value: Quantity | QuantityArray, *, coverage_factor: float = 2.0
) -> dict[str, Any]:
    """Return a D-SI-like data payload, failing rather than guessing units."""

    payload = value.to_dsi(coverage_factor=coverage_factor)
    payload["unit"] = require_dsi_unit(getattr(value, "unit", ""))
    payload["dsi_schema_version"] = DSI_SCHEMA_VERSION
    return payload


def quantity_to_pytestlab_evidence_xml(
    value: Quantity,
    *,
    identifier: str,
    coverage_factor: float = 2.0,
    allow_incomplete: bool = False,
) -> str:
    """Create PyTestLab's unsigned XML evidence record for scalar/reduction results.

    This is a local software-validation evidence format.  It intentionally does
    not claim to be a signed DCC, an accredited calibration certificate, or a
    full PTB DCC schema-valid document.
    """

    blockers = report_grade_blockers(value)
    if blockers and not allow_incomplete:
        raise ValueError("Refusing DCC export for non-report-grade result: " + "; ".join(blockers))
    dsi = quantity_to_dsi(value, coverage_factor=coverage_factor)
    root = ET.Element(
        "pytestlabMeasurementEvidence",
        {
            "schemaVersion": DCC_SCHEMA_VERSION,
            "unsigned": "true",
            "dccSchema": DCC_SCHEMA_URL,
            "dsiSchema": DSI_SCHEMA_URL,
            "profile": "pytestlab-evidence-xml-1.0",
            "notDccCertificate": "true",
        },
    )
    administrative = ET.SubElement(root, "administrativeData")
    ET.SubElement(administrative, "software").text = "PyTestLab"
    ET.SubElement(administrative, "reportGrade").text = str(not blockers).lower()
    if blockers:
        blocker_el = ET.SubElement(administrative, "reportGradeBlockers")
        for blocker in blockers:
            ET.SubElement(blocker_el, "blocker").text = blocker
    result = ET.SubElement(root, "measurementResult", {"id": identifier})
    ET.SubElement(result, "value", {"unit": str(dsi["unit"])}).text = str(dsi["value"])
    ET.SubElement(result, "standardUncertainty", {"unit": str(dsi["unit"])}).text = str(
        dsi["standard_uncertainty"]
    )
    ET.SubElement(result, "expandedUncertainty", {"unit": str(dsi["unit"])}).text = str(
        dsi["expanded_uncertainty"]
    )
    ET.SubElement(result, "coverageFactor").text = str(dsi["coverageFactor"])
    ET.SubElement(
        result, "unsignedScopeNote"
    ).text = "Unsigned export: cryptographic signing and PKI are the issuing laboratory's responsibility."
    xml = ET.tostring(root, encoding="unicode")
    validate_dcc_profile_xml(xml)
    return xml


def quantity_to_dcc_candidate_xml(
    value: Quantity,
    *,
    identifier: str,
    coverage_factor: float = 2.0,
    allow_incomplete: bool = False,
    require_full_xsd: bool = True,
) -> str:
    """Return DCC candidate XML only when full DCC validation is available.

    PyTestLab does not currently ship a complete DCC authoring/signing stack.
    The fail-loud default prevents accidentally presenting local evidence XML as
    a PTB DCC certificate.
    """

    if require_full_xsd:
        raise NotImplementedError(
            "Full PTB DCC XSD validation/signing is not implemented. "
            "Use quantity_to_pytestlab_evidence_xml() for unsigned software-validation evidence."
        )
    return quantity_to_pytestlab_evidence_xml(
        value,
        identifier=identifier,
        coverage_factor=coverage_factor,
        allow_incomplete=allow_incomplete,
    )


def quantity_to_unsigned_dcc_xml(
    value: Quantity,
    *,
    identifier: str,
    coverage_factor: float = 2.0,
    allow_incomplete: bool = False,
) -> str:
    """Compatibility alias for PyTestLab's unsigned evidence XML.

    New code should use :func:`quantity_to_pytestlab_evidence_xml`.  The emitted
    root is intentionally *not* ``digitalCalibrationCertificate``.
    """

    return quantity_to_pytestlab_evidence_xml(
        value,
        identifier=identifier,
        coverage_factor=coverage_factor,
        allow_incomplete=allow_incomplete,
    )


def waveform_reductions_to_digital_exports(
    reductions: dict[str, Quantity],
    *,
    identifier_prefix: str = "waveform",
    coverage_factor: float = 2.0,
    allow_incomplete: bool = True,
) -> dict[str, Any]:
    """Export waveform scalar reductions as D-SI payloads plus unsigned DCC XML.

    This helper is intentionally scoped to scalar reductions derived from a
    waveform ``QuantityArray`` (for example mean/RMS/Vpp).  It keeps D-SI unit
    resolution fail-loud and records that DCC XML is an unsigned PyTestLab subset,
    not a complete signed calibration certificate.
    """

    payload: dict[str, Any] = {
        "schema": "pytestlab.waveform_reduction_digital_exports.v1",
        "dcc_schema_version": DCC_SCHEMA_VERSION,
        "dsi_schema_version": DSI_SCHEMA_VERSION,
        "unsigned_dcc_subset": True,
        "non_claim": (
            "Unsigned PyTestLab software-validation evidence; not an accredited "
            "calibration certificate, not a signed DCC, and not DCC certification."
        ),
        "reductions": {},
    }
    for name, quantity in reductions.items():
        identifier = f"{identifier_prefix}-{name}".replace("_", "-")
        dsi = quantity_to_dsi(quantity, coverage_factor=coverage_factor)
        xml = quantity_to_pytestlab_evidence_xml(
            quantity,
            identifier=identifier,
            coverage_factor=coverage_factor,
            allow_incomplete=allow_incomplete,
        )
        validate_dcc_profile_xml(xml)
        payload["reductions"][name] = {
            "identifier": identifier,
            "dsi": dsi,
            "dcc_xml": xml,
            "measurement_model_method": getattr(quantity.measurement_model, "method", None),
        }
    return payload


def validate_dcc_profile_xml(xml: str) -> None:
    """Validate the strict PyTestLab DCC-subset profile without live network access.

    Full DCC XSD validation is performed by accredited-lab tooling.  This local
    validator enforces the fields PyTestLab can guarantee and records the pinned
    schema versions that external validation must use.
    """

    root = ET.fromstring(xml)
    if root.tag != "pytestlabMeasurementEvidence":
        raise ValueError("PyTestLab evidence XML root must be pytestlabMeasurementEvidence.")
    if root.attrib.get("schemaVersion") != DCC_SCHEMA_VERSION:
        raise ValueError(f"DCC schemaVersion must be {DCC_SCHEMA_VERSION}.")
    if root.attrib.get("dsiSchema") != DSI_SCHEMA_URL:
        raise ValueError("DCC profile must record the pinned D-SI schema URL.")
    if root.attrib.get("unsigned") != "true":
        raise ValueError("PyTestLab DCC profile exports are unsigned and must say so.")
    if root.attrib.get("notDccCertificate") != "true":
        raise ValueError("PyTestLab evidence XML must state notDccCertificate=true.")
    if root.find("administrativeData") is None:
        raise ValueError("DCC profile requires administrativeData.")
    result = root.find("measurementResult")
    if result is None or not result.attrib.get("id"):
        raise ValueError("DCC profile requires a measurementResult id.")
    required = ["value", "standardUncertainty", "expandedUncertainty", "coverageFactor"]
    missing = [name for name in required if result.find(name) is None]
    if missing:
        raise ValueError(f"DCC profile missing required result fields: {missing}.")


def verify_cached_schema_files(schema_root: Path | None = None) -> dict[str, str]:
    """Verify pinned DCC/D-SI schema cache checksums and return them."""

    root = schema_root or SCHEMA_ROOT
    files = {
        "dcc": root / "dcc-3.3.0" / "dcc.xsd",
        "d-si": root / "d-si-2.2.1" / "SI_Format.xsd",
    }
    verified: dict[str, str] = {}
    for name, path in files.items():
        manifest_path = path.with_suffix(path.suffix + ".manifest.json")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != manifest.get("sha256"):
            raise ValueError(f"Cached {name} schema checksum mismatch.")
        verified[name] = actual
    return verified
