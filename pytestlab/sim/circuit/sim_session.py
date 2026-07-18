from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any
from typing import Literal

import numpy as np

from .analysis import bode_from_ac_result
from .analysis import impedance_deembed
from .bench import AWG
from .bench import DMM
from .bench import PSU
from .bench import BenchConfig
from .bench import PSUChannel
from .bench import Scope
from .circuit_package import ManifestConstraints
from .factories import circuit_from_netlist
from .instruments.twins import normalize_dmm_function
from .instruments.twins import reject_unsupported_dmm_function
from .noise import NoiseConfig
from .results import BodeResult
from .results import FrequencySpectrum
from .results import ImpedanceResult
from .results import SimChannelReadingResult
from .results import SweepResult
from .results import WaveformResult
from .session import Session
from .simulators import RequiredFeatures
from .simulators import UnsupportedReason
from .simulators import raise_missing_vector
from .simulators import require_capability
from .simulators.requests import AnalysisKind
from .simulators.requests import SimulationRequest
from .spice import AcSweepSpec
from .spice import DcSweepSpec
from .spice import KernelSettings
from .spice import SpiceResult
from .wiring import Connection
from .wiring import Netlist
from .wiring import NodeRef
from .wiring import WiringConfig
from .wiring import WiringRules


def _node_str(value: str | NodeRef) -> str:
    """Coerce a node reference (typed or raw string) to its SPICE name."""
    return str(value)


class PortKind(str, Enum):  # noqa: UP042 - keep str(Enum) semantics for compatibility.
    SIGNAL = "signal"
    PROBE = "probe"
    SUPPLY = "supply"
    MEASUREMENT = "measurement"
    CURRENT_MEASUREMENT = "current_measurement"


@dataclass(frozen=True)
class Port:
    hi_node: str
    lo_node: str
    kind: PortKind

    @classmethod
    def signal(cls, hi: str | NodeRef, lo: str | NodeRef = "0") -> Port:
        return cls(_node_str(hi), _node_str(lo), PortKind.SIGNAL)

    @classmethod
    def probe(cls, hi: str | NodeRef, lo: str | NodeRef = "0") -> Port:
        return cls(_node_str(hi), _node_str(lo), PortKind.PROBE)

    @classmethod
    def supply(cls, hi: str | NodeRef, lo: str | NodeRef = "0") -> Port:
        return cls(_node_str(hi), _node_str(lo), PortKind.SUPPLY)

    @classmethod
    def measurement(cls, hi: str | NodeRef, lo: str | NodeRef = "0") -> Port:
        return cls(_node_str(hi), _node_str(lo), PortKind.MEASUREMENT)

    @classmethod
    def voltage_measurement(cls, hi: str | NodeRef, lo: str | NodeRef = "0") -> Port:
        return cls.measurement(hi, lo)

    @classmethod
    def current_measurement(cls, hi: str | NodeRef, lo: str | NodeRef = "0") -> Port:
        return cls(_node_str(hi), _node_str(lo), PortKind.CURRENT_MEASUREMENT)


class SimSession:
    def __init__(
        self,
        *,
        netlist_path: Path,
        seed: int,
        noise: NoiseConfig | None,
        kernel_settings: KernelSettings | None,
    ):
        self.netlist_path = netlist_path
        self.seed = seed
        self.noise = noise
        self.kernel_settings = kernel_settings
        self._ports: dict[str, Port] = {}
        self._session: Session | None = None
        self._instrument_for_port: dict[str, str] = {}

    @classmethod
    def from_netlist(
        cls,
        netlist: str | Path | Netlist,
        *,
        seed: int = 1337,
        noise: NoiseConfig | None = None,
        kernel_settings: KernelSettings | None = None,
    ) -> SimSession:
        if isinstance(netlist, Netlist):
            if netlist.source is None:
                raise ValueError(
                    "Netlist has no source file to simulate; build it with Netlist.from_file(path)."
                )
            netlist_path: Path = netlist.source
        else:
            netlist_path = Path(netlist)
        return cls(
            netlist_path=netlist_path,
            seed=seed,
            noise=noise,
            kernel_settings=kernel_settings,
        )

    def ports(self, **port_map: Port) -> SimSession:
        self._ports.update(port_map)
        self._build_session()
        return self

    def awg(self, port_name: str) -> SimAWG:
        self._require_port_kind(port_name, PortKind.SIGNAL)
        return SimAWG(self._require_session(), self._instrument_for_port[port_name])

    def psu(
        self, port_name: str, voltage: float | None = None, current_limit: float = 1.0
    ) -> SimPSU:
        self._require_port_kind(port_name, PortKind.SUPPLY)
        proxy = SimPSU(self._require_session(), self._instrument_for_port[port_name])
        if voltage is not None:
            proxy.set(voltage=voltage, current_limit=current_limit)
        return proxy

    def scope(self, port_name: str) -> SimScope:
        self._require_port_kind(port_name, PortKind.PROBE)
        return SimScope(
            self._require_session(),
            self._instrument_for_port[port_name],
            self._ports[port_name],
        )

    def dmm(self, port_name: str) -> SimDMM:
        self._require_port_kind(port_name, (PortKind.MEASUREMENT, PortKind.CURRENT_MEASUREMENT))
        return SimDMM(
            self._require_session(),
            self._instrument_for_port[port_name],
            mode=self._ports[port_name].kind,
        )

    def probe(self, hi_node: str | NodeRef, lo_node: str | NodeRef = "0") -> SimProbe:
        session = self._require_session()
        session.validate_nodes(_node_str(hi_node), _node_str(lo_node))
        return SimProbe(session, Port.probe(hi_node, lo_node))

    def sweep(
        self,
        *,
        param_name: str,
        param_unit: str,
        values: np.ndarray | list[float],
        measure: Callable[[], dict[str, float]],
        setup: Callable[[float], Any] | None = None,
    ) -> SweepResult:
        pl = _polars()
        param_values = np.asarray(values, dtype=float)
        rows: list[dict[str, float]] = []
        for value in param_values:
            scalar = float(value)
            if setup is not None:
                setup(scalar)
            row = {param_name: scalar}
            row.update({key: float(val) for key, val in measure().items()})
            rows.append(row)
        return SweepResult(
            param_name=param_name,
            param_values=param_values,
            param_unit=param_unit,
            data=pl.DataFrame(rows),
            metadata={"rows": len(rows)},
        )

    def ac(
        self,
        *,
        freq_range: tuple[float, float],
        nodes: list[str],
        points: int = 100,
        sweep: Literal["dec", "oct", "lin"] = "dec",
    ) -> SpiceResult:
        spec = AcSweepSpec(
            sweep=sweep,
            points=int(points),
            start_hz=float(freq_range[0]),
            stop_hz=float(freq_range[1]),
        )
        session = self._require_session()
        return session.kernel.ac(
            session,
            nodes,
            spec,
            settings=session.kernel_settings,
            params=_model_params(session),
        )

    def dc_sweep(
        self,
        *,
        source: str,
        start: float,
        stop: float,
        step: float,
        nodes: list[str],
    ) -> SpiceResult:
        spec = DcSweepSpec(source=source, start=float(start), stop=float(stop), step=float(step))
        session = self._require_session()
        return session.kernel.dc_sweep(
            session,
            nodes,
            spec,
            settings=session.kernel_settings,
            params=_model_params(session),
        )

    def transient(
        self,
        *,
        duration: float,
        sample_rate: float,
        nodes: list[str],
    ) -> dict[str, WaveformResult]:
        session = self._require_session()
        record_length = _record_length(duration, sample_rate)
        result = session.kernel.transient(
            session,
            nodes,
            sample_rate=float(sample_rate),
            record_length=record_length,
            settings=session.kernel_settings,
            params=_model_params(session),
        )
        return {
            node: WaveformResult(
                time_s=result.time_s,
                voltage=np.asarray(result.node_voltages[node], dtype=float),
                sample_rate=float(sample_rate),
                instrument="session",
                metadata=dict(result.metadata),
            )
            for node in nodes
            if node in result.node_voltages
        }

    def __enter__(self) -> SimSession:
        return self

    def __exit__(self, *exc) -> None:
        return None

    def _build_session(self) -> None:
        instruments = {}
        connections = []
        self._instrument_for_port = {}
        awg_n = psu_n = scope_n = dmm_n = 1
        for name, port in self._ports.items():
            if port.kind == PortKind.SIGNAL:
                inst = f"awg{awg_n}"
                awg_n += 1
                instruments[inst] = AWG(vpp_max=10.0)
                connections.extend(
                    [
                        Connection(from_=f"{inst}.HI", to=port.hi_node),
                        Connection(from_=f"{inst}.LO", to=port.lo_node),
                    ]
                )
            elif port.kind == PortKind.SUPPLY:
                inst = f"psu{psu_n}"
                psu_n += 1
                instruments[inst] = PSU(channels=[PSUChannel(name="CH1", v_max=60.0, i_max=5.0)])
                connections.extend(
                    [
                        Connection(from_=f"{inst}.CH1.HI", to=port.hi_node),
                        Connection(from_=f"{inst}.CH1.LO", to=port.lo_node),
                    ]
                )
            elif port.kind == PortKind.PROBE:
                inst = f"scope{scope_n}"
                scope_n += 1
                instruments[inst] = Scope(channels=1)
                connections.extend(
                    [
                        Connection(from_=f"{inst}.CH1.HI", to=port.hi_node),
                        Connection(from_=f"{inst}.CH1.LO", to=port.lo_node),
                    ]
                )
            elif port.kind == PortKind.MEASUREMENT:
                inst = f"dmm{dmm_n}"
                dmm_n += 1
                instruments[inst] = DMM()
                connections.extend(
                    [
                        Connection(from_=f"{inst}.V.HI", to=port.hi_node),
                        Connection(from_=f"{inst}.V.LO", to=port.lo_node),
                    ]
                )
            elif port.kind == PortKind.CURRENT_MEASUREMENT:
                inst = f"dmm{dmm_n}"
                dmm_n += 1
                instruments[inst] = DMM()
                connections.extend(
                    [
                        Connection(from_=f"{inst}.I.HI", to=port.hi_node),
                        Connection(from_=f"{inst}.I.LO", to=port.lo_node),
                    ]
                )
            else:
                raise ValueError(f"unsupported port kind: {port.kind}")
            self._instrument_for_port[name] = inst

        bench = BenchConfig(bench_id=f"sim-{self.netlist_path.stem}", instruments=instruments)
        wiring = WiringConfig(
            connections=connections,
            rules=WiringRules(allow_output_sharing=True),
        )
        circuit = circuit_from_netlist(
            self.netlist_path,
            metadata={
                "title": self.netlist_path.stem,
                "author": "pytestlab_sim",
                "license": "UNLICENSED",
                "intended_analyses": ["op", "tran", "ac"],
            },
            constraints=ManifestConstraints(max_tran_time_s=10.0),
        )
        self._session = Session(
            circuit=circuit,
            bench=bench,
            wiring=wiring,
            seed=self.seed,
            noise=self.noise,
            kernel_settings=self.kernel_settings,
        )

    def _require_session(self) -> Session:
        if self._session is None:
            self._build_session()
        assert self._session is not None
        return self._session

    def _require_port_kind(self, port_name: str, kind: PortKind | tuple[PortKind, ...]) -> None:
        port = self._ports.get(port_name)
        if port is None:
            raise KeyError(f"unknown port: {port_name}")
        kinds = kind if isinstance(kind, tuple) else (kind,)
        if port.kind not in kinds:
            raise ValueError(
                f"port {port_name!r} is {port.kind.value}, not "
                f"{' or '.join(item.value for item in kinds)}"
            )


class SimAWG:
    def __init__(self, session: Session, instrument_id: str):
        self.session = session
        self.instrument_id = instrument_id

    @property
    def _freq(self) -> float:
        return float(self.session.awgs[self.instrument_id].state.frequency_hz)

    def sine(
        self,
        *,
        freq_hz: float,
        amplitude_vpp: float,
        offset_v: float = 0.0,
        phase_deg: float = 0.0,
    ) -> SimAWG:
        return self._set_waveform(
            "sine",
            freq_hz=freq_hz,
            amplitude_vpp=amplitude_vpp,
            offset_v=offset_v,
            phase_deg=phase_deg,
        )

    def square(
        self,
        *,
        freq_hz: float,
        amplitude_vpp: float,
        duty_cycle: float = 0.5,
        offset_v: float = 0.0,
    ) -> SimAWG:
        return self._set_waveform(
            "square",
            freq_hz=freq_hz,
            amplitude_vpp=amplitude_vpp,
            duty_cycle=duty_cycle,
            offset_v=offset_v,
        )

    def triangle(
        self,
        *,
        freq_hz: float,
        amplitude_vpp: float,
        offset_v: float = 0.0,
    ) -> SimAWG:
        return self._set_waveform(
            "triangle", freq_hz=freq_hz, amplitude_vpp=amplitude_vpp, offset_v=offset_v
        )

    def dc(self, *, level: float) -> SimAWG:
        awg = self.session.awgs[self.instrument_id]
        awg.set_state(
            waveform="dc",
            frequency_hz=0.0,
            amplitude_vpp=0.0,
            offset_v=level,
            enabled=True,
        )
        return self

    def pulse(
        self,
        *,
        freq_hz: float,
        amplitude_vpp: float,
        duty_cycle: float = 0.5,
        offset_v: float = 0.0,
    ) -> SimAWG:
        return self._set_waveform(
            "pulse",
            freq_hz=freq_hz,
            amplitude_vpp=amplitude_vpp,
            duty_cycle=duty_cycle,
            offset_v=offset_v,
        )

    def enable(self) -> SimAWG:
        awg = self.session.awgs[self.instrument_id]
        awg.set_state(enabled=True)
        return self

    def disable(self) -> SimAWG:
        awg = self.session.awgs[self.instrument_id]
        awg.set_state(enabled=False)
        return self

    def _set_waveform(self, waveform: str, **state) -> SimAWG:
        awg = self.session.awgs[self.instrument_id]
        if "freq_hz" in state:
            state["frequency_hz"] = state.pop("freq_hz")
        awg.set_state(waveform=waveform, enabled=True, **state)
        return self


class SimPSU:
    def __init__(self, session: Session, instrument_id: str):
        self.session = session
        self.instrument_id = instrument_id

    def channel(self, n: int = 1) -> PSUChannelProxy:
        return PSUChannelProxy(self.session, self.instrument_id, _channel_name(n))

    def set(self, *, voltage: float, current_limit: float = 1.0) -> SimPSU:
        self.set_voltage(voltage)
        self.set_current_limit(current_limit)
        self.enable_output()
        return self

    def set_voltage(self, voltage: float, channel: int = 1) -> SimPSU:
        psu = self.session.psus[self.instrument_id]
        psu.set_state(channel=_channel_name(channel), voltage_setpoint=voltage)
        return self

    def set_current_limit(self, amps: float, channel: int = 1) -> SimPSU:
        psu = self.session.psus[self.instrument_id]
        psu.set_state(channel=_channel_name(channel), current_limit=amps)
        return self

    def enable_output(self, channel: int = 1) -> SimPSU:
        psu = self.session.psus[self.instrument_id]
        psu.set_state(channel=_channel_name(channel), enabled=True)
        return self

    def disable_output(self, channel: int = 1) -> SimPSU:
        psu = self.session.psus[self.instrument_id]
        psu.set_state(channel=_channel_name(channel), enabled=False)
        return self

    def read_voltage(self, channel: int = 1) -> float:
        hi, lo = _mapped_terminal_pair(
            self.session,
            self.instrument_id,
            f"{_channel_name(channel)}.HI",
            f"{_channel_name(channel)}.LO",
        )
        nodes = _node_list(self.session, hi, lo)
        result = self.session.kernel.op(
            self.session,
            nodes,
            settings=self.session.kernel_settings,
            params=_model_params(self.session),
        )
        return _mean_voltage(self.session, result, hi, lo, AnalysisKind.OP)

    def read_current(self, channel: int = 1) -> float:
        key = f"{self.instrument_id}.{_channel_name(channel)}"
        require_capability(
            self.session.kernel,
            SimulationRequest(
                analysis=AnalysisKind.OP,
                source_currents=(key,),
                settings=self.session.kernel_settings,
                required=RequiredFeatures(source_currents=True, settings=True),
            ),
        )
        result = self.session.kernel.op(
            self.session,
            [],
            settings=self.session.kernel_settings,
            params=_model_params(self.session),
        )
        current = _required_vector(
            self.session,
            result.source_currents,
            vector=key,
            analysis=AnalysisKind.OP,
            reason=UnsupportedReason.SOURCE_CURRENT_UNSUPPORTED,
        )
        return float(-np.mean(current))

    def on(self, channel: int = 1) -> SimPSU:
        return self.enable_output(channel)

    def off(self, channel: int = 1) -> SimPSU:
        return self.disable_output(channel)


class PSUChannelProxy:
    def __init__(self, session: Session, instrument_id: str, channel: str):
        self.session = session
        self.instrument_id = instrument_id
        self.channel_name = channel

    def set(self, *, voltage: float, current_limit: float = 1.0) -> PSUChannelProxy:
        psu = self.session.psus[self.instrument_id]
        psu.set_state(
            channel=self.channel_name,
            voltage_setpoint=voltage,
            current_limit=current_limit,
        )
        return self

    def on(self) -> PSUChannelProxy:
        self.session.psus[self.instrument_id].set_state(channel=self.channel_name, enabled=True)
        return self

    def off(self) -> PSUChannelProxy:
        self.session.psus[self.instrument_id].set_state(channel=self.channel_name, enabled=False)
        return self

    def read_voltage(self) -> float:
        return SimPSU(self.session, self.instrument_id).read_voltage(int(self.channel_name[2:]))

    def read_current(self) -> float:
        return SimPSU(self.session, self.instrument_id).read_current(int(self.channel_name[2:]))


class SimScope:
    def __init__(self, session: Session, instrument_id: str, port: Port):
        self.session = session
        self.instrument_id = instrument_id
        self.port = port

    def trigger(self, level: float, slope: str = "POS", source: str | None = None) -> SimScope:
        scope = self.session.scopes[self.instrument_id]
        state = {"trigger_level": level, "trigger_slope": slope}
        if source is not None:
            state["trigger_source"] = source
        scope.set_state(**state)
        return self

    def coupling(self, mode: str = "DC") -> SimScope:
        self.session.scopes[self.instrument_id].set_state(coupling=mode)
        return self

    def bandwidth(self, hz: float) -> SimScope:
        self.session.scopes[self.instrument_id].set_state(bandwidth_hz=hz)
        return self

    def vertical_scale(self, v_per_div: float) -> SimScope:
        self.session.scopes[self.instrument_id].set_state(vertical_scale_v=v_per_div)
        return self

    def run(self) -> SimScope:
        self.session.scopes[self.instrument_id].set_state(enabled=True)
        return self

    def stop(self) -> SimScope:
        self.session.scopes[self.instrument_id].set_state(enabled=False)
        return self

    def capture(self, duration: float, sample_rate: float) -> WaveformResult:
        scope = self.session.scopes[self.instrument_id]
        record_length = _record_length(duration, sample_rate)
        scope.set_state(enabled=True, sample_rate=sample_rate, record_length=record_length)
        result = self.session.kernel.transient(
            self.session,
            _node_list(self.session, self.port.hi_node, self.port.lo_node),
            sample_rate=sample_rate,
            record_length=record_length,
            settings=self.session.kernel_settings,
            params=_model_params(self.session),
        )
        wave = _voltage_waveform(
            self.session,
            result,
            self.port.hi_node,
            self.port.lo_node,
            AnalysisKind.TRANSIENT,
        )
        acquired = scope.acquire(wave)
        return WaveformResult(
            time_s=np.asarray(acquired.values["t"], dtype=float),
            voltage=np.asarray(acquired.values["v"], dtype=float),
            sample_rate=sample_rate,
            instrument=self.instrument_id,
            metadata={**dict(result.metadata), **dict(acquired.metadata)},
        )

    def read_channels(
        self,
        *channels: int,
        duration: float,
        sample_rate: float,
    ) -> SimChannelReadingResult:
        channel_list = [1] if not channels else [int(ch) for ch in channels]
        if channel_list != [1]:
            raise ValueError("SimScope currently exposes one channel per probe port")
        waveform = self.capture(duration, sample_rate)
        return SimChannelReadingResult(
            channels=channel_list,
            time=waveform.time_s,
            readings={1: waveform},
            metadata=dict(waveform.metadata),
        )

    def measure_voltage_peak_to_peak(self, duration: float, sample_rate: float) -> float:
        return self.capture(duration, sample_rate).peak_to_peak()

    def measure_rms_voltage(self, duration: float, sample_rate: float) -> float:
        return self.capture(duration, sample_rate).rms()

    def bode(
        self,
        source: SimAWG,
        *,
        freq_range: tuple[float, float],
        points: int = 100,
        sweep: Literal["dec", "oct", "lin"] = "dec",
    ) -> BodeResult:
        source.enable()
        source_hi = self.session.mapping[f"{source.instrument_id}.HI"]
        nodes = _dedupe(
            _node_list(self.session, self.port.hi_node, self.port.lo_node) + [source_hi]
        )
        spec = AcSweepSpec(
            sweep=sweep,
            points=int(points),
            start_hz=freq_range[0],
            stop_hz=freq_range[1],
        )
        result = self.session.kernel.ac(
            self.session,
            nodes,
            spec,
            settings=self.session.kernel_settings,
            params=_model_params(self.session),
        )
        return bode_from_ac_result(result, input_node=source_hi, output_node=self.port.hi_node)

    def step_response(
        self,
        source: SimAWG,
        *,
        step_from: float = 0.0,
        step_to: float = 1.0,
        duration: float,
        sample_rate: float = 1e6,
    ) -> WaveformResult:
        freq = 1.0 / max(float(duration), 1e-12)
        source.pulse(
            freq_hz=freq,
            amplitude_vpp=abs(step_to - step_from),
            duty_cycle=0.5,
            offset_v=(step_to + step_from) / 2.0,
        )
        result = self.capture(duration, sample_rate)
        result.metadata.update(
            {"analysis": "step_response", "step_from": step_from, "step_to": step_to}
        )
        return result

    def thd(
        self,
        source: SimAWG,
        *,
        freq_hz: float,
        duration: float | None = None,
        sample_rate: float | None = None,
        n_harmonics: int = 7,
    ) -> FrequencySpectrum:
        if duration is None:
            duration = 10.0 / float(freq_hz)
        if sample_rate is None:
            sample_rate = max(float(freq_hz) * 100.0, float(freq_hz) * (n_harmonics + 2) * 2.5)
        source.sine(
            freq_hz=freq_hz,
            amplitude_vpp=self.session.awgs[source.instrument_id].state.amplitude_vpp,
        )
        return self.capture(duration, sample_rate).fft()

    def impedance(
        self,
        source: SimAWG,
        *,
        freq_range: tuple[float, float],
        points: int = 50,
        r_sense_ohm: float = 50.0,
    ) -> ImpedanceResult:
        source.enable()
        source_hi = self.session.mapping[f"{source.instrument_id}.HI"]
        nodes = _dedupe(
            _node_list(self.session, self.port.hi_node, self.port.lo_node) + [source_hi]
        )
        spec = AcSweepSpec(
            sweep="dec",
            points=int(points),
            start_hz=freq_range[0],
            stop_hz=freq_range[1],
        )
        result = self.session.kernel.ac(
            self.session,
            nodes,
            spec,
            settings=self.session.kernel_settings,
            params=_model_params(self.session),
        )
        vin = result.node_voltages[source_hi]
        vout = result.node_voltages[self.port.hi_node]
        h = np.divide(vout, vin, out=np.zeros_like(vout, dtype=complex), where=np.abs(vin) > 0)
        return impedance_deembed(result.scale, h, r_sense_ohm)


class SimDMM:
    def __init__(
        self,
        session: Session,
        instrument_id: str,
        *,
        mode: PortKind | None = None,
    ):
        self.session = session
        self.instrument_id = instrument_id
        self.mode = mode

    def configure(
        self,
        *,
        function: str = "DCV",
        range_v: float | None = None,
        aperture_s: float | None = None,
    ) -> SimDMM:
        normalized_function = _normalize_dmm_function(function)
        reject_unsupported_dmm_function(normalized_function)
        self._raise_if_function_incompatible(normalized_function)
        state: dict[str, Any] = {"function": normalized_function}
        if range_v is not None:
            state["range_v"] = range_v
            state["auto_range"] = False
        if aperture_s is not None:
            state["aperture_s"] = aperture_s
        self.session.dmms[self.instrument_id].set_state(**state)
        return self

    def read_dc_voltage(self) -> float:
        if self.mode == PortKind.CURRENT_MEASUREMENT:
            raise ValueError(
                f"{self.instrument_id} is wired as current-only; use read_dc_current()"
            )
        self.configure(function="DCV")
        hi, lo = _mapped_terminal_pair(self.session, self.instrument_id, "V.HI", "V.LO")
        result = self.session.kernel.op(
            self.session,
            _node_list(self.session, hi, lo),
            settings=self.session.kernel_settings,
            params=_model_params(self.session),
        )
        value = _mean_voltage(self.session, result, hi, lo, AnalysisKind.OP)
        return float(self.session.dmms[self.instrument_id].measure(value).values)

    def read_ac_voltage(self) -> float:
        if self.mode == PortKind.CURRENT_MEASUREMENT:
            raise ValueError(
                f"{self.instrument_id} is wired as current-only; use read_dc_current()"
            )
        self.configure(function="ACV")
        twin = self.session.dmms[self.instrument_id]
        freqs = [
            float(awg.state.frequency_hz)
            for awg in self.session.awgs.values()
            if getattr(awg.state, "enabled", False) and awg.state.frequency_hz > 0
        ]
        duration = max(
            float(twin.state.aperture_s),
            1.0 / min(freqs) if freqs else float(twin.state.aperture_s),
        )
        sample_rate = max(50_000.0, max(freqs) * 20.0 if freqs else 50_000.0)
        hi, lo = _mapped_terminal_pair(self.session, self.instrument_id, "V.HI", "V.LO")
        record_length = _record_length(duration, sample_rate)
        result = self.session.kernel.transient(
            self.session,
            _node_list(self.session, hi, lo),
            sample_rate=sample_rate,
            record_length=record_length,
            settings=self.session.kernel_settings,
            params=_model_params(self.session),
        )
        wave = _voltage_waveform(
            self.session,
            result,
            hi,
            lo,
            AnalysisKind.TRANSIENT,
        )
        return float(twin.measure(wave, sample_rate=sample_rate).values)

    def read_dc_current(self) -> float:
        if self.mode == PortKind.MEASUREMENT:
            raise ValueError(
                f"{self.instrument_id} is wired as voltage-only; use read_dc_voltage()"
            )
        self.configure(function="DCI")
        hi, lo = _mapped_terminal_pair(self.session, self.instrument_id, "I.HI", "I.LO")
        key = f"{self.instrument_id}.I"
        require_capability(
            self.session.kernel,
            SimulationRequest(
                analysis=AnalysisKind.OP,
                nodes=tuple(_node_list(self.session, hi, lo)),
                element_currents=(key,),
                settings=self.session.kernel_settings,
                required=RequiredFeatures(element_currents=True, settings=True),
            ),
        )
        result = self.session.kernel.op(
            self.session,
            _node_list(self.session, hi, lo),
            settings=self.session.kernel_settings,
            currents=[key],
            params=_model_params(self.session),
        )
        current = _required_vector(
            self.session,
            result.element_currents,
            vector=key,
            analysis=AnalysisKind.OP,
            reason=UnsupportedReason.ELEMENT_CURRENT_UNSUPPORTED,
        )
        value = float(np.mean(current))
        return float(self.session.dmms[self.instrument_id].measure(value).values)

    def read(self) -> float:
        if self.mode == PortKind.CURRENT_MEASUREMENT:
            function = _normalize_dmm_function(self.session.dmms[self.instrument_id].state.function)
            reject_unsupported_dmm_function(function)
            return self.read_dc_current()
        if self.mode == PortKind.MEASUREMENT:
            function = _normalize_dmm_function(self.session.dmms[self.instrument_id].state.function)
            reject_unsupported_dmm_function(function)
            self._raise_if_function_incompatible(function)
            if function == "ACV":
                return self.read_ac_voltage()
            return self.read_dc_voltage()
        function = _normalize_dmm_function(self.session.dmms[self.instrument_id].state.function)
        reject_unsupported_dmm_function(function)
        if function == "ACV":
            return self.read_ac_voltage()
        if function == "DCI":
            return self.read_dc_current()
        return self.read_dc_voltage()

    def _raise_if_function_incompatible(self, function: str) -> None:
        normalized = _normalize_dmm_function(function)
        reject_unsupported_dmm_function(normalized)
        if self.mode == PortKind.MEASUREMENT and normalized in {"DCI", "ACI"}:
            raise ValueError(
                f"{self.instrument_id} is wired as voltage-only; use read_dc_voltage()"
            )
        if self.mode == PortKind.CURRENT_MEASUREMENT and normalized in {"DCV", "ACV"}:
            raise ValueError(
                f"{self.instrument_id} is wired as current-only; use read_dc_current()"
            )


class SimProbe:
    def __init__(self, session: Session, port: Port):
        self.session = session
        self.port = port

    def read(self) -> float:
        nodes = [self.port.hi_node]
        if self.port.lo_node != self.session.wiring.ground_node:
            nodes.append(self.port.lo_node)
        result = self.session.kernel.op(
            self.session,
            nodes,
            settings=self.session.kernel_settings,
            params=_model_params(self.session),
        )
        return _mean_voltage(
            self.session,
            result,
            self.port.hi_node,
            self.port.lo_node,
            AnalysisKind.OP,
        )

    def waveform(self, duration: float, sample_rate: float) -> WaveformResult:
        record_length = _record_length(duration, sample_rate)
        result = self.session.kernel.transient(
            self.session,
            _node_list(self.session, self.port.hi_node, self.port.lo_node),
            sample_rate=sample_rate,
            record_length=record_length,
            settings=self.session.kernel_settings,
            params=_model_params(self.session),
        )
        return WaveformResult(
            time_s=result.time_s,
            voltage=_voltage_waveform(
                self.session,
                result,
                self.port.hi_node,
                self.port.lo_node,
                AnalysisKind.TRANSIENT,
            ),
            sample_rate=sample_rate,
            instrument="probe",
            metadata=dict(result.metadata),
        )


def _model_params(session: Session) -> dict[str, float]:
    resolver = getattr(session, "resolve_model_params", None)
    if callable(resolver):
        return resolver(None)
    return {}


def _polars():
    try:
        import polars as pl
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise ImportError(
            "Polars is required for SimSession.sweep(). Install polars>=1.0."
        ) from exc
    return pl


def _record_length(duration: float, sample_rate: float) -> int:
    length = int(round(float(duration) * float(sample_rate)))
    if length <= 0:
        raise ValueError("duration * sample_rate must produce at least one sample")
    return length


def _channel_name(channel: int) -> str:
    return f"CH{int(channel)}"


def _normalize_dmm_function(value: str) -> str:
    return normalize_dmm_function(value)


def _node_list(session: Session, hi: str, lo: str | None = None) -> list[str]:
    nodes = [hi]
    if lo and lo != session.wiring.ground_node and lo not in nodes:
        nodes.append(lo)
    return nodes


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    out = []
    for value in values:
        if value not in seen:
            out.append(value)
            seen.add(value)
    return out


def _mapped_terminal_pair(
    session: Session, instrument_id: str, hi_suffix: str, lo_suffix: str
) -> tuple[str, str]:
    hi = session.mapping.get(f"{instrument_id}.{hi_suffix}")
    lo = session.mapping.get(f"{instrument_id}.{lo_suffix}") or session.wiring.ground_node
    if hi is None:
        raise ValueError(f"{instrument_id}.{hi_suffix} is not wired")
    return hi, lo


def _voltage_waveform(
    session: Session,
    result: SpiceResult,
    hi: str,
    lo: str | None,
    analysis: AnalysisKind,
) -> np.ndarray:
    wave = _required_vector(
        session,
        result.node_voltages,
        vector=hi,
        analysis=analysis,
        reason=UnsupportedReason.OUTPUT_VECTOR_UNPROVEN,
    )
    if lo and not _is_ground_node(session, lo):
        wave = wave - _required_vector(
            session,
            result.node_voltages,
            vector=lo,
            analysis=analysis,
            reason=UnsupportedReason.OUTPUT_VECTOR_UNPROVEN,
        )
    return wave


def _mean_voltage(
    session: Session,
    result: SpiceResult,
    hi: str,
    lo: str | None,
    analysis: AnalysisKind,
) -> float:
    return float(np.mean(_voltage_waveform(session, result, hi, lo, analysis)))


def _required_vector(
    session: Session,
    vectors: dict[str, np.ndarray],
    *,
    vector: str,
    analysis: AnalysisKind,
    reason: UnsupportedReason,
) -> np.ndarray:
    raw = vectors.get(vector)
    values = np.asarray(raw, dtype=float) if raw is not None else np.asarray([])
    if values.size == 0:
        raise_missing_vector(
            session.kernel,
            analysis=analysis.value,
            reason=reason,
            vector=vector,
        )
    return values


def _is_ground_node(session: Session, node: str) -> bool:
    canonical = str(node).strip().lower()
    ground = str(session.wiring.ground_node).strip().lower()
    return canonical in {"0", ground}
