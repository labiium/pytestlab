from __future__ import annotations

import numpy as np

from pytestlab.sim.circuit import Port
from pytestlab.sim.circuit import SimSession
from pytestlab.sim.circuit.spice import SpiceResult


class CapturingKernel:
    def __init__(self):
        self.calls: list[dict[str, float] | None] = []

    def op(self, session, nodes, *, settings=None, currents=None, params=None):
        self.calls.append(params)
        return SpiceResult(
            "op",
            np.asarray([0.0]),
            "op",
            {node: np.asarray([1.0]) for node in nodes},
            {},
            (),
        )

    def transient(
        self,
        session,
        nodes,
        *,
        sample_rate,
        record_length,
        settings=None,
        currents=None,
        params=None,
    ):
        self.calls.append(params)
        t = np.arange(record_length) / sample_rate
        return SpiceResult(
            "tran", t, "s", {node: np.ones(record_length) for node in nodes}, {}, ()
        )

    def ac(self, session, nodes, sweep, *, settings=None, currents=None, params=None):
        self.calls.append(params)
        freq = np.asarray([1.0, 10.0])
        return SpiceResult(
            "ac",
            freq,
            "Hz",
            {node: np.ones(2, dtype=complex) for node in nodes},
            {},
            (),
        )

    def dc_sweep(
        self, session, nodes, sweep, *, settings=None, currents=None, params=None
    ):
        self.calls.append(params)
        scale = np.asarray([sweep.start, sweep.stop])
        return SpiceResult("dc", scale, "V", {node: scale for node in nodes}, {}, ())


def test_session_model_params_resolve_and_kernel_paths(netlist_path) -> None:
    sim = SimSession.from_netlist(netlist_path).ports(vout=Port.probe("vout", "0"))
    session = sim._require_session()
    session.parameter_set = session.parameter_set.from_values({"rc": 1000.0})
    session.model_params = {"rc": 1000.0}
    kernel = CapturingKernel()
    session.kernel = kernel

    assert session.resolve_model_params({"rc": 2000.0}) == {"rc": 2000.0}

    sim.probe("vout").read()
    sim.probe("vout").waveform(duration=1e-3, sample_rate=10_000.0)
    sim.ac(freq_range=(1.0, 10.0), nodes=["vout"], points=2)
    sim.dc_sweep(source="V1", start=0.0, stop=1.0, step=1.0, nodes=["vout"])

    assert kernel.calls == [{"rc": 1000.0}] * 4
