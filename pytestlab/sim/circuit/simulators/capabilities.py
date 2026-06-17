from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from dataclasses import field
from enum import Enum


class UnsupportedReason(str, Enum):
    CONTROL_WRDATA_UNSUPPORTED = "CONTROL_WRDATA_UNSUPPORTED"
    SOURCE_CURRENT_UNSUPPORTED = "SOURCE_CURRENT_UNSUPPORTED"
    ELEMENT_CURRENT_UNSUPPORTED = "ELEMENT_CURRENT_UNSUPPORTED"
    BEHAVIORAL_SOURCE_UNSUPPORTED = "BEHAVIORAL_SOURCE_UNSUPPORTED"
    PSU_CC_UNSUPPORTED = "PSU_CC_UNSUPPORTED"
    COMPLEX_AC_UNPROVEN = "COMPLEX_AC_UNPROVEN"
    SOURCE_SYNTAX_UNSUPPORTED = "SOURCE_SYNTAX_UNSUPPORTED"
    RAW_NETLIST_UNSUPPORTED = "RAW_NETLIST_UNSUPPORTED"
    OUTPUT_VECTOR_UNPROVEN = "OUTPUT_VECTOR_UNPROVEN"
    SETTINGS_UNSUPPORTED = "SETTINGS_UNSUPPORTED"


@dataclass(frozen=True)
class CapabilityCheck:
    supported: bool
    reasons: tuple[UnsupportedReason, ...] = ()
    details: tuple[str, ...] = ()

    @classmethod
    def ok(cls) -> CapabilityCheck:
        return cls(supported=True)

    @classmethod
    def fail(
        cls,
        reasons: Iterable[UnsupportedReason],
        details: Iterable[str] = (),
    ) -> CapabilityCheck:
        reason_tuple = tuple(dict.fromkeys(reasons))
        return cls(supported=False, reasons=reason_tuple, details=tuple(details))


@dataclass(frozen=True)
class SimulatorCapabilities:
    backend: str
    op: bool = False
    dc_sweep: bool = False
    ac: bool = False
    transient: bool = False
    node_voltages: bool = False
    source_currents: bool = False
    element_currents: bool = False
    complex_ac: bool = False
    transient_scale: bool = False
    control_wrdata: bool = False
    params: bool = False
    includes: bool = False
    settings: bool = False
    structured_sources: bool = False
    raw_netlists: bool = False
    behavioral_sources: bool = False
    psu_current_limit: bool = False
    notes: tuple[str, ...] = ()
    unsupported_by_default: tuple[UnsupportedReason, ...] = field(default_factory=tuple)

    def supports(self, request) -> CapabilityCheck:
        reasons: list[UnsupportedReason] = []
        details: list[str] = []
        analysis = getattr(request, "analysis", None)
        analysis_value = getattr(analysis, "value", analysis)

        if analysis_value == "op" and not self.op:
            reasons.append(UnsupportedReason.OUTPUT_VECTOR_UNPROVEN)
            details.append("operating-point analysis is not proven")
        elif analysis_value == "dc" and not self.dc_sweep:
            reasons.append(UnsupportedReason.OUTPUT_VECTOR_UNPROVEN)
            details.append("DC sweep analysis is not proven")
        elif analysis_value == "ac" and not self.ac:
            reasons.append(UnsupportedReason.OUTPUT_VECTOR_UNPROVEN)
            details.append("AC analysis is not proven")
        elif analysis_value == "tran" and not self.transient:
            reasons.append(UnsupportedReason.OUTPUT_VECTOR_UNPROVEN)
            details.append("transient analysis is not proven")

        features = getattr(request, "required", None)
        if features is not None:
            if getattr(features, "node_voltages", False) and not self.node_voltages:
                reasons.append(UnsupportedReason.OUTPUT_VECTOR_UNPROVEN)
                details.append("node-voltage vectors are not proven")
            if getattr(features, "source_currents", False) and not self.source_currents:
                reasons.append(UnsupportedReason.SOURCE_CURRENT_UNSUPPORTED)
                details.append("source-current vectors are required")
            if getattr(features, "element_currents", False) and not self.element_currents:
                reasons.append(UnsupportedReason.ELEMENT_CURRENT_UNSUPPORTED)
                details.append("element-current vectors are required")
            if getattr(features, "complex_ac", False) and not self.complex_ac:
                reasons.append(UnsupportedReason.COMPLEX_AC_UNPROVEN)
                details.append("complex AC vectors are not proven")
            if getattr(features, "settings", False) and not self.settings:
                reasons.append(UnsupportedReason.SETTINGS_UNSUPPORTED)
                details.append("kernel settings are required")
            if getattr(features, "behavioral_sources", False) and not self.behavioral_sources:
                reasons.append(UnsupportedReason.BEHAVIORAL_SOURCE_UNSUPPORTED)
                details.append("behavioral sources are required")
            if getattr(features, "psu_current_limit", False) and not self.psu_current_limit:
                reasons.append(UnsupportedReason.PSU_CC_UNSUPPORTED)
                details.append("PSU current limiting is required")
            if getattr(features, "raw_netlist", False) and not self.raw_netlists:
                reasons.append(UnsupportedReason.RAW_NETLIST_UNSUPPORTED)
                details.append("raw netlist execution is required")
            if getattr(features, "structured_sources", False) and not self.structured_sources:
                reasons.append(UnsupportedReason.SOURCE_SYNTAX_UNSUPPORTED)
                details.append("structured source rendering is required")

        if reasons:
            return CapabilityCheck.fail(reasons, details)
        return CapabilityCheck.ok()


class UnsupportedCapability(RuntimeError):
    def __init__(
        self,
        backend: str,
        analysis: str,
        reasons: Iterable[UnsupportedReason],
        details: Iterable[str] = (),
    ) -> None:
        self.backend = backend
        self.analysis = analysis
        self.reasons = tuple(dict.fromkeys(reasons))
        self.details = tuple(details)
        reason_text = ", ".join(reason.value for reason in self.reasons)
        detail_text = "; ".join(self.details)
        message = f"{backend} cannot run {analysis}: {reason_text}"
        if detail_text:
            message = f"{message} ({detail_text})"
        super().__init__(message)


def require_capability(kernel, request) -> None:
    caps_func = getattr(kernel, "capabilities", None)
    if caps_func is None:
        return
    caps = caps_func()
    check_func = getattr(kernel, "supports", None)
    check = check_func(request) if check_func is not None else caps.supports(request)
    if not check.supported:
        analysis = getattr(getattr(request, "analysis", None), "value", None) or str(
            getattr(request, "analysis", "unknown")
        )
        raise UnsupportedCapability(caps.backend, analysis, check.reasons, check.details)


def capability_backend(kernel) -> str | None:
    caps_func = getattr(kernel, "capabilities", None)
    if caps_func is None:
        return None
    return str(caps_func().backend)


def raise_missing_vector(
    kernel,
    *,
    analysis: str,
    reason: UnsupportedReason,
    vector: str,
) -> None:
    backend = capability_backend(kernel)
    if backend is None:
        return
    raise UnsupportedCapability(
        backend,
        analysis,
        (reason,),
        (f"required current vector was not returned: {vector}",),
    )


def list_simulator_backends() -> tuple[str, ...]:
    return ("ngspice", "eespice")


def get_simulator_capabilities(name: str) -> SimulatorCapabilities:
    normalized = name.lower().replace("-", "_")
    if normalized == "ngspice":
        from .ngspice_cli import ngspice_capabilities

        return ngspice_capabilities()
    if normalized == "eespice":
        from .eespice_cli import eespice_capabilities

        return eespice_capabilities()
    raise KeyError(f"unknown simulator backend: {name}")
