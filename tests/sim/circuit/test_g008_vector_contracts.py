from __future__ import annotations

import numpy as np
import pytest

from pytestlab.sim.circuit import Port
from pytestlab.sim.circuit import Session
from pytestlab.sim.circuit import SimbenchScpiBackend
from pytestlab.sim.circuit import SimSession
from pytestlab.sim.circuit import UnsupportedCapability
from pytestlab.sim.circuit import UnsupportedReason
from pytestlab.sim.circuit.bench import AWG
from pytestlab.sim.circuit.bench import DMM
from pytestlab.sim.circuit.bench import PSU
from pytestlab.sim.circuit.bench import BenchConfig
from pytestlab.sim.circuit.bench import PSUChannel
from pytestlab.sim.circuit.bench import Scope
from pytestlab.sim.circuit.factories import circuit_from_netlist
from pytestlab.sim.circuit.simulators import SimulatorCapabilities
from pytestlab.sim.circuit.spice import SpiceResult
from pytestlab.sim.circuit.wiring import Connection
from pytestlab.sim.circuit.wiring import WiringConfig

_VOLTAGE_CASES = ("scope", "psu_voltage", "dmm_dc", "dmm_ac")
_CURRENT_CASES = ("psu_current", "dmm_current")
_ALL_CASES = _VOLTAGE_CASES + _CURRENT_CASES


class VectorKernel:
    def __init__(
        self,
        *,
        op_nodes: dict[str, np.ndarray] | None = None,
        transient_nodes: dict[str, np.ndarray] | None = None,
        source_currents: dict[str, np.ndarray] | None = None,
        element_currents: dict[str, np.ndarray] | None = None,
    ) -> None:
        self.op_nodes = op_nodes or {}
        self.transient_nodes = transient_nodes or {}
        self.source_currents = source_currents or {}
        self.element_currents = element_currents or {}

    def capabilities(self) -> SimulatorCapabilities:
        return SimulatorCapabilities(
            backend="g008_fake",
            op=True,
            transient=True,
            node_voltages=True,
            source_currents=True,
            element_currents=True,
            raw_netlists=True,
            settings=True,
        )

    def supports(self, request):
        return self.capabilities().supports(request)

    def op(self, session, nodes, *, settings=None, currents=None, params=None):
        return SpiceResult(
            "op",
            np.asarray([0.0]),
            "op",
            dict(self.op_nodes),
            dict(self.source_currents),
            (),
            dict(self.element_currents),
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
        scale = np.arange(int(record_length), dtype=float) / float(sample_rate)
        return SpiceResult(
            "tran",
            scale,
            "s",
            dict(self.transient_nodes),
            {},
            (),
        )


def _circuit(tmp_path):
    path = tmp_path / "g008.cir"
    path.write_text("G008 vector contract\nRHI vhi 0 10\nRLOW vlow 0 10\n.end\n")
    return circuit_from_netlist(
        path,
        metadata={
            "title": "g008",
            "author": "pytestlab_sim",
            "license": "UNLICENSED",
            "intended_analyses": ["op", "tran"],
        },
    )


def _session(tmp_path, case: str, *, low: str = "0") -> Session:
    instruments: dict[str, PSU | AWG | DMM | Scope] = {"anchor": DMM()}
    if case.startswith("psu_"):
        instruments["psu1"] = PSU(channels=[PSUChannel(name="CH1", v_max=30.0, i_max=1.0)])
        terminal_prefix = "psu1.CH1"
    elif case.startswith("dmm_"):
        instruments["dmm1"] = DMM()
        terminal_prefix = "dmm1.I" if case == "dmm_current" else "dmm1.V"
    else:
        instruments["scope1"] = Scope(channels=1)
        terminal_prefix = "scope1.CH1"

    wiring = WiringConfig(
        connections=[
            Connection(from_=f"{terminal_prefix}.HI", to="vhi"),
            Connection(from_=f"{terminal_prefix}.LO", to=low),
            Connection(from_="anchor.I.HI", to="0"),
        ]
    )
    return Session(
        circuit=_circuit(tmp_path),
        bench=BenchConfig(bench_id=f"g008-{case}", instruments=instruments),
        wiring=wiring,
    )


def _sim_session(tmp_path, session: Session, case: str, *, low: str) -> SimSession:
    sim = SimSession.from_netlist(tmp_path / "unused.cir")
    sim._session = session
    if case.startswith("psu_"):
        instrument_id = "psu1"
        port = Port.supply("vhi", low)
    elif case == "dmm_current":
        instrument_id = "dmm1"
        port = Port.current_measurement("vhi", low)
    elif case.startswith("dmm_"):
        instrument_id = "dmm1"
        port = Port.measurement("vhi", low)
    else:
        instrument_id = "scope1"
        port = Port.probe("vhi", low)
    sim._instrument_for_port = {"target": instrument_id}
    sim._ports = {"target": port}
    return sim


def _invoke_scpi(session: Session, case: str) -> object:
    instrument_id = case.split("_", 1)[0] + "1"
    backend = SimbenchScpiBackend(session=session, instrument_id=instrument_id)
    if case == "scope":
        backend.write("RUN")
        backend.write("WAV:POIN 4")
        return backend.write("DIGITIZE CHANnel1")
    if case == "psu_voltage":
        return backend.query("MEAS:VOLT?")
    if case == "psu_current":
        return backend.query("MEAS:CURR?")
    if case == "dmm_ac":
        backend.write('SENS:FUNC "ACV"')
    elif case == "dmm_current":
        backend.write('SENS:FUNC "DCI"')
    return backend.query("READ?")


def _invoke_direct(sim: SimSession, case: str) -> object:
    if case == "scope":
        return sim.scope("target").capture(duration=4e-6, sample_rate=1_000_000.0)
    if case == "psu_voltage":
        return sim.psu("target").read_voltage()
    if case == "psu_current":
        return sim.psu("target").read_current()
    if case == "dmm_dc":
        return sim.dmm("target").read_dc_voltage()
    if case == "dmm_ac":
        return sim.dmm("target").read_ac_voltage()
    return sim.dmm("target").read_dc_current()


def _invoke_api(tmp_path, session: Session, case: str, api: str, *, low: str) -> object:
    if api == "scpi":
        return _invoke_scpi(session, case)
    return _invoke_direct(_sim_session(tmp_path, session, case, low=low), case)


def _reason_for(case: str) -> UnsupportedReason:
    if case == "psu_current":
        return UnsupportedReason.SOURCE_CURRENT_UNSUPPORTED
    if case == "dmm_current":
        return UnsupportedReason.ELEMENT_CURRENT_UNSUPPORTED
    return UnsupportedReason.OUTPUT_VECTOR_UNPROVEN


def _kernel_for(case: str, *, vector: np.ndarray | None, low: np.ndarray | None = None):
    if case == "psu_current":
        vectors = {} if vector is None else {"psu1.CH1": vector}
        return VectorKernel(source_currents=vectors)
    if case == "dmm_current":
        vectors = {} if vector is None else {"dmm1.I": vector}
        return VectorKernel(element_currents=vectors)

    nodes = {} if vector is None else {"vhi": vector}
    if low is not None:
        nodes["vlow"] = low
    if case in {"scope", "dmm_ac"}:
        return VectorKernel(transient_nodes=nodes)
    return VectorKernel(op_nodes=nodes)


@pytest.mark.parametrize("case", _VOLTAGE_CASES)
@pytest.mark.parametrize("api", ("scpi", "direct"))
def test_mapped_non_ground_low_requires_a_returned_vector(tmp_path, case: str, api: str) -> None:
    session = _session(tmp_path, case, low="vlow")
    session.kernel = _kernel_for(case, vector=np.zeros(4))

    with pytest.raises(UnsupportedCapability) as excinfo:
        _invoke_api(tmp_path, session, case, api, low="vlow")

    assert UnsupportedReason.OUTPUT_VECTOR_UNPROVEN in excinfo.value.reasons
    assert "vlow" in excinfo.value.details[0]


@pytest.mark.parametrize("case", _ALL_CASES)
@pytest.mark.parametrize("vector_state", ("missing", "empty"))
@pytest.mark.parametrize("api", ("scpi", "direct"))
def test_missing_and_empty_vectors_are_rejected(
    tmp_path,
    case: str,
    vector_state: str,
    api: str,
) -> None:
    session = _session(tmp_path, case)
    vector = None if vector_state == "missing" else np.asarray([])
    session.kernel = _kernel_for(case, vector=vector)

    with pytest.raises(UnsupportedCapability) as excinfo:
        _invoke_api(tmp_path, session, case, api, low="0")

    assert _reason_for(case) in excinfo.value.reasons


@pytest.mark.parametrize("case", _ALL_CASES)
@pytest.mark.parametrize("api", ("scpi", "direct"))
def test_explicit_ground_and_nonempty_zero_vectors_are_valid(
    tmp_path,
    case: str,
    api: str,
) -> None:
    session = _session(tmp_path, case)
    session.kernel = _kernel_for(case, vector=np.zeros(4))

    result = _invoke_api(tmp_path, session, case, api, low="0")

    if isinstance(result, str | float):
        assert np.isfinite(float(result))
