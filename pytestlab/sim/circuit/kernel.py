from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .spice import AcSweepSpec
from .spice import DcSweepSpec
from .spice import KernelSettings
from .spice import SpiceResult
from .spice import simulate_ac
from .spice import simulate_dc_sweep
from .spice import simulate_op
from .spice import simulate_transient


class KernelAdapter(Protocol):
    def op(
        self,
        session,
        nodes: list[str],
        *,
        params: dict[str, float] | None = None,
        settings: KernelSettings | None = None,
        currents: list[str] | None = None,
    ) -> SpiceResult: ...

    def dc_sweep(
        self,
        session,
        nodes: list[str],
        sweep: DcSweepSpec,
        *,
        params: dict[str, float] | None = None,
        settings: KernelSettings | None = None,
        currents: list[str] | None = None,
    ) -> SpiceResult: ...

    def ac(
        self,
        session,
        nodes: list[str],
        sweep: AcSweepSpec,
        *,
        params: dict[str, float] | None = None,
        settings: KernelSettings | None = None,
        currents: list[str] | None = None,
    ) -> SpiceResult: ...

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
    ) -> SpiceResult: ...


@dataclass(frozen=True)
class NgspiceKernel:
    cmd: str = "ngspice"

    def capabilities(self):
        from .simulators.ngspice_cli import ngspice_capabilities

        return ngspice_capabilities()

    def supports(self, request):
        return self.capabilities().supports(request)

    def op(
        self,
        session,
        nodes: list[str],
        *,
        params: dict[str, float] | None = None,
        settings: KernelSettings | None = None,
        currents: list[str] | None = None,
    ) -> SpiceResult:
        return simulate_op(
            session,
            nodes,
            params=params,
            settings=settings,
            currents=currents,
            cmd=self.cmd,
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
        return simulate_dc_sweep(
            session,
            nodes,
            sweep,
            params=params,
            settings=settings,
            currents=currents,
            cmd=self.cmd,
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
        return simulate_ac(
            session,
            nodes,
            sweep,
            params=params,
            settings=settings,
            currents=currents,
            cmd=self.cmd,
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
        return simulate_transient(
            session,
            nodes,
            sample_rate=sample_rate,
            record_length=record_length,
            params=params,
            settings=settings,
            currents=currents,
            cmd=self.cmd,
        )
