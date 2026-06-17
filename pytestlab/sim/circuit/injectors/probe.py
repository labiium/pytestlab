from __future__ import annotations

from ..spice import _resolve_probe_terminal
from ..spice import _sanitize_identifier
from .base import InjectionResult


class ProbeInjector:
    def inject(self, session) -> InjectionResult:
        result = InjectionResult()
        ground = session.wiring.ground_node

        for key, probe in session.wiring.probe_models.items():
            terminal = _resolve_probe_terminal(key, terminals=session.compiler.terminals)
            if terminal is None:
                continue
            node_hi = session.mapping.get(terminal)
            if not node_hi:
                continue
            base, _, suffix = terminal.rpartition(".")
            node_lo = ground
            if suffix in {"HI", "LO"} and base:
                other = f"{base}.{'LO' if suffix == 'HI' else 'HI'}"
                node_lo = session.mapping.get(other) or ground
            ident = _sanitize_identifier(key)
            probe_node = node_hi
            if probe.lin_h:
                probe_node = f"n_sb_probe_{ident}"
                result.netlist_lines.append(
                    f"L_SB_PROBE_{ident} {node_hi} {probe_node} {float(probe.lin_h):.12g}"
                )
            if probe.rin_ohm:
                result.netlist_lines.append(
                    f"R_SB_PROBE_{ident} {probe_node} {node_lo} {float(probe.rin_ohm):.12g}"
                )
            if probe.cin_f:
                result.netlist_lines.append(
                    f"C_SB_PROBE_{ident} {probe_node} {node_lo} {float(probe.cin_f):.12g}"
                )

        for scope_id, scope_twin in session.scopes.items():
            del scope_twin
            cfg = session.bench.instruments.get(scope_id)
            n_ch = int(getattr(cfg, "channels", 2))
            for ch_n in range(1, n_ch + 1):
                hi_term = f"{scope_id}.CH{ch_n}.HI"
                lo_term = f"{scope_id}.CH{ch_n}.LO"
                if session.wiring.probe_model_for(hi_term):
                    continue
                hi_node = session.mapping.get(hi_term)
                if not hi_node:
                    continue
                lo_node = session.mapping.get(lo_term) or ground
                rin = float(getattr(cfg, "rin_ohm", 1e6))
                cin = float(getattr(cfg, "cin_f", 15e-12))
                ident = _sanitize_identifier(f"{scope_id}_CH{ch_n}")
                result.netlist_lines.append(f"R_SB_SCOPE_{ident} {hi_node} {lo_node} {rin:.12g}")
                if cin > 0:
                    result.netlist_lines.append(
                        f"C_SB_SCOPE_{ident} {hi_node} {lo_node} {cin:.12g}"
                    )
        return result
