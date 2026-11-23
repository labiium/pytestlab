"""Read-only channel context shared by the two documented VNA dialects."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import Literal

from ..config.vna_config import CMTHeldReadbackConfig
from ..config.vna_config import VNAReadbackConfig

if TYPE_CHECKING:
    from .VectorNetworkAnalyser import VectorNetworkAnalyser

VNAEvidence = Literal["live_configuration", "held_readback", "fresh_sweep"]


@dataclass(frozen=True)
class VNATraceContext:
    """Observed trace slot and applied correction, not a calibration certificate."""

    slot: int
    parameter: str
    correction_method: str
    correction_ports: tuple[int, ...]


@dataclass(frozen=True)
class VNAChannelContext:
    """Matched analyzer, frequency setup, system Z0 and indexed trace catalogue."""

    evidence: VNAEvidence
    manufacturer: str
    model: str
    serial_number: str
    software_revision: str
    hardware_revision: str | None
    options_reply: str | None
    channel: int
    sweep_type: Literal["linear", "log"]
    start_hz: float
    stop_hz: float
    point_count: int
    if_bandwidth_hz: float
    averaging_enabled: bool
    averaging_count: int
    port_reference_ohms: tuple[float, ...]  # Index 0 is physical port 1.
    correction_enabled: bool | None  # CMT channel-wide setting; ENA is trace-specific.
    port_extension_enabled: bool
    traces: tuple[VNATraceContext, ...]

    @property
    def port_count(self) -> int:
        return len(self.port_reference_ohms)

    def trace(self, slot: int) -> VNATraceContext:
        """Look up a physical trace slot, not its position in the returned S-data."""
        if type(slot) is not int or not 1 <= slot <= len(self.traces):
            raise KeyError(f"Trace slot {slot!r} is not in this channel context.")
        return self.traces[slot - 1]


_COMMON = {
    "identify": "*IDN?",
    "ports": ":SERV:PORT:COUN?",
    "continuous": ":INIT{channel}:CONT?",
    "sweep_type": ":SENS{channel}:SWE:TYPE?",
    "start_hz": ":SENS{channel}:FREQ:STAR?",
    "stop_hz": ":SENS{channel}:FREQ:STOP?",
    "points": ":SENS{channel}:SWE:POIN?",
    "if_bandwidth": ":SENS{channel}:BWID?",
    "average": ":SENS{channel}:AVER?",
    "average_count": ":SENS{channel}:AVER:COUN?",
    "port_extension": ":SENS{channel}:CORR:EXT:STAT?",
    "frequency_offset": ":SENS{channel}:OFFS:STAT?",
    "fixture_simulator": ":CALC{channel}:FSIM:STAT?",
    "trace_count": ":CALC{channel}:PAR:COUN?",
    "trace_identity": ":CALC{channel}:PAR{index}:DEF?",
    "trace_correction": ":SENS{channel}:CORR:TYPE{index}?",
}
_ENA = {
    "status": "*STB?",
    "condition": ":STAT:OPER:COND?",
    "format": ":FORM:DATA?",
    "options": "*OPT?",
    # The indexed form is in the Command Finder; the command page documents
    # this equivalent unindexed System Z0 form. This is a system quantity.
    "reference_ohms": ":SENS:CORR:IMP:INP:MAGN?",
}
_CMT = {
    "trigger_state": ":TRIG:STAT?",
    "channel_correction": ":SENS{channel}:CORR:STAT?",
    "reference_ohms": ":SENS:CORR:PORT{index}:IMP:INP:MAGN?",
}
_METHOD_PORTS = {
    "NONE": 0,
    "RESPO": 1,
    "RESPS": 1,
    "RESPT": 2,
    "SOLT1": 1,
    "SOLT2": 2,
    "SOLT3": 3,
    "SOLT4": 4,
    "ERES": 2,
    "SMIX2": 2,
    "1PATH": 2,
}
ContextPlan = dict[tuple[str, int | None], str]


def build_context_plan(vna: VectorNetworkAnalyser) -> ContextPlan:
    """Compile a semantically pinned query-only profile operation before I/O."""
    spec = vna.config.readback
    operation = vna.config.operation_options.operation("sparameter_channel_context")
    scpi = vna.config.scpi
    cmt = isinstance(spec, CMTHeldReadbackConfig)
    if (
        not isinstance(spec, (VNAReadbackConfig, CMTHeldReadbackConfig))
        or operation is None
        or scpi is None
        or vna.config.model.casefold() != ("c1209" if cmt else "e5071c")
    ):
        raise vna._configuration_error("Profile does not implement a verified VNA channel context.")
    commands: ContextPlan = {}
    for key, template in (_COMMON | (_CMT if cmt else _ENA)).items():
        alias = operation.transport.get(key)
        if alias not in (scpi.queries or {}) or alias is None:
            raise vna._configuration_error(f"Missing VNA context query {key!r}.")
        indices = (
            range(1, 3 if key == "reference_ohms" else spec.max_traces + 1)
            if "{index}" in template
            else (None,)
        )
        for index in indices:
            args = {"channel": spec.channel, "index": index}
            expected = template.format(**args)
            if vna._build_profile_alias(alias, **args) != [expected]:
                raise vna._configuration_error(f"Unverified VNA context query {key!r}.")
            commands[key, index] = expected
    return commands


def require_idle(
    vna: VectorNetworkAnalyser,
    query: Callable[[str], str],
    *,
    armed: bool = False,
) -> None:
    cmt = isinstance(vna.config.readback, CMTHeldReadbackConfig)
    if cmt:
        idle = not armed and query("trigger_state") == "HOLD"
    else:
        idle = not vna._readback_count(
            query("status"), "status byte", 0, 255
        ) & 20 and vna._readback_count(query("condition"), "operation state", 0, 65535) == (
            32 if armed else 0
        )
    if not idle or vna._readback_count(query("continuous"), "continuous", 0, 1):
        raise vna._configuration_error("VNA readback requires a stable held sweep.")


def read_identity(
    vna: VectorNetworkAnalyser,
    query: Callable[[str], str],
) -> tuple[str, str, str, str, str | None]:
    spec = vna.config.readback
    assert isinstance(spec, (VNAReadbackConfig, CMTHeldReadbackConfig))
    fields = tuple(part.strip() for part in query("identify").split(","))
    if len(fields) != 4 or any(re.fullmatch(r"[ -~]{1,128}", field) is None for field in fields):
        raise vna._data_error("Invalid VNA identification reply.")
    manufacturer, model, serial, revision = fields
    if vna.config.serial_number is not None and serial != vna.config.serial_number:
        raise vna._configuration_error("VNA serial does not match the selected profile.")
    hw_revision = None
    if isinstance(spec, CMTHeldReadbackConfig):
        if (
            (manufacturer, model) != ("CMT", "C1209")
            or re.fullmatch(r"[0-9]+", serial) is None
            or re.fullmatch(re.escape(spec.software_version) + r"/[0-9]+", revision) is None
        ):
            raise vna._configuration_error("Expected a C1209 reporting the exact S2VNA version.")
        revision, hw_revision = revision.split("/")
    else:
        minimum = vna._firmware_tuple(spec.minimum_firmware)
        firmware = vna._firmware_tuple(revision.upper())
        if (
            manufacturer.casefold() not in {"keysight technologies", "agilent technologies"}
            or model.upper() != "E5071C"
            or firmware is None
            or minimum is None
            or firmware[0] != minimum[0]
            or firmware < minimum
        ):
            raise vna._configuration_error("Expected the profile-supported E5071C firmware.")
    return manufacturer, model, serial, revision, hw_revision


def observe_context(
    vna: VectorNetworkAnalyser,
    commands: ContextPlan,
    exchange: Callable[[str], str],
    evidence: VNAEvidence,
    *,
    armed: bool = False,
) -> VNAChannelContext:
    """Observe one held context. The caller re-observes it around acquisition."""
    spec = vna.config.readback
    assert isinstance(spec, (VNAReadbackConfig, CMTHeldReadbackConfig))
    cmt = isinstance(spec, CMTHeldReadbackConfig)

    def query(key: str, index: int | None = None) -> str:
        return exchange(commands[key, index]).strip()

    def number(key: str, index: int | None = None) -> float:
        return vna._csv_values(query(key, index), 1, key)[0]

    def boolean(key: str) -> bool:
        return bool(vna._readback_count(query(key), key, 0, 1))

    require_idle(vna, query, armed=armed)
    manufacturer, model, serial, revision, hw_revision = read_identity(vna, query)
    if not cmt and query("format") != "ASC":
        raise vna._configuration_error("VNA channel context requires ASCII format.")
    options = None if cmt else query("options")
    if options is not None and re.fullmatch(r"[A-Z0-9, /]{1,256}", options.upper()) is None:
        raise vna._data_error("Invalid E5071C installed-options reply.")
    ports = vna._readback_count(query("ports"), "physical port count", 2, 2 if cmt else 4)
    if ports not in (2, 4):
        raise vna._data_error("Unsupported physical port count.")
    mode = query("sweep_type")
    if mode not in {"LIN", "LOG"} or boolean("frequency_offset") or boolean("fixture_simulator"):
        raise vna._configuration_error(
            "VNA channel context requires LIN/LOG and no frequency offset or fixture simulation."
        )
    start, stop, bandwidth = (number(key) for key in ("start_hz", "stop_hz", "if_bandwidth"))
    if not 0 < start < stop or bandwidth <= 0:
        raise vna._data_error("Invalid frequency limits or IF bandwidth in VNA channel context.")
    points = vna._readback_count(query("points"), "sweep points", 2, spec.max_points)
    averaging = boolean("average")
    average_count = vna._readback_count(query("average_count"), "averaging count", 1, 999_999)
    references = (
        tuple(number("reference_ohms", port) for port in range(1, ports + 1))
        if cmt
        else (number("reference_ohms"),) * ports
    )
    if any(not 0.001 <= z0 <= 1000 for z0 in references):
        raise vna._data_error("VNA reported an invalid reference impedance.")
    count = vna._readback_count(query("trace_count"), "trace count", 1, spec.max_traces)
    traces = []
    for slot in range(1, count + 1):
        parameter = query("trace_identity", slot).upper()
        if re.fullmatch(r"[A-Z0-9_+-]{1,16}(?:\([1-4]\))?", parameter) is None:
            raise vna._data_error(f"Invalid measurement identity on VNA trace {slot}.")
        raw = query("trace_correction", slot)
        fields = tuple(part.strip() for part in raw.split(","))
        method = fields[0]
        arity = _METHOD_PORTS.get(method)
        allowed = {"NONE", "RESPO", "RESPS", "RESPT", "SOLT1", "SOLT2"}
        allowed |= {"1PATH"} if cmt else {"ERES", "SMIX2", "SOLT3", "SOLT4"}
        if (
            arity is None
            or method not in allowed
            or len(fields) != (arity + 1 if cmt else 5)
            or any(re.fullmatch(r"[0-4]", field) is None for field in fields[1:])
        ):
            raise vna._data_error(f"Invalid correction reply for VNA trace {slot}.")
        correction_ports = tuple(int(value) for value in fields[1 : 1 + arity])
        if (
            any(not 1 <= port <= ports for port in correction_ports)
            or (method != "SMIX2" and len(set(correction_ports)) != arity)
            or any(value != "0" for value in fields[1 + arity :])
        ):
            raise vna._data_error(f"Invalid correction ports for VNA trace {slot}.")
        traces.append(VNATraceContext(slot, parameter, method, correction_ports))
    correction = boolean("channel_correction") if cmt else None
    extension = boolean("port_extension")
    require_idle(vna, query, armed=armed)
    return VNAChannelContext(
        evidence,
        manufacturer,
        model,
        serial,
        revision,
        hw_revision,
        options,
        spec.channel,
        "linear" if mode == "LIN" else "log",
        start,
        stop,
        points,
        bandwidth,
        averaging,
        average_count,
        references,
        correction,
        extension,
        tuple(traces),
    )


@dataclass(frozen=True)
class VNAFrequencyMarker:
    """One enabled instrument display marker, not a complex measured bin."""

    channel: int
    trace_slot: int
    parameter: str
    marker: int
    frequency_hz: float
    magnitude_db: float


_MARKER_COMMON = {
    "state": ":CALC{channel}:TRAC{trace}:MARK{marker}:STAT?",
    "format": ":CALC{channel}:TRAC{trace}:FORM?",
    "display_data": ":DISP:WIND{channel}:TRAC{trace}:STAT?",
    "display_memory": ":DISP:WIND{channel}:TRAC{trace}:MEM?",
    "time_transform": ":CALC{channel}:TRAC{trace}:TRAN:TIME:STAT?",
    "conversion": ":CALC{channel}:TRAC{trace}:CONV:STAT?",
}
_MARKER_ENA = {
    "reference": ":CALC{channel}:TRAC{trace}:MARK:REF:STAT?",
    "equation": ":CALC{channel}:TRAC{trace}:EQU:STAT?",
    "data": ":CALC{channel}:TRAC{trace}:MARK{marker}:DATA?",
}
_MARKER_CMT = {
    # The S2VNA marks the reference mode as marker 16; its ordinary markers
    # are 1–15 and report deltas when reference marker 16 is enabled.
    "reference": ":CALC{channel}:TRAC{trace}:MARK16:STAT?",
    "x": ":CALC{channel}:TRAC{trace}:MARK{marker}:X?",
    "y": ":CALC{channel}:TRAC{trace}:MARK{marker}:Y?",
}


def build_marker_plan(vna: VectorNetworkAnalyser, trace: int, marker: int) -> dict[str, str]:
    spec = vna.config.readback
    contract = vna.config.operation_options.operation("sparameter_frequency_marker")
    scpi = vna.config.scpi
    cmt = isinstance(spec, CMTHeldReadbackConfig)
    if not isinstance(spec, (VNAReadbackConfig, CMTHeldReadbackConfig)) or (
        contract is None or scpi is None
    ):
        raise vna._configuration_error("Profile does not implement indexed VNA marker readback.")
    if type(trace) is not int or not 1 <= trace <= spec.max_traces:
        raise vna._configuration_error(
            f"Trace slot must be an integer from 1 to {spec.max_traces}."
        )
    maximum = 15 if cmt else 9
    if type(marker) is not int or not 1 <= marker <= maximum:
        raise vna._configuration_error(f"Marker must be an integer from 1 to {maximum}.")
    commands: dict[str, str] = {}
    for key, template in (_MARKER_COMMON | (_MARKER_CMT if cmt else _MARKER_ENA)).items():
        alias = contract.transport.get(key)
        args = {"channel": spec.channel, "trace": trace, "marker": marker}
        expected = template.format(**args)
        if (
            alias is None
            or alias not in (scpi.queries or {})
            or vna._build_profile_alias(alias, **args) != [expected]
        ):
            raise vna._configuration_error(f"Unverified indexed VNA marker query {key!r}.")
        commands[key] = expected
    return commands


def observe_marker(
    vna: VectorNetworkAnalyser,
    context: VNAChannelContext,
    commands: dict[str, str],
    exchange: Callable[[str], str],
    trace: int,
    marker: int,
) -> VNAFrequencyMarker:
    if trace > len(context.traces):
        raise vna._configuration_error(f"Trace slot {trace} is not configured.")
    parameter = context.trace(trace).parameter
    match = re.fullmatch(r"S([1-4])([1-4])", parameter)
    if match is None or any(int(port) > context.port_count for port in match.groups()):
        raise vna._configuration_error(
            "Frequency marker requires a single-ended S-parameter trace."
        )

    def query(key: str) -> str:
        return exchange(commands[key]).strip()

    for key, expected in (
        ("state", "1"),
        ("reference", "0"),
        ("format", "MLOG"),
        ("display_data", "1"),
        ("display_memory", "0"),
        ("time_transform", "0"),
        ("conversion", "0"),
        ("equation", "0"),
    ):
        if key in commands and query(key) != expected:
            raise vna._configuration_error(f"Frequency marker requires {key}={expected}.")
    if "data" in commands:
        # ENA reports primary Y, secondary Y, then X in one reply.
        magnitude, auxiliary, frequency = vna._csv_values(query("data"), 3, "marker data")
    else:
        frequency = vna._csv_values(query("x"), 1, "marker frequency")[0]
        magnitude, auxiliary = vna._csv_values(query("y"), 2, "marker response")
        if vna._csv_values(query("x"), 1, "marker frequency")[0] != frequency:
            raise vna._data_error("Marker moved while reading its stimulus and response.")
    if (
        auxiliary != 0
        or not context.start_hz <= frequency <= context.stop_hz
        or abs(magnitude) >= 9.9e37
    ):
        raise vna._data_error("Invalid absolute log-magnitude marker reply.")
    return VNAFrequencyMarker(context.channel, trace, parameter, marker, frequency, magnitude)
