from __future__ import annotations

from dataclasses import dataclass

from ..spice import AcSweepSpec
from ..spice import DcSweepSpec
from ..spice import KernelSettings
from ..spice import SpiceResult
from .capabilities import SimulatorCapabilities
from .capabilities import UnsupportedCapability
from .capabilities import UnsupportedReason
from .requests import AnalysisKind
from .requests import RequiredFeatures
from .requests import SimulationRequest


def eespice_capabilities() -> SimulatorCapabilities:
    return SimulatorCapabilities(
        backend="eespice",
        op=False,
        dc_sweep=False,
        ac=False,
        transient=False,
        node_voltages=False,
        source_currents=False,
        element_currents=False,
        complex_ac=False,
        transient_scale=False,
        control_wrdata=False,
        params=False,
        includes=False,
        settings=False,
        structured_sources=True,
        raw_netlists=False,
        behavioral_sources=False,
        psu_current_limit=False,
        notes=(
            "Opt-in placeholder for EEspice CLI. Analysis execution remains disabled "
            "until output-vector parsing is proven by executable tests.",
        ),
        unsupported_by_default=(
            UnsupportedReason.CONTROL_WRDATA_UNSUPPORTED,
            UnsupportedReason.OUTPUT_VECTOR_UNPROVEN,
            UnsupportedReason.SOURCE_CURRENT_UNSUPPORTED,
            UnsupportedReason.ELEMENT_CURRENT_UNSUPPORTED,
            UnsupportedReason.COMPLEX_AC_UNPROVEN,
            UnsupportedReason.PSU_CC_UNSUPPORTED,
        ),
    )


@dataclass(frozen=True)
class EEspiceCliKernel:
    cmd: str = "eespice"

    def capabilities(self) -> SimulatorCapabilities:
        return eespice_capabilities()

    def supports(self, request: SimulationRequest):
        return self.capabilities().supports(request)

    def _raise(self, request: SimulationRequest) -> None:
        check = self.supports(request)
        reasons = check.reasons or (UnsupportedReason.OUTPUT_VECTOR_UNPROVEN,)
        details = check.details or (
            "EEspice CLI execution is opt-in but not enabled for this request",
        )
        raise UnsupportedCapability("eespice", request.analysis.value, reasons, details)

    def op(
        self,
        session,
        nodes: list[str],
        *,
        params: dict[str, float] | None = None,
        settings: KernelSettings | None = None,
        currents: list[str] | None = None,
    ) -> SpiceResult:
        self._raise(
            SimulationRequest(
                analysis=AnalysisKind.OP,
                nodes=tuple(nodes),
                source_currents=tuple(currents or ()),
                settings=settings,
                required=RequiredFeatures(
                    source_currents=bool(currents),
                    settings=settings is not None,
                    raw_netlist=True,
                ),
            )
        )

    def dc_sweep(
        self,
        session,
        nodes: list[str],
        sweep: DcSweepSpec,
        *,
        params: dict[str, float] | None = None,
        settings: KernelSettings | None = None,
        currents: list[str] | None = None,
    ) -> SpiceResult:
        self._raise(
            SimulationRequest(
                analysis=AnalysisKind.DC,
                nodes=tuple(nodes),
                source_currents=tuple(currents or ()),
                settings=settings,
                required=RequiredFeatures(
                    source_currents=bool(currents),
                    settings=settings is not None,
                    raw_netlist=True,
                ),
                metadata={"source": sweep.source},
            )
        )

    def ac(
        self,
        session,
        nodes: list[str],
        sweep: AcSweepSpec,
        *,
        params: dict[str, float] | None = None,
        settings: KernelSettings | None = None,
        currents: list[str] | None = None,
    ) -> SpiceResult:
        self._raise(
            SimulationRequest(
                analysis=AnalysisKind.AC,
                nodes=tuple(nodes),
                source_currents=tuple(currents or ()),
                settings=settings,
                required=RequiredFeatures(
                    source_currents=bool(currents),
                    complex_ac=True,
                    settings=settings is not None,
                    raw_netlist=True,
                ),
                metadata={"points": sweep.points},
            )
        )

    def transient(
        self,
        session,
        nodes: list[str],
        *,
        sample_rate: float,
        record_length: int,
        params: dict[str, float] | None = None,
        settings: KernelSettings | None = None,
        currents: list[str] | None = None,
    ) -> SpiceResult:
        self._raise(
            SimulationRequest(
                analysis=AnalysisKind.TRANSIENT,
                nodes=tuple(nodes),
                source_currents=tuple(currents or ()),
                settings=settings,
                required=RequiredFeatures(
                    source_currents=bool(currents),
                    settings=settings is not None,
                    raw_netlist=True,
                ),
                metadata={"sample_rate": sample_rate, "record_length": record_length},
            )
        )
