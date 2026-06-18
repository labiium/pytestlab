from __future__ import annotations

from ..models import SourceDescriptor
from ..spice import _sanitize_identifier
from .base import InjectionResult


class PsuInjector:
    def inject(self, session) -> InjectionResult:
        result = InjectionResult()
        ground = session.wiring.ground_node
        for psu_id, psu in session.psus.items():
            cfg = session.bench.instruments.get(psu_id)
            channels = getattr(cfg, "channels", None) if cfg is not None else None
            if not channels:
                channels = [type("Channel", (), {"name": "CH1", "r_out_ohm": 0.05})()]
            for ch in channels:
                ch_name = str(getattr(ch, "name", "CH1"))
                state = psu.state.channels.get(ch_name)
                if state is None or not state.enabled:
                    continue
                hi = session.mapping.get(f"{psu_id}.{ch_name}.HI")
                if not hi:
                    continue
                lo = session.mapping.get(f"{psu_id}.{ch_name}.LO") or ground
                i_lim = float(getattr(state, "current_limit", 0.0))
                ident = _sanitize_identifier(f"{psu_id}_{ch_name}")
                internal = f"n_sb_psu_{ident}"
                cv_node = f"n_sb_cv_{ident}"
                ilim = f"I_SB_LIM_{ident}"
                vcv = f"V_SB_CV_{ident}"
                diode = f"D_SB_CLAMP_{ident}"
                diode_model = f"D_SB_IDEAL_{ident}"
                sense = f"V_SB_SENSE_{ident}"
                result.netlist_lines.append(f"* SimBench PSU {psu_id}.{ch_name}")
                if i_lim > 0:
                    result.netlist_lines.append(f"{ilim} {lo} {internal} DC {i_lim:.12g}")
                    result.netlist_lines.append(
                        f"{vcv} {cv_node} {lo} DC {float(state.voltage_setpoint):.12g}"
                    )
                    result.netlist_lines.append(f"{diode} {internal} {cv_node} {diode_model}")
                    result.netlist_lines.append(f".model {diode_model} D(Is=1e-9 N=0.01 Rs=1e-6)")
                    # Positive terminal on the load side makes ngspice i(Vsense)
                    # negative for delivered current, matching voltage-source readback sign.
                    result.netlist_lines.append(f"{sense} {hi} {internal} 0")
                    readback = sense
                else:
                    r_out = float(getattr(ch, "r_out_ohm", 0.05))
                    vsrc = f"V_SB_PSU_{ident}"
                    rser = f"R_SB_PSU_{ident}"
                    result.netlist_lines.append(
                        f"{vsrc} {internal} {lo} DC {float(state.voltage_setpoint):.12g}"
                    )
                    result.netlist_lines.append(f"{rser} {internal} {hi} {r_out:.12g}")
                    readback = vsrc
                result.sources.append(
                    SourceDescriptor(
                        kind="psu",
                        key=f"{psu_id}.{ch_name}",
                        vsrc_name=readback,
                        hi_node=hi,
                        lo_node=lo,
                    )
                )
                if i_lim > 0:
                    result.element_currents[f"{psu_id}.{ch_name}"] = sense
        return result
