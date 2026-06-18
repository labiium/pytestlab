from __future__ import annotations

from ..spice import _sanitize_identifier
from .base import InjectionResult


class DmmInjector:
    def inject(self, session) -> InjectionResult:
        result = InjectionResult()
        ground = session.wiring.ground_node
        for dmm_id in session.dmms.keys():
            hi_term = f"{dmm_id}.V.HI"
            lo_term = f"{dmm_id}.V.LO"
            if session.wiring.probe_model_for(hi_term) or session.wiring.probe_model_for(
                f"{dmm_id}.V"
            ):
                continue
            node_hi = session.mapping.get(hi_term)
            if not node_hi:
                continue
            node_lo = session.mapping.get(lo_term) or ground
            cfg = session.bench.instruments.get(dmm_id)
            rin = float(getattr(cfg, "rin_v_ohm", 10e6)) if cfg is not None else 10e6
            ident = _sanitize_identifier(f"{dmm_id}_V")
            result.netlist_lines.append(f"R_SB_DMM_{ident} {node_hi} {node_lo} {rin}")

        for dmm_id in session.dmms.keys():
            hi_term = f"{dmm_id}.I.HI"
            lo_term = f"{dmm_id}.I.LO"
            node_hi = session.mapping.get(hi_term)
            node_lo = session.mapping.get(lo_term)
            if not node_hi or not node_lo or node_hi == node_lo:
                continue
            cfg = session.bench.instruments.get(dmm_id)
            burden = float(getattr(cfg, "burden_ohm", 0.1)) if cfg is not None else 0.1
            ident = _sanitize_identifier(f"{dmm_id}_I")
            sense = f"V_SB_DMMI_SENSE_{ident}"
            shunt = f"R_SB_DMMI_{ident}"
            mid = f"n_sb_dmmi_{ident}"
            result.netlist_lines.append(f"{sense} {node_hi} {mid} 0")
            result.netlist_lines.append(f"{shunt} {mid} {node_lo} {burden}")
            result.element_currents[f"{dmm_id}.I"] = sense
        return result
