from __future__ import annotations

import random
import re
from dataclasses import asdict
from typing import Any
from typing import cast

import numpy as np

from .determinism import seed_from_context
from .instruments.base import InstrumentTwin
from .instruments.base import MeasurementResult
from .instruments.twins import AWGTwin
from .instruments.twins import DMMTwin
from .instruments.twins import PSUTwin
from .instruments.twins import ScopeTwin
from .instruments.twins import normalize_dmm_function
from .instruments.twins import reject_unsupported_dmm_function
from .noise import apply_layer2_noise
from .session import Session
from .simulators import RequiredFeatures
from .simulators import UnsupportedReason
from .simulators import raise_missing_vector
from .simulators import require_capability
from .simulators.requests import AnalysisKind
from .simulators.requests import SimulationRequest


class SimbenchScpiBackend:
    """Minimal SCPI handler that routes commands to SimBench instrument twins.

    The backend implements the ``InstrumentIO`` protocol surface that
    ``pytestlab`` instrument drivers expect: ``connect``, ``disconnect``,
    ``write``, ``query``, ``query_raw``, ``set_timeout`` and ``get_timeout``.

    A backend instance is bound to a ``Session`` and a concrete instrument ID.
    Measurements are always derived from the simulation kernel and instrument
    twin models (no stubbed fallbacks).
    """

    def __init__(
        self,
        session: Session,
        instrument_id: str,
        *,
        timeout_ms: int = 5_000,
    ) -> None:
        self.session = session
        self.instrument_id = instrument_id
        self.timeout_ms = timeout_ms
        self._error_queue: list[tuple[int, str]] = []
        inst = session.bench.instruments[instrument_id]
        self.kind = inst.kind
        self._scope_selected_source: str = "CHANnel1"
        self._scope_captures: dict[str, bytes] = {}
        self._scope_preambles: dict[str, list[str]] = {}
        self._scope_metadata: dict[str, dict[str, object]] = {}
        self._psu_selected_channel: str | None = None
        self._bind_twin()

    def _bind_twin(self) -> None:
        if self.kind == "PSU":
            self.twin: PSUTwin | DMMTwin | ScopeTwin | AWGTwin = self.session.psus[
                self.instrument_id
            ]
        elif self.kind == "DMM":
            self.twin = self.session.dmms[self.instrument_id]
        elif self.kind == "SCOPE":
            self.twin = self.session.scopes[self.instrument_id]
        elif self.kind == "AWG":
            self.twin = self.session.awgs[self.instrument_id]
        else:
            raise ValueError(f"Unsupported instrument kind: {self.kind}")

    # InstrumentIO surface -------------------------------------------------
    def connect(self) -> None:  # pragma: no cover - no-op
        return

    def disconnect(self) -> None:  # pragma: no cover - no-op
        return

    def close(self) -> None:  # pragma: no cover - alias
        self.disconnect()

    def set_timeout(self, timeout_ms: int) -> None:
        self.timeout_ms = timeout_ms

    def get_timeout(self) -> int:
        return self.timeout_ms

    def write(self, cmd: str) -> None:
        self._handle_command(cmd.strip(), expect_response=False)

    def query(self, cmd: str, delay: float | None = None) -> str:
        if delay:
            import time

            time.sleep(delay)
        resp = self._handle_command(cmd.strip(), expect_response=True)
        if isinstance(resp, bytes):
            return resp.decode()
        return "" if resp is None else str(resp)

    def query_raw(self, cmd: str, delay: float | None = None) -> bytes:
        if delay:
            import time

            time.sleep(delay)
        resp = self._handle_command(cmd.strip(), expect_response=True)
        if resp is None:
            return b""
        if isinstance(resp, bytes):
            return resp
        return str(resp).encode()

    # Command handlers -----------------------------------------------------
    def _handle_command(self, cmd: str, expect_response: bool) -> str | bytes | None:
        upper = cmd.upper()
        normalized = upper.lstrip(":")
        if normalized == "*IDN?":
            return f"SimBench,{self.kind},{self.instrument_id},1.0"
        if normalized == "*CLS":
            self._clear_errors()
            return ""
        if normalized == "*RST":
            self._reset_state()
            return None
        if normalized == "*OPC?":
            return "1"
        if normalized.startswith("SYST:ERR") or normalized.startswith("SYSTEM:ERROR"):
            return self._pop_error()

        if self.kind == "DMM":
            return self._handle_dmm(normalized, expect_response)
        if self.kind == "PSU":
            return self._handle_psu(normalized, expect_response)
        if self.kind == "AWG":
            return self._handle_awg(normalized, expect_response)
        if self.kind == "SCOPE":
            return self._handle_scope(cmd, normalized, expect_response)
        raise ValueError(f"Unhandled command {cmd}")

    def _handle_dmm(self, cmd: str, expect_response: bool) -> str:
        twin: DMMTwin = self.twin  # type: ignore[assignment]
        if cmd.startswith("SYSTEM:ERROR"):
            return self._pop_error()
        if cmd.startswith("SENSE:FUNC") or cmd.startswith("SENS:FUNC"):
            _, value = cmd.split(" ", 1)
            twin.set_state(function=value.strip('"'))
            self._emit_warnings(twin)
            return ""
        if ":RANGE:AUTO" in cmd:
            tail = cmd.split(" ", 1)[-1].strip().upper()
            state = tail.split(",", 1)[0].strip().upper()
            twin.set_state(auto_range=state in {"ON", "1", "TRUE"})
            self._emit_warnings(twin)
            return ""
        if ":RESOLUTION" in cmd:
            tail = cmd.split(" ", 1)[-1].strip()
            try:
                resolution = float(tail.split(",", 1)[0])
            except ValueError:
                resolution = twin.state.resolution_digits
            twin.set_state(resolution_digits=resolution)
            self._emit_warnings(twin)
            return ""
        if ":APER" in cmd or ":APERTURE" in cmd:
            tail = cmd.split(" ", 1)[-1].strip()
            try:
                aperture = float(tail.split(",", 1)[0])
            except ValueError:
                aperture = twin.state.aperture_s
            twin.set_state(aperture_s=aperture)
            self._emit_warnings(twin)
            return ""
        if ":NPLC" in cmd:
            tail = cmd.split(" ", 1)[-1].strip()
            try:
                nplc = float(tail.split(",", 1)[0])
            except ValueError:
                nplc = 1.0
            line_freq = float(getattr(twin.cfg, "line_freq_hz", 50.0))
            aperture = nplc / line_freq if line_freq > 0 else twin.state.aperture_s
            twin.set_state(aperture_s=aperture)
            self._emit_warnings(twin)
            return ""
        if cmd.startswith("CONF"):
            self._dmm_configure_command_function(cmd)
            return f"{twin.state.function} {twin.state.range_v},0.0001"
        if cmd.startswith("MEAS") or cmd == "READ?":
            requested_function = self._dmm_measure_command_function(cmd)
            if requested_function:
                previous_state = asdict(twin.get_state())
                twin.set_state(function=requested_function)
                try:
                    result = self._sample_dmm()
                finally:
                    twin.set_state(**previous_state)
                return f"{result.values:.6f}"
            result = self._sample_dmm()
            return f"{result.values:.6f}"
        raise ValueError(f"Unsupported DMM command: {cmd}")

    def _dmm_measure_command_function(self, cmd: str) -> str | None:
        if cmd in {"MEAS?", "READ?"}:
            return None
        if not cmd.startswith("MEAS:"):
            raise ValueError(f"Unsupported DMM command: {cmd}")
        requested = cmd.rstrip("?").removeprefix("MEAS:")
        normalized = self._normalize_dmm_command_function(requested, cmd)
        reject_unsupported_dmm_function(normalized)
        return normalized

    def _dmm_configure_command_function(self, cmd: str) -> str | None:
        if cmd == "CONF" or cmd == "CONF?":
            return None
        if not cmd.startswith("CONF:"):
            raise ValueError(f"Unsupported DMM command: {cmd}")
        requested = cmd.rstrip("?").removeprefix("CONF:")
        normalized = self._normalize_dmm_command_function(requested, cmd)
        reject_unsupported_dmm_function(normalized)
        return normalized

    def _normalize_dmm_command_function(self, requested: str, cmd: str) -> str:
        if requested.startswith("VOLT:DC"):
            requested = "VOLT:DC"
        elif requested.startswith("VOLT:AC"):
            requested = "VOLT:AC"
        elif requested.startswith("CURR:DC"):
            requested = "CURR:DC"
        elif requested.startswith("CURR:AC"):
            requested = "CURR:AC"
        elif requested.startswith("DCV"):
            requested = "DCV"
        elif requested.startswith("ACV"):
            requested = "ACV"
        elif requested.startswith("DCI"):
            requested = "DCI"
        elif requested.startswith("ACI"):
            requested = "ACI"
        else:
            raise ValueError(f"Unsupported DMM command: {cmd}")
        return normalize_dmm_function(requested)

    def _handle_psu(self, cmd: str, expect_response: bool) -> str:
        twin: PSUTwin = self.twin  # type: ignore[assignment]
        head, _, tail = cmd.partition(" ")
        is_query = head.endswith("?")
        base = head.rstrip("?")

        def _first_float(arg: str) -> float:
            value = arg.split(",", 1)[0].strip()
            return float(value)

        if base in {"INST:NSEL", "INST:SEL"} and not is_query:
            channel = tail.split(",", 1)[0].strip()
            if channel.isdigit():
                channel = f"CH{channel}"
            self._psu_selected_channel = channel
            twin.set_state(selected_channel=channel)
            return ""

        channel = self._psu_selected_channel or self._psu_primary_channel_name()

        if base in {"VOLT", "VOLTAGE"} and not is_query:
            twin.set_state(channel=channel, voltage_setpoint=_first_float(tail))
            self._emit_warnings(twin)
            return ""
        if base in {"CURR", "CURR:LEV", "CURRENT"} and not is_query:
            twin.set_state(channel=channel, current_limit=_first_float(tail))
            self._emit_warnings(twin)
            return ""
        if base.startswith("OUTP") and not is_query:
            state = tail.split(",", 1)[0].strip().upper()
            twin.set_state(channel=channel, enabled=state in {"ON", "1", "TRUE"})
            self._emit_warnings(twin)
            return ""

        if base == "MEAS:VOLT" and is_query:
            measured = self._spice_psu_readback(kind="voltage", channel=channel)
            if measured is not None:
                return f"{measured:.6f}"
            return f"{twin.measure(channel=channel).values['voltage']:.6f}"
        if base == "MEAS:CURR" and is_query:
            measured = self._spice_psu_readback(kind="current", channel=channel)
            if measured is not None:
                return f"{measured:.6f}"
            return f"{twin.measure(channel=channel).values['current']:.6f}"
        if base in {"OUTP:STAT", "OUTP"} and is_query:
            state = twin.state.channels.get(channel)
            return "1" if state and state.enabled else "0"

        raise ValueError(f"Unsupported PSU command: {cmd}")

    def _handle_awg(self, cmd: str, expect_response: bool) -> str:
        twin: AWGTwin = self.twin  # type: ignore[assignment]
        head, _, tail = cmd.partition(" ")
        is_query = head.endswith("?")
        base = head.rstrip("?")

        def _first_float(arg: str) -> float:
            value = arg.split(",", 1)[0].strip()
            return float(value)

        def _waveform_name(scpi_value: str) -> str:
            normalized = scpi_value.strip().strip('"').upper()
            mapping = {
                "SIN": "sine",
                "SINUSOID": "sine",
                "SINE": "sine",
                "SQU": "square",
                "SQUARE": "square",
                "RAMP": "triangle",
                "TRI": "triangle",
                "TRIANGLE": "triangle",
                "DC": "dc",
            }
            return mapping.get(normalized, normalized.lower())

        if base.endswith(":FUNC") or base.endswith(":FUNCTION") or base == "FUNC":
            if is_query:
                return twin.state.waveform
            twin.set_state(waveform=_waveform_name(tail))
            self._emit_warnings(twin)
            return ""

        if base.endswith(":FREQ") or base.endswith(":FREQUENCY") or base == "FREQ":
            if is_query:
                return f"{twin.state.frequency_hz:.12g}"
            twin.set_state(frequency_hz=_first_float(tail))
            self._emit_warnings(twin)
            return ""

        if base.endswith(":VOLT:UNIT") or base.endswith(":VOLTAGE:UNIT"):
            if is_query:
                return str(getattr(twin.state, "voltage_unit", "VPP"))
            twin.set_state(voltage_unit=tail.split(",", 1)[0].strip().upper())
            self._emit_warnings(twin)
            return ""

        if (
            base.endswith(":VOLT:OFFS")
            or base.endswith(":VOLT:OFFSET")
            or base.endswith(":VOLTAGE:OFFSET")
        ):
            if is_query:
                return f"{twin.state.offset_v:.12g}"
            twin.set_state(offset_v=_first_float(tail))
            self._emit_warnings(twin)
            return ""

        if base.endswith(":VOLT") or base.endswith(":VOLTAGE") or base == "VOLT":
            if is_query:
                return f"{twin.state.amplitude_vpp:.12g}"
            twin.set_state(amplitude_vpp=_first_float(tail))
            self._emit_warnings(twin)
            return ""

        if base.startswith("OUTP") and not base.endswith(":LOAD"):
            if is_query:
                return "1" if getattr(twin.state, "enabled", False) else "0"
            state = tail.split(",", 1)[0].strip().upper()
            twin.set_state(enabled=state in {"ON", "1", "TRUE"})
            self._emit_warnings(twin)
            return ""

        raise ValueError(f"Unsupported AWG command: {cmd}")

    def _handle_scope(self, raw_cmd: str, cmd: str, expect_response: bool) -> str | bytes:
        twin: ScopeTwin = self.twin  # type: ignore[assignment]

        cmd = cmd.strip()
        head, _, tail = cmd.partition(" ")
        is_query = head.endswith("?")
        base = head.rstrip("?")

        def _first_float(arg: str) -> float:
            value = arg.split(",", 1)[0].strip()
            return float(value)

        if base == "RUN" and not is_query:
            twin.set_state(enabled=True)
            self._emit_warnings(twin)
            return ""
        if base == "STOP" and not is_query:
            twin.set_state(enabled=False)
            self._emit_warnings(twin)
            return ""

        if base == "TIMEBASE:SCALE":
            if is_query:
                return f"{twin.state.timebase_s:.12g}"
            twin.set_state(timebase_s=_first_float(tail))
            self._emit_warnings(twin)
            return ""

        if base == "TIMEBASE:POSITION":
            if is_query:
                return f"{getattr(self, '_scope_timebase_position_s', 0.0):.12g}"
            self._scope_timebase_position_s = _first_float(tail)
            return ""

        if base == "ACQUIRE:SRATE":
            if is_query:
                return f"{twin.state.sample_rate:.12g}"
            requested = tail.split(",", 1)[0].strip().upper()
            if requested in {"MAX", "AUTO"}:
                if requested == "MAX":
                    cfg = self.session.bench.instruments.get(self.instrument_id)
                    max_rate = float(getattr(cfg, "sample_rate_sps_max", twin.state.sample_rate))
                    twin.set_state(sample_rate=max_rate)
                    self._emit_warnings(twin)
                return ""
            twin.set_state(sample_rate=_first_float(tail))
            self._emit_warnings(twin)
            return ""

        if base.startswith("TRIGGER:EDGE:LEVEL") and not is_query:
            twin.set_state(trigger_level=_first_float(tail))
            self._emit_warnings(twin)
            return ""

        if base.startswith("TRIGGER:EDGE:SOURCE") and not is_query:
            source = tail.split(",", 1)[0].strip().upper()
            source = source.replace("CHANNEL", "CH")
            twin.set_state(trigger_source=source)
            self._emit_warnings(twin)
            return ""

        if base.startswith("TRIGGER:EDGE:SLOPE") and not is_query:
            slope = tail.split(",", 1)[0].strip().upper()
            twin.set_state(trigger_slope=slope)
            self._emit_warnings(twin)
            return ""

        if base.startswith("CHANNEL") or base.startswith("CHAN"):
            if base.endswith(":SCALE") and not is_query:
                twin.set_state(vertical_scale_v=_first_float(tail))
                self._emit_warnings(twin)
                return ""
            if base.endswith(":OFFS") and not is_query:
                twin.set_state(vertical_offset_v=_first_float(tail))
                self._emit_warnings(twin)
                return ""
            if base.endswith(":COUPLING") and not is_query:
                twin.set_state(coupling=tail.split(",", 1)[0].strip().upper())
                self._emit_warnings(twin)
                return ""

        if base == "WAVEFORM:SOURCE":
            if is_query:
                return self._scope_selected_source
            self._scope_selected_source = tail.strip()
            return ""

        if base == "WAVEFORM:POINTS":
            if is_query:
                return str(twin.state.record_length)
            requested = tail.split(",", 1)[0].strip().upper()
            if requested == "MAX":
                twin.set_state(record_length=twin.max_record_length)
                self._emit_warnings(twin)
                return ""
            twin.set_state(record_length=int(float(requested)))
            self._emit_warnings(twin)
            return ""

        if base in {"WAVEFORM:POINTS:MODE", "WAVEFORM:FORMAT"}:
            # Configuration hints for waveform readout.
            return ""

        if base == "DIGITIZE" and not is_query:
            sources = [s.strip() for s in tail.split(",") if s.strip()] if tail else []
            if not sources:
                sources = [self._scope_selected_source]
            self._capture_scope_waveform(twin, sources)
            return ""

        if base == "WAVEFORM:DATA" and is_query:
            source = self._scope_selected_source
            payload_bytes = self._scope_captures.get(source)
            if payload_bytes is None:
                self._push_error(-221, "No capture available")
                return self._pop_error().encode()
            length_str = str(len(payload_bytes))
            header = f"#{len(length_str)}{length_str}".encode()
            return header + payload_bytes

        if base == "WAVEFORM:PREAMBLE" and is_query:
            source = self._scope_selected_source
            preamble = self._scope_preambles.get(source)
            if preamble is None:
                self._push_error(-221, "No preamble available")
                return self._pop_error()
            return ",".join(preamble)

        raise ValueError(f"Unsupported scope command: {raw_cmd}")

    # Helpers --------------------------------------------------------------
    def _capture_scope_waveform(self, twin: ScopeTwin, sources: list[str]) -> None:
        if not twin.state.enabled:
            self._push_error(-221, "scope stopped; send RUN before DIGITIZE")
            return

        sample_rate = float(twin.state.sample_rate)
        record_length = int(twin.state.record_length)
        # Ensure enough time-span for low-frequency captures.
        enabled_freqs = [
            float(awg.state.frequency_hz)
            for awg in self.session.awgs.values()
            if getattr(awg.state, "enabled", False) and float(awg.state.frequency_hz) > 0
        ]
        if enabled_freqs and sample_rate > 0:
            cycles = 5.0
            required = int(round(cycles * sample_rate / min(enabled_freqs)))
            record_length = max(record_length, required)
        runtime = self._runtime_state()
        runtime["last_scope"] = {
            "sample_rate": sample_rate,
            "record_length": record_length,
        }

        nodes_by_source: dict[str, tuple[str | None, str | None]] = {}
        nodes_for_spice: list[str] = []
        for source in sources:
            node_hi, node_lo = self._scope_nodes_for_source(source)
            if not node_hi and not node_lo:
                continue
            nodes_by_source[source] = (node_hi, node_lo)
            for node in (node_hi, node_lo):
                if node and node not in nodes_for_spice:
                    nodes_for_spice.append(node)

        spice = None
        if nodes_for_spice and sample_rate > 0 and record_length > 0:
            spice = self.session.kernel.transient(
                self.session,
                nodes_for_spice,
                sample_rate=sample_rate,
                record_length=record_length,
                settings=self.session.kernel_settings,
                params=_model_params(self.session),
            )
            runtime.setdefault("spice", {})["currents"] = spice.source_currents
            runtime.setdefault("spice", {})["metadata"] = spice.metadata

        trigger_channel = self._scope_channel_index(twin.state.trigger_source) or 1
        trigger_source = None
        for source in sources:
            if self._scope_channel_index(source) == trigger_channel:
                trigger_source = source
                break
        if trigger_source is None and sources:
            trigger_source = sources[0]
        trigger_index = None
        if trigger_source:
            trig_hi, trig_lo = nodes_by_source.get(trigger_source, (None, None))
            if trig_hi:
                trig_wave = self._resolve_scope_waveform(spice, trig_hi, trig_lo, record_length)
                trig_att = self._probe_attenuation_for_source(trigger_source)
                trigger_index = twin.compute_trigger_index(
                    trig_wave,
                    probe_attenuation=trig_att,
                )

        for source in sources:
            node_hi, node_lo = nodes_by_source.get(source, (None, None))
            volts = self._resolve_scope_waveform(spice, node_hi, node_lo, record_length)
            attenuation = self._probe_attenuation_for_source(source)
            processed = twin.acquire(
                volts,
                probe_attenuation=attenuation,
                trigger_index=trigger_index,
            )
            processed_volts = np.asarray(processed.values["v"], dtype=float)
            processed_volts = np.asarray(
                apply_layer2_noise(
                    processed_volts,
                    config=self.session.noise,
                    rng=self.session.noise_rng,
                    time_axis=processed.values.get("t"),
                ),
                dtype=float,
            )
            scale = twin.state.vertical_scale_v * attenuation
            raw_bytes, preamble = _encode_scope_bytes(
                processed_volts,
                sample_rate=sample_rate,
                vertical_scale_v=scale,
                vertical_offset_v=twin.state.vertical_offset_v,
            )
            self._scope_captures[source] = raw_bytes
            self._scope_preambles[source] = preamble
            self._scope_metadata[source] = processed.metadata

            if node_hi:
                runtime.setdefault("node_captures", {})[node_hi] = processed_volts

    def _sample_dmm(self) -> MeasurementResult:
        twin: DMMTwin = self.twin  # type: ignore[assignment]
        seed = seed_from_context(
            base_seed=self.session.seed,
            instrument_id=self.instrument_id,
            kind="dmm",
            state=twin.get_state().__dict__,
        )
        twin.random = random.Random(seed)
        reject_unsupported_dmm_function(twin.state.function)
        if twin.state.function == "DCI":
            return self._with_measurement_noise(self._sample_dmm_current(twin))

        hi, lo = self._dmm_voltage_nodes()
        if not hi:
            return self._with_measurement_noise(twin.measure(0.0))

        if twin.state.function == "ACV":
            sample_rate, record_length = self._dmm_transient_plan(twin)
            nodes = [hi]
            if lo:
                nodes.append(lo)
            spice = self.session.kernel.transient(
                self.session,
                nodes,
                sample_rate=sample_rate,
                record_length=record_length,
                settings=self.session.kernel_settings,
                params=_model_params(self.session),
            )
            v_hi = spice.node_voltages.get(hi)
            if v_hi is None:
                return self._with_measurement_noise(twin.measure(0.0))
            if lo:
                v_lo = spice.node_voltages.get(lo)
                if v_lo is not None:
                    v_hi = v_hi - v_lo
            return self._with_measurement_noise(twin.measure(v_hi, sample_rate=sample_rate))

        nodes = [hi]
        if lo:
            nodes.append(lo)
        spice = self.session.kernel.op(
            self.session,
            nodes,
            settings=self.session.kernel_settings,
            params=_model_params(self.session),
        )
        v_hi = spice.node_voltages.get(hi)
        if v_hi is None or not v_hi.size:
            return self._with_measurement_noise(twin.measure(0.0))
        if lo:
            v_lo = spice.node_voltages.get(lo)
            if v_lo is not None:
                v_hi = v_hi - v_lo
        return self._with_measurement_noise(twin.measure(float(np.mean(v_hi))))

    def _sample_dmm_current(self, twin: DMMTwin) -> MeasurementResult:
        hi, lo = self._dmm_current_nodes()
        if not hi or not lo:
            raise ValueError(f"{self.instrument_id} current terminals are not wired")
        nodes = [hi, lo] if lo else [hi]
        element_key = f"{self.instrument_id}.I"
        require_capability(
            self.session.kernel,
            SimulationRequest(
                analysis=AnalysisKind.OP,
                nodes=tuple(nodes),
                element_currents=(element_key,),
                settings=self.session.kernel_settings,
                required=RequiredFeatures(element_currents=True, settings=True),
            ),
        )
        spice = self.session.kernel.op(
            self.session,
            nodes,
            settings=self.session.kernel_settings,
            currents=[element_key],
            params=_model_params(self.session),
        )
        current = spice.element_currents.get(element_key)
        if current is None or not current.size:
            raise_missing_vector(
                self.session.kernel,
                analysis=AnalysisKind.OP.value,
                reason=UnsupportedReason.ELEMENT_CURRENT_UNSUPPORTED,
                vector=element_key,
            )
            return twin.measure(0.0)
        # ngspice defines i(R) as current flowing from node1 to node2.
        return twin.measure(float(np.mean(current)))

    def _with_measurement_noise(self, result: MeasurementResult) -> MeasurementResult:
        if isinstance(result.values, int | float | np.floating):
            return MeasurementResult(
                values=apply_layer2_noise(
                    float(result.values),
                    config=self.session.noise,
                    rng=self.session.noise_rng,
                ),
                units=result.units,
                metadata=result.metadata,
            )
        return result

    def _spice_psu_readback(self, *, kind: str, channel: str) -> float | None:
        """Return PSU voltage/current based on the simulation kernel."""
        psu_id = self.instrument_id
        channel_name = channel or self._psu_primary_channel_name()
        seed = seed_from_context(
            base_seed=self.session.seed,
            instrument_id=psu_id,
            kind=f"psu_{kind}",
            state=self.twin.get_state().__dict__,
        )
        self.twin.random = random.Random(seed)
        hi = self.session.mapping.get(f"{psu_id}.{channel_name}.HI")
        if not hi:
            return None
        lo = (
            self.session.mapping.get(f"{psu_id}.{channel_name}.LO")
            or self.session.wiring.ground_node
        )

        nodes: list[str] = [hi]
        if lo and lo not in nodes:
            nodes.append(lo)

        require_capability(
            self.session.kernel,
            SimulationRequest(
                analysis=AnalysisKind.OP,
                nodes=tuple(nodes),
                source_currents=(f"{psu_id}.{channel_name}",) if kind == "current" else (),
                settings=self.session.kernel_settings,
                required=RequiredFeatures(
                    source_currents=kind == "current",
                    settings=True,
                ),
            ),
        )

        spice = self.session.kernel.op(
            self.session,
            nodes,
            settings=self.session.kernel_settings,
            params=_model_params(self.session),
        )

        if kind == "voltage":
            v_hi = spice.node_voltages.get(hi)
            if v_hi is None:
                return None
            v_lo = spice.node_voltages.get(lo) if lo in spice.node_voltages else None
            if v_lo is None:
                return float(np.mean(v_hi))
            return float(np.mean(v_hi - v_lo))

        if kind == "current":
            key = f"{psu_id}.{channel_name}"
            current = spice.source_currents.get(key)
            if current is None:
                raise_missing_vector(
                    self.session.kernel,
                    analysis=AnalysisKind.OP.value,
                    reason=UnsupportedReason.SOURCE_CURRENT_UNSUPPORTED,
                    vector=key,
                )
                return None
            # ngspice defines i(V) as current entering the positive terminal of the source.
            return float(-np.mean(current))

        raise ValueError(f"Unknown PSU readback kind: {kind}")

    def _psu_primary_channel_name(self) -> str:
        inst = self.session.bench.instruments.get(self.instrument_id)
        channels = getattr(inst, "channels", None) if inst is not None else None
        if channels:
            name = getattr(channels[0], "name", None)
            if name:
                return str(name)
        return "CH1"

    def _reset_state(self) -> None:
        # Re-instantiate the twin state for deterministic reset
        self._bind_twin()
        if hasattr(self.twin, "state"):
            state_type = type(self.twin.state)
            cast(Any, self.twin).state = state_type()
        self._scope_selected_source = "CHANnel1"
        self._scope_captures.clear()
        self._scope_preambles.clear()
        self._scope_metadata.clear()
        self._clear_errors()

    def _runtime_state(self) -> dict[str, Any]:
        state = getattr(self.session, "_simbench_runtime", None)
        if not isinstance(state, dict):
            state = {}
            cast(Any, self.session)._simbench_runtime = state
        return state

    def _dmm_voltage_nodes(self) -> tuple[str | None, str | None]:
        hi = self.session.mapping.get(f"{self.instrument_id}.V.HI")
        lo = self.session.mapping.get(f"{self.instrument_id}.V.LO")
        return hi, lo

    def _dmm_current_nodes(self) -> tuple[str | None, str | None]:
        hi = self.session.mapping.get(f"{self.instrument_id}.I.HI")
        lo = self.session.mapping.get(f"{self.instrument_id}.I.LO")
        return hi, lo

    def _scope_nodes_for_source(self, source: str) -> tuple[str | None, str | None]:
        match = re.search(r"(?:CHAN(?:NEL)?|CH)(\d+)", source.strip(), flags=re.IGNORECASE)
        if not match:
            return None, None
        ch = match.group(1)
        hi = self.session.mapping.get(f"{self.instrument_id}.CH{ch}.HI")
        lo = self.session.mapping.get(f"{self.instrument_id}.CH{ch}.LO")
        return hi, lo

    @staticmethod
    def _scope_channel_index(value: str | None) -> int | None:
        if not value:
            return None
        match = re.search(r"(?:CHAN(?:NEL)?|CH)(\d+)", value.strip(), flags=re.IGNORECASE)
        if not match:
            return None
        return int(match.group(1))

    def _probe_attenuation_for_source(self, source: str) -> float:
        match = re.search(r"(?:CHAN(?:NEL)?|CH)(\d+)", source.strip(), flags=re.IGNORECASE)
        if not match:
            return 1.0
        ch = match.group(1)
        terminal = f"{self.instrument_id}.CH{ch}.HI"
        probe = self.session.wiring.probe_model_for(terminal)
        if probe and probe.attenuation:
            return float(probe.attenuation)
        return 1.0

    @staticmethod
    def _resolve_scope_waveform(
        spice,
        node_hi: str | None,
        node_lo: str | None,
        record_length: int,
    ) -> np.ndarray:
        volts: np.ndarray | None = None
        if spice is not None and node_hi:
            v_hi = spice.node_voltages.get(node_hi)
            if v_hi is not None:
                if node_lo:
                    v_lo = spice.node_voltages.get(node_lo)
                    if v_lo is not None:
                        volts = v_hi - v_lo
                    else:
                        volts = v_hi
                else:
                    volts = v_hi
        if volts is None:
            volts = np.zeros(record_length)
        volts = np.asarray(volts, dtype=float)
        if volts.size != record_length:
            volts = (
                volts[:record_length]
                if volts.size > record_length
                else np.pad(volts, (0, record_length - volts.size))
            )
        return volts

    def _dmm_transient_plan(self, twin: DMMTwin) -> tuple[float, int]:
        aperture = float(twin.state.aperture_s)
        enabled_freqs = [
            float(awg.state.frequency_hz)
            for awg in self.session.awgs.values()
            if getattr(awg.state, "enabled", False) and float(awg.state.frequency_hz) > 0
        ]
        duration = aperture
        if enabled_freqs:
            duration = max(duration, 5.0 / min(enabled_freqs))
        sample_rate = max(50_000.0, max(enabled_freqs) * 10.0 if enabled_freqs else 50_000.0)
        record_length = max(2, int(round(duration * sample_rate)))
        return sample_rate, record_length

    def _push_error(self, code: int, message: str) -> None:
        self._error_queue.append((code, message))

    def _pop_error(self) -> str:
        if not self._error_queue:
            return '+0,"No error"'
        code, msg = self._error_queue.pop(0)
        return f'{code},"{msg}"'

    def _clear_errors(self) -> None:
        self._error_queue.clear()

    def _emit_warnings(self, twin: InstrumentTwin) -> None:
        if not getattr(twin, "last_warnings", None):
            return
        for message in twin.last_warnings:
            self._push_error(-200, message)


def _encode_scope_bytes(
    volts: np.ndarray,
    *,
    sample_rate: float,
    vertical_scale_v: float,
    vertical_offset_v: float,
) -> tuple[bytes, list[str]]:
    volts = np.asarray(volts, dtype=float)
    points = int(volts.size)
    xinc = 1.0 / sample_rate if sample_rate > 0 else 0.0

    if points == 0:
        return b"", ["0"] * 10

    scale = float(vertical_scale_v)
    full_scale = scale * 8.0 if scale > 0 else 1.0
    yinc = full_scale / 255.0
    yorg = float(vertical_offset_v) - full_scale / 2.0
    raw = np.clip(np.round((volts - yorg) / yinc), 0, 255).astype(np.uint8)

    preamble = [
        "0",  # format: BYTE
        "0",  # type: NORMAL
        str(points),
        "1",  # count
        f"{xinc:.12g}",
        "0",  # xorigin
        "0",  # xreference
        f"{yinc:.12g}",
        f"{yorg:.12g}",
        "0",  # yreference
    ]
    return raw.tobytes(), preamble


def _model_params(session: Session) -> dict[str, float]:
    resolver = getattr(session, "resolve_model_params", None)
    if callable(resolver):
        return resolver(None)
    return {}
