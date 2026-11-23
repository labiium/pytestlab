from __future__ import annotations

from ..kernel import NgspiceKernel as NgspiceCliKernel
from .capabilities import SimulatorCapabilities


def ngspice_capabilities() -> SimulatorCapabilities:
    return SimulatorCapabilities(
        backend="ngspice",
        op=True,
        dc_sweep=True,
        ac=True,
        transient=True,
        node_voltages=True,
        source_currents=True,
        element_currents=True,
        complex_ac=True,
        transient_scale=True,
        control_wrdata=True,
        params=True,
        includes=True,
        settings=True,
        structured_sources=True,
        raw_netlists=True,
        behavioral_sources=True,
        psu_current_limit=True,
        notes=("Default full-fidelity simulator backend and reference oracle.",),
    )


__all__ = ["NgspiceCliKernel", "ngspice_capabilities"]
