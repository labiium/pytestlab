"""Stable readback of analyzer capacity, independent of acquisition limits."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import Literal

from ..config.vna_config import CMTHeldReadbackConfig
from ..config.vna_config import VNAReadbackConfig
from ._vna_context import read_identity
from ._vna_context import require_idle

if TYPE_CHECKING:
    from .VectorNetworkAnalyser import VectorNetworkAnalyser


@dataclass(frozen=True)
class VNAFrequencyLimits:
    """Analyzer frequency limits, not a measurement or RF commissioning record."""

    minimum_hz: float
    maximum_hz: float
    source: Literal["instrument_query", "vendor_option_table"]


@dataclass(frozen=True)
class VNAInstrumentInventory:
    """Observed identity, service capacity and the driver profile's separate caps."""

    manufacturer: str
    model: str
    serial_number: str
    software_revision: str
    hardware_revision: str | None
    port_count: int
    max_channels: int
    max_traces_per_channel: int
    max_sweep_points: int
    active_channel: int
    profile_channel: int
    profile_channel_trace_count: int
    profile_max_traces: int
    profile_max_points: int
    frequency_limits: VNAFrequencyLimits | None
    options_reply: str | None = None
    test_set_option: str | None = None
    bias_tees_installed: bool | None = None


# E5071C WebHelp, Options > Test Port & Frequency Options. These are
# published nominal ranges, not frequency observations from the device.
_ENA_TEST_SETS = {
    option: (ports, bias, low, high)
    for first, second, bias, low, high in (
        ("230", "430", False, 9e3, 3e9),
        ("240", "440", False, 9e3, 4.5e9),
        ("260", "460", False, 9e3, 6.5e9),
        ("280", "480", False, 9e3, 8.5e9),
        ("235", "435", True, 100e3, 3e9),
        ("245", "445", True, 100e3, 4.5e9),
        ("265", "465", True, 100e3, 6.5e9),
        ("285", "485", True, 100e3, 8.5e9),
        ("2D5", "4D5", True, 300e3, 14e9),
        ("2K5", "4K5", True, 300e3, 20e9),
    )
    for option, ports in ((first, 2), (second, 4))
}
_COMMON = {
    "identify": "*IDN?",
    "continuous": ":INIT{channel}:CONT?",
    "ports": ":SERV:PORT:COUN?",
    "max_channels": ":SERV:CHAN:COUN?",
    "max_traces": ":SERV:CHAN:TRAC:COUN?",
    "max_points": ":SERV:SWE:POIN?",
    "active_channel": ":SERV:CHAN:ACT?",
    "trace_count": ":CALC{channel}:PAR:COUN?",
}
_ENA = {
    "status": "*STB?",
    "condition": ":STAT:OPER:COND?",
    "options": "*OPT?",
}
_CMT = {
    "trigger_state": ":TRIG:STAT?",
    "min_frequency": ":SERV:SWE:FREQ:MIN?",
    "max_frequency": ":SERV:SWE:FREQ:MAX?",
}


def build_inventory_plan(vna: VectorNetworkAnalyser) -> dict[str, str]:
    spec = vna.config.readback
    contract = vna.config.operation_options.operation("vna_inventory")
    scpi = vna.config.scpi
    cmt = isinstance(spec, CMTHeldReadbackConfig)
    if (
        not isinstance(spec, (VNAReadbackConfig, CMTHeldReadbackConfig))
        or contract is None
        or scpi is None
        or vna.config.model.casefold() != ("c1209" if cmt else "e5071c")
    ):
        raise vna._configuration_error("Profile does not implement VNA analyzer inventory.")
    queries = scpi.queries or {}
    plan = {}
    for key, template in (_COMMON | (_CMT if cmt else _ENA)).items():
        alias = contract.transport.get(key)
        expected = template.format(channel=spec.channel)
        if (
            alias is None
            or alias not in queries
            or vna._build_profile_alias(alias, channel=spec.channel) != [expected]
        ):
            raise vna._configuration_error(f"Unverified VNA inventory query {key!r}.")
        plan[key] = expected
    return plan


def observe_inventory(
    vna: VectorNetworkAnalyser,
    plan: dict[str, str],
    exchange: Callable[[str], str],
) -> VNAInstrumentInventory:
    spec = vna.config.readback
    assert isinstance(spec, (VNAReadbackConfig, CMTHeldReadbackConfig))
    cmt = isinstance(spec, CMTHeldReadbackConfig)

    def query(key: str) -> str:
        return exchange(plan[key]).strip()

    def count(key: str, low: int, high: int) -> int:
        label = key.replace("_", " ")
        reply = query(key)
        if not cmt:
            return vna._readback_count(reply, label, low, high)
        # S2VNA specifies a numeric response, not a lexical integer. Accept
        # integral ASCII values even if written in decimal or exponent form.
        value = vna._csv_values(reply, 1, label)[0]
        if not float(value).is_integer():
            raise vna._data_error(f"VNA {label} reply is not an integer.")
        if not low <= value <= high:
            raise vna._configuration_error(f"{label} {value:g} outside supported {low}–{high}.")
        return int(value)

    require_idle(vna, query)
    manufacturer, model, serial, revision, hardware_revision = read_identity(vna, query)
    ports = count("ports", 2, 2 if cmt else 4)
    if ports not in (2, 4):
        raise vna._data_error("Unsupported VNA physical port count.")
    max_channels = count("max_channels", 1, 16 if cmt else 160)
    max_traces = count("max_traces", 1, 16)
    max_points = count("max_points", 2, 500_001 if cmt else 20_001)
    active = count("active_channel", 1, max_channels)
    if spec.channel > max_channels:
        raise vna._configuration_error("Profile channel exceeds the observed analyzer limit.")
    current_traces = count("trace_count", 1, max_traces)

    options = option = None
    bias_tees = frequency_limits = None
    if cmt:
        minimum = vna._csv_values(query("min_frequency"), 1, "minimum frequency")[0]
        maximum = vna._csv_values(query("max_frequency"), 1, "maximum frequency")[0]
        if not 0 < minimum < maximum:
            raise vna._data_error("Invalid VNA frequency limits.")
        frequency_limits = VNAFrequencyLimits(minimum, maximum, "instrument_query")
    else:
        options = query("options")
        if (
            len(options) > 256
            or re.fullmatch(r"[A-Z0-9]+(?:[ ,/]+[A-Z0-9]+)*", options.upper()) is None
        ):
            raise vna._data_error("Invalid E5071C installed-options reply.")
        test_sets = _ENA_TEST_SETS.keys() & set(re.split(r"[ ,/]+", options.upper()))
        if len(test_sets) > 1:
            raise vna._data_error("E5071C reported conflicting test-set options.")
        if test_sets:
            option = next(iter(test_sets))
            expected_ports, bias_tees, minimum, maximum = _ENA_TEST_SETS[option]
            if expected_ports != ports:
                raise vna._data_error("E5071C test-set option disagrees with its port count.")
            frequency_limits = VNAFrequencyLimits(minimum, maximum, "vendor_option_table")

    require_idle(vna, query)
    return VNAInstrumentInventory(
        manufacturer=manufacturer,
        model=model,
        serial_number=serial,
        software_revision=revision,
        hardware_revision=hardware_revision,
        port_count=ports,
        max_channels=max_channels,
        max_traces_per_channel=max_traces,
        max_sweep_points=max_points,
        active_channel=active,
        profile_channel=spec.channel,
        profile_channel_trace_count=current_traces,
        profile_max_traces=spec.max_traces,
        profile_max_points=spec.max_points,
        frequency_limits=frequency_limits,
        options_reply=options,
        test_set_option=option,
        bias_tees_installed=bias_tees,
    )
