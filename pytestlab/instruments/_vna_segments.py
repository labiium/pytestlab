"""Read-only inspection of manufacturer segment setup tables, not trace data."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import replace
from typing import TYPE_CHECKING
from typing import Literal

from ..config.vna_config import CMTHeldReadbackConfig
from ..config.vna_config import VNAReadbackConfig
from ._vna_context import read_identity
from ._vna_context import require_idle

if TYPE_CHECKING:
    from .VectorNetworkAnalyser import VectorNetworkAnalyser

SweepType = Literal["linear", "log", "segment", "power"]


@dataclass(frozen=True)
class VNASweepSegment:
    """One configured table row; no measured stimulus or data are implied."""

    index: int
    start_hz: float
    stop_hz: float
    point_count: int
    if_bandwidth_hz: float | None = None
    power_dbm: float | None = None
    delay_s: float | None = None
    sweep_mode: Literal["stepped", "swept"] | None = None
    sweep_time_s: float | None = None  # ENA's explicit 0 means automatic.
    enabled: bool | None = None  # S2VNA does not report per-row enable.
    vendor_reserved_value: float | None = None  # S2VNA's optional reserved column.


@dataclass(frozen=True)
class VNASegmentTable:
    """Observed configuration in instrument row order, even when not active."""

    model: str
    serial_number: str
    software_revision: str
    hardware_revision: str | None
    channel: int
    active_sweep_type: SweepType
    frequency_mode: Literal["start_stop", "center_span"]
    segments: tuple[VNASweepSegment, ...]
    individual_state_control: bool | None = None
    arbitrary_segments_enabled: bool | None = None


_COMMON = {
    "identify": "*IDN?",
    "continuous": ":INIT{channel}:CONT?",
    "sweep_type": ":SENS{channel}:SWE:TYPE?",
    "table": ":SENS{channel}:SEGM:DATA?",
}
_ENA = {
    "status": "*STB?",
    "condition": ":STAT:OPER:COND?",
    "format": ":FORM:DATA?",
    "state_control": ":SENS{channel}:SEGM:LIST:CONT:STAT?",
    "row_states": ":SENS{channel}:SEGM:LIST:CONT:DATA?",
    "arbitrary": ":SENS{channel}:SEGM:ARB:STAT?",
}
_CMT = {"trigger_state": ":TRIG:STAT?"}
_TYPES: dict[str, SweepType] = {"LIN": "linear", "LOG": "log", "SEGM": "segment", "POW": "power"}


def build_segment_plan(vna: VectorNetworkAnalyser) -> dict[str, str]:
    spec = vna.config.readback
    contract = vna.config.operation_options.operation("sparameter_segment_table")
    scpi = vna.config.scpi
    cmt = isinstance(spec, CMTHeldReadbackConfig)
    if (
        not isinstance(spec, (VNAReadbackConfig, CMTHeldReadbackConfig))
        or contract is None
        or scpi is None
        or vna.config.model.casefold() != ("c1209" if cmt else "e5071c")
    ):
        raise vna._configuration_error("Profile does not implement VNA segment-table readback.")
    commands = {}
    for key, template in (_COMMON | (_CMT if cmt else _ENA)).items():
        alias = contract.transport.get(key)
        expected = template.format(channel=spec.channel)
        if (
            alias is None
            or alias not in (scpi.queries or {})
            or vna._build_profile_alias(alias, channel=spec.channel) != [expected]
        ):
            raise vna._configuration_error(f"Unverified VNA segment-table query {key!r}.")
        commands[key] = expected
    return commands


def segment_table_line_limit(spec: VNAReadbackConfig | CMTHeldReadbackConfig) -> int:
    cmt = isinstance(spec, CMTHeldReadbackConfig)
    rows = spec.max_points if cmt else 201
    fields_per_row = 7 if cmt else 8
    # 32 ASCII characters per field is ample for the documented numeric
    # representation. Never exceed the shared VISA backend's hard line cap.
    return min(2_000_000, 32 * (8 + fields_per_row * rows) + 2)


def _decode_table(
    vna: VectorNetworkAnalyser,
    raw: str,
    spec: VNAReadbackConfig | CMTHeldReadbackConfig,
) -> tuple[Literal["start_stop", "center_span"], tuple[VNASweepSegment, ...]]:
    cmt = isinstance(spec, CMTHeldReadbackConfig)
    if len(raw) > segment_table_line_limit(spec) or not raw.isascii():
        raise vna._data_error("VNA segment table exceeds the bounded ASCII format.")
    size = raw.count(",") + 1
    if size < 10:
        raise vna._data_error("VNA segment table is missing its header or rows.")
    values = vna._csv_values(raw, size, "segment table")
    wire_format = values[0]
    if wire_format != 5 and (cmt or wire_format != 6):
        raise vna._data_error("Unrecognized VNA segment table wire format.")
    header_size = 8 if wire_format == 6 else 7
    center_span, bandwidth, power, delay = values[1:5]
    sweep_mode = values[5] if wire_format == 6 else 0
    timing, raw_count = values[header_size - 2 : header_size]
    flags = (center_span, bandwidth, power, delay, sweep_mode, timing)
    if any(flag not in (0, 1) for flag in flags) or (wire_format == 6 and not sweep_mode):
        raise vna._data_error("Invalid VNA segment table option flags.")
    max_rows = spec.max_points if cmt else 201
    if not float(raw_count).is_integer() or not 1 <= raw_count <= max_rows:
        raise vna._data_error("VNA segment count is invalid or outside the supported bound.")
    count = int(raw_count)
    fields_per_row = 3 + int(sum(flags[1:]))
    if size != header_size + count * fields_per_row:
        raise vna._data_error("VNA segment rows do not match the declared fields and count.")

    rows = []
    for index, offset in enumerate(range(header_size, size, fields_per_row), start=1):
        first, second, points = values[offset : offset + 3]
        if center_span:
            if second < 0:
                raise vna._data_error(f"VNA segment {index} reports negative span.")
            start, stop = first - second / 2, first + second / 2
        else:
            start, stop = first, second
        if (
            (not math.isfinite(start) or not math.isfinite(stop) or min(start, stop) <= 0)
            or not float(points).is_integer()
            or not (1 if start == stop else 2) <= points <= spec.max_points
            or (cmt and start > stop)
        ):
            raise vna._data_error(f"Invalid frequency or point count for VNA segment {index}.")

        fields = iter(values[offset + 3 : offset + fields_per_row])
        if_bandwidth_hz = next(fields) if bandwidth else None
        power_dbm = next(fields) if power else None
        delay_s = next(fields) if delay else None
        mode = next(fields) if sweep_mode else None
        time_value = next(fields) if timing else None
        if (
            (if_bandwidth_hz is not None and if_bandwidth_hz <= 0)
            or (delay_s is not None and delay_s < 0)
            or (not cmt and time_value is not None and time_value < 0)
            or (mode is not None and mode not in (0, 1, 2, 3))
        ):
            raise vna._data_error(f"Invalid optional setting for VNA segment {index}.")

        rows.append(
            VNASweepSegment(
                index=index,
                start_hz=start,
                stop_hz=stop,
                point_count=int(points),
                if_bandwidth_hz=if_bandwidth_hz,
                power_dbm=power_dbm,
                delay_s=delay_s,
                sweep_mode=None if mode is None else ("stepped" if mode in (0, 2) else "swept"),
                sweep_time_s=None if cmt else time_value,
                vendor_reserved_value=time_value if cmt else None,
            )
        )
    return ("center_span" if center_span else "start_stop"), tuple(rows)


def observe_segment_table(
    vna: VectorNetworkAnalyser,
    commands: dict[str, str],
    exchange: Callable[[str], str],
) -> VNASegmentTable:
    spec = vna.config.readback
    assert isinstance(spec, (VNAReadbackConfig, CMTHeldReadbackConfig))
    cmt = isinstance(spec, CMTHeldReadbackConfig)

    def query(key: str) -> str:
        return exchange(commands[key]).strip()

    def boolean(key: str) -> bool:
        return bool(vna._readback_count(query(key), key, 0, 1))

    require_idle(vna, query)
    _, model, serial, revision, hardware_revision = read_identity(vna, query)
    firmware = None if cmt else vna._firmware_tuple(revision.upper())
    if not cmt:
        if firmware is None or firmware < ("A", 9, 60):
            raise vna._configuration_error("ENA segment readback requires A.09.60+ firmware.")
        if query("format") != "ASC":
            raise vna._configuration_error("ENA segment-table readback requires ASCII format.")
    current_type = _TYPES.get(query("sweep_type"))
    if current_type is None:
        raise vna._data_error("Unrecognized active VNA sweep type.")

    frequency_mode, rows = _decode_table(vna, query("table"), spec)
    state_control = arbitrary = None
    if not cmt:
        state_control = boolean("state_control")
        if state_control:
            raw_states = vna._csv_values(query("row_states"), len(rows), "segment state list")
            if any(state not in (0, 1) for state in raw_states):
                raise vna._data_error("ENA segment state list contains a non-Boolean reply.")
            rows = tuple(
                replace(row, enabled=bool(state))
                for row, state in zip(rows, raw_states, strict=True)
            )
        else:
            rows = tuple(replace(row, enabled=True) for row in rows)
        if firmware is not None and firmware >= ("A", 11, 20):
            arbitrary = boolean("arbitrary")
        if not arbitrary and any(row.start_hz > row.stop_hz for row in rows):
            raise vna._data_error("ENA reverse segment requires enabled arbitrary segment control.")
    require_idle(vna, query)
    return VNASegmentTable(
        model,
        serial,
        revision,
        hardware_revision,
        spec.channel,
        current_type,
        frequency_mode,
        rows,
        state_control,
        arbitrary,
    )
