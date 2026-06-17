from __future__ import annotations

from ..models import SourceDescriptor
from ..spice import _awg_source_spec
from ..spice import _sanitize_identifier
from .base import InjectionResult


class AwgInjector:
    def inject(self, session) -> InjectionResult:
        result = InjectionResult()
        ground = session.wiring.ground_node
        for awg_id, awg in session.awgs.items():
            if not getattr(awg.state, "enabled", False):
                continue
            hi = session.mapping.get(f"{awg_id}.HI")
            if not hi:
                continue
            lo = session.mapping.get(f"{awg_id}.LO") or ground
            cfg = session.bench.instruments.get(awg_id)
            z_out = float(getattr(cfg, "z_out_ohm", 50.0)) if cfg is not None else 50.0
            ident = _sanitize_identifier(awg_id)
            internal = f"n_sb_awg_{ident}"
            vsrc = f"V_SB_AWG_{ident}"
            rser = f"R_SB_AWG_{ident}"
            spec = _awg_source_spec(awg)
            ac_prefix = "" if spec.startswith("DC ") else "AC 1 "
            result.netlist_lines.append(f"* SimBench AWG {awg_id}")
            result.netlist_lines.append(f"{vsrc} {internal} {lo} {ac_prefix}{spec}")
            result.netlist_lines.append(f"{rser} {internal} {hi} {z_out}")
            result.sources.append(
                SourceDescriptor(kind="awg", key=awg_id, vsrc_name=vsrc, hi_node=hi, lo_node=lo)
            )
        return result
