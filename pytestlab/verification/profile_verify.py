from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from enum import StrEnum
from pathlib import Path
from typing import Any
from typing import Literal
from typing import cast

from pydantic import BaseModel
from rich.console import Console
from rich.table import Table
from rich.text import Text

from pytestlab.common.health import HealthReport
from pytestlab.common.health import HealthStatus
from pytestlab.config.instrument_config import InstrumentConfig
from pytestlab.config.loader import load_profile
from pytestlab.instruments.AutoInstrument import AutoInstrument

ProbeMode = Literal["read-only", "safe-write"]
_VALID_PROBE_MODES = {"read-only", "safe-write"}

_STATUS_ORDER = ("error", "fail", "warn", "skip", "pass")
_STATUS_COLORS = {
    "pass": "green",
    "fail": "red",
    "warn": "yellow",
    "skip": "dim",
    "error": "bold red",
}
_STATUS_ICONS = {
    "pass": "PASS",
    "fail": "FAIL",
    "warn": "WARN",
    "skip": "SKIP",
    "error": "ERROR",
}
_SKIPPED_QUERY_NAMES = {"reset", "clear", "self_test"}


class VerificationStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"
    SKIP = "skip"
    ERROR = "error"


@dataclass(slots=True)
class VerificationResult:
    id: str
    category: str
    status: VerificationStatus
    summary: str
    expected: str | None = None
    observed: str | None = None
    details: str | None = None


@dataclass(slots=True)
class VerificationContext:
    profile_source: str | Path
    config: InstrumentConfig
    instrument: Any
    probe_mode: ProbeMode
    allow_output_enable: bool
    fail_fast: bool
    address_override: str | None = None
    timeout_ms: int | None = None


@dataclass(slots=True)
class VerificationReport:
    profile_source: str | Path
    device_type: str
    manufacturer: str
    model: str
    probe_mode: ProbeMode
    address_override: str | None
    results: list[VerificationResult] = field(default_factory=list)

    @property
    def overall_status(self) -> VerificationStatus:
        statuses = {result.status for result in self.results}
        for candidate in _STATUS_ORDER:
            enum_candidate = VerificationStatus(candidate)
            if enum_candidate in statuses:
                return enum_candidate
        return VerificationStatus.PASS

    @property
    def counts(self) -> dict[str, int]:
        counts = {name: 0 for name in _STATUS_ORDER}
        for result in self.results:
            counts[result.status.value] += 1
        return counts

    @property
    def has_failures(self) -> bool:
        return self.overall_status in {VerificationStatus.FAIL, VerificationStatus.ERROR}

    def add(self, result: VerificationResult) -> None:
        self.results.append(result)


def _format_value(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def _result(
    status: VerificationStatus,
    category: str,
    check_id: str,
    summary: str,
    *,
    expected: Any = None,
    observed: Any = None,
    details: str | None = None,
) -> VerificationResult:
    return VerificationResult(
        id=check_id,
        category=category,
        status=status,
        summary=summary,
        expected=_format_value(expected) if expected is not None else None,
        observed=_format_value(observed) if observed is not None else None,
        details=details,
    )


def _validate_probe_mode(probe_mode: str) -> ProbeMode:
    if probe_mode not in _VALID_PROBE_MODES:
        raise ValueError("probe_mode must be 'read-only' or 'safe-write'")
    return cast(ProbeMode, probe_mode)


def _first_channel_id(config: InstrumentConfig) -> int:
    channels = getattr(config, "channels", None) or []
    if not channels:
        return 1

    first = channels[0]
    if isinstance(first, dict):
        for key in ("channel_id", "id", "number", "channel"):
            value = first.get(key)
            if isinstance(value, int):
                return value
            if isinstance(value, str) and value.isdigit():
                return int(value)
        return 1

    for attr_name in ("channel_id", "id", "number", "channel"):
        value = getattr(first, attr_name, None)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return 1


def _collect_scpi_requirement_groups(obj: Any, prefix: str = "") -> list[tuple[str, list[str]]]:
    groups: list[tuple[str, list[str]]] = []

    if isinstance(obj, BaseModel):
        for field_name in obj.__class__.model_fields:
            value = getattr(obj, field_name, None)
            group_name = f"{prefix}.{field_name}" if prefix else field_name
            if field_name.endswith("_scpi_commands") and isinstance(value, list) and value:
                groups.append((group_name, [str(item) for item in value]))
            elif field_name == "required_scpi_commands" and isinstance(value, list) and value:
                groups.append((group_name, [str(item) for item in value]))
            elif isinstance(value, BaseModel):
                groups.extend(_collect_scpi_requirement_groups(value, group_name))
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    if isinstance(item, BaseModel):
                        groups.extend(_collect_scpi_requirement_groups(item, f"{group_name}[{index}]"))
    return groups


def _run_identity_check(context: VerificationContext) -> VerificationResult:
    idn = context.instrument.id()
    idn_lc = idn.lower()
    manufacturer_ok = context.config.manufacturer.lower() in idn_lc
    model_ok = context.config.model.lower() in idn_lc
    if manufacturer_ok and model_ok:
        return _result(
            VerificationStatus.PASS,
            "Identity",
            "identity.idn",
            "Instrument ID matches profile manufacturer and model.",
            expected=f"{context.config.manufacturer} / {context.config.model}",
            observed=idn,
        )
    return _result(
        VerificationStatus.FAIL,
        "Identity",
        "identity.idn",
        "Instrument ID does not match profile manufacturer/model.",
        expected=f"{context.config.manufacturer} / {context.config.model}",
        observed=idn,
    )


def _run_health_checks(context: VerificationContext) -> list[VerificationResult]:
    if not hasattr(context.instrument, "health_check"):
        return [
            _result(
                VerificationStatus.SKIP,
                "Health",
                "health.unsupported",
                "Instrument does not implement health_check().",
            )
        ]

    report = context.instrument.health_check()
    if not isinstance(report, HealthReport):
        return [
            _result(
                VerificationStatus.WARN,
                "Health",
                "health.invalid-report",
                "health_check() did not return a HealthReport instance.",
                observed=type(report).__name__,
            )
        ]

    results: list[VerificationResult] = [
        _result(
            VerificationStatus.PASS
            if report.status in {HealthStatus.OK, HealthStatus.WARNING}
            else VerificationStatus.FAIL,
            "Health",
            "health.status",
            f"Health check completed with status {report.status.value}.",
            observed=report.status.value,
        )
    ]
    for warning in report.warnings:
        results.append(
            _result(
                VerificationStatus.WARN,
                "Health",
                "health.warning",
                warning,
            )
        )
    for error in report.errors:
        results.append(
            _result(
                VerificationStatus.FAIL,
                "Health",
                "health.error",
                error,
            )
        )
    for feature_name, supported in sorted(report.supported_features.items()):
        results.append(
            _result(
                VerificationStatus.PASS if supported else VerificationStatus.WARN,
                "Health",
                f"health.feature.{feature_name}",
                f"Feature '{feature_name}' reported by health check.",
                observed=supported,
            )
        )
    return results


def _run_scpi_presence_checks(context: VerificationContext) -> list[VerificationResult]:
    results: list[VerificationResult] = []
    engine = getattr(context.instrument, "scpi_engine", None)
    if engine is None:
        return [
            _result(
                VerificationStatus.SKIP,
                "SCPI",
                "scpi.engine",
                "Instrument does not expose an SCPI engine.",
            )
        ]

    groups = _collect_scpi_requirement_groups(context.config)
    for group_name, names in groups:
        presence = engine.validate_presence(names)
        missing = sorted(name for name, present in presence.items() if not present)
        if missing:
            results.append(
                _result(
                    VerificationStatus.FAIL,
                    "SCPI",
                    f"scpi.group.{group_name}",
                    f"SCPI aliases declared in '{group_name}' are missing.",
                    expected=", ".join(names),
                    observed=", ".join(missing),
                )
            )
        else:
            results.append(
                _result(
                    VerificationStatus.PASS,
                    "SCPI",
                    f"scpi.group.{group_name}",
                    f"All SCPI aliases declared in '{group_name}' are present.",
                    observed=", ".join(names),
                )
            )

    feature_mappings = getattr(getattr(context.config, "scpi", None), "feature_mappings", None) or {}
    for feature_name, mapping in sorted(feature_mappings.items()):
        required = list((mapping or {}).get("required_scpi", []) or [])
        if not required:
            continue
        presence = engine.validate_presence(required)
        missing = sorted(name for name, present in presence.items() if not present)
        if missing:
            results.append(
                _result(
                    VerificationStatus.FAIL,
                    "SCPI",
                    f"scpi.feature.{feature_name}",
                    f"Feature '{feature_name}' is missing required SCPI aliases.",
                    expected=", ".join(required),
                    observed=", ".join(missing),
                )
            )
        else:
            results.append(
                _result(
                    VerificationStatus.PASS,
                    "SCPI",
                    f"scpi.feature.{feature_name}",
                    f"Feature '{feature_name}' has all required SCPI aliases.",
                )
            )
    return results


def _run_generic_query_smoke_checks(context: VerificationContext) -> list[VerificationResult]:
    results: list[VerificationResult] = []
    engine = getattr(context.instrument, "scpi_engine", None)
    if engine is None:
        return results

    seen: set[str] = set()
    candidate_names: list[str] = []
    for _group_name, aliases in _collect_scpi_requirement_groups(context.config):
        for alias in aliases:
            if alias not in seen:
                seen.add(alias)
                candidate_names.append(alias)

    for feature_mapping in (getattr(getattr(context.config, "scpi", None), "feature_mappings", None) or {}).values():
        for alias in list((feature_mapping or {}).get("required_scpi", []) or []):
            if alias not in seen:
                seen.add(alias)
                candidate_names.append(alias)

    for name in candidate_names:
        if name in _SKIPPED_QUERY_NAMES:
            results.append(
                _result(
                    VerificationStatus.SKIP,
                    "SCPI",
                    f"scpi.query.{name}",
                    f"Skipped potentially disruptive SCPI query '{name}'.",
                )
            )
            continue

        try:
            description = engine.describe(name)
        except Exception:
            continue

        sequence = description.get("sequence", [])
        if len(sequence) != 1:
            continue
        if "?" not in sequence[0]:
            continue

        try:
            placeholder_info = engine.validate_placeholders(name)
            placeholders = placeholder_info.get("placeholders", [])
            if placeholders:
                results.append(
                    _result(
                        VerificationStatus.SKIP,
                        "SCPI",
                        f"scpi.query.{name}",
                        f"Skipped query '{name}' because it requires parameters.",
                        observed=", ".join(placeholders),
                    )
                )
                continue

            cmd = engine.build(name)[0]
            raw = context.instrument._query(cmd)
            parsed = engine.parse(name, raw)
            results.append(
                _result(
                    VerificationStatus.PASS,
                    "SCPI",
                    f"scpi.query.{name}",
                    f"Query '{name}' executed and parsed successfully.",
                    observed=parsed,
                )
            )
        except Exception as exc:
            results.append(
                _result(
                    VerificationStatus.FAIL,
                    "SCPI",
                    f"scpi.query.{name}",
                    f"Query '{name}' failed during runtime execution.",
                    details=str(exc),
                )
            )
    return results


def _plugin_multimeter(context: VerificationContext) -> list[VerificationResult]:
    results: list[VerificationResult] = []
    snapshot = None
    if hasattr(context.instrument, "get_config"):
        try:
            snapshot = context.instrument.get_config()
            results.append(
                _result(
                    VerificationStatus.PASS,
                    "Plugin",
                    "plugin.multimeter.get-config",
                    "Multimeter configuration snapshot succeeded.",
                    observed=getattr(snapshot, "measurement_mode", type(snapshot).__name__),
                )
            )
        except Exception as exc:
            results.append(
                _result(
                    VerificationStatus.FAIL,
                    "Plugin",
                    "plugin.multimeter.get-config",
                    "Multimeter configuration snapshot failed.",
                    details=str(exc),
                )
            )
    if context.probe_mode == "safe-write" and hasattr(context.instrument, "set_measurement_function"):
        from pytestlab.config.multimeter_config import DMMFunction

        current_mode = getattr(snapshot, "measurement_mode", None)
        if current_mode is None:
            return [
                *results,
                _result(
                    VerificationStatus.SKIP,
                    "Plugin",
                    "plugin.multimeter.set-function",
                    "Skipped measurement function write probe because current mode is unknown.",
                ),
            ]

        try:
            current_function = DMMFunction(current_mode)
        except Exception:
            results.append(
                _result(
                    VerificationStatus.SKIP,
                    "Plugin",
                    "plugin.multimeter.set-function",
                    "Skipped measurement function write probe because current mode is unsupported.",
                    observed=current_mode,
                )
            )
            return results

        try:
            context.instrument.set_measurement_function(current_function)
            results.append(
                _result(
                    VerificationStatus.PASS,
                    "Plugin",
                    "plugin.multimeter.set-function",
                    "Measurement function write probe reapplied the current mode.",
                    observed=current_function.value,
                )
            )
        except Exception as exc:
            results.append(
                _result(
                    VerificationStatus.FAIL,
                    "Plugin",
                    "plugin.multimeter.set-function",
                    "Measurement function write probe failed.",
                    details=str(exc),
                )
            )
    return results


def _plugin_power_supply(context: VerificationContext) -> list[VerificationResult]:
    results: list[VerificationResult] = []
    channel = _first_channel_id(context.config)

    if hasattr(context.instrument, "get_configuration"):
        try:
            snapshot = context.instrument.get_configuration()
            results.append(
                _result(
                    VerificationStatus.PASS,
                    "Plugin",
                    "plugin.psu.get-configuration",
                    "Power supply configuration snapshot succeeded.",
                    observed=len(snapshot),
                )
            )
        except Exception as exc:
            snapshot = {}
            results.append(
                _result(
                    VerificationStatus.FAIL,
                    "Plugin",
                    "plugin.psu.get-configuration",
                    "Power supply configuration snapshot failed.",
                    details=str(exc),
                )
            )
    else:
        snapshot = {}

    for method_name in ("read_voltage", "read_current"):
        if hasattr(context.instrument, method_name):
            try:
                value = getattr(context.instrument, method_name)(channel)
                results.append(
                    _result(
                        VerificationStatus.PASS,
                        "Plugin",
                        f"plugin.psu.{method_name}",
                        f"{method_name} probe succeeded on channel {channel}.",
                        observed=value,
                    )
                )
            except Exception as exc:
                results.append(
                    _result(
                        VerificationStatus.FAIL,
                        "Plugin",
                        f"plugin.psu.{method_name}",
                        f"{method_name} probe failed on channel {channel}.",
                        details=str(exc),
                    )
                )

    if context.probe_mode == "safe-write" and snapshot:
        channel_cfg = snapshot.get(channel)
        if channel_cfg is not None:
            voltage = getattr(channel_cfg, "voltage", None)
            current = getattr(channel_cfg, "current", None)
            state = str(getattr(channel_cfg, "state", "")).upper()
            if hasattr(context.instrument, "set_voltage") and voltage is not None:
                if context.allow_output_enable:
                    try:
                        context.instrument.set_voltage(channel, float(voltage))
                        results.append(
                            _result(
                                VerificationStatus.PASS,
                                "Plugin",
                                "plugin.psu.set-voltage",
                                "Voltage write probe succeeded with existing channel value.",
                                observed=voltage,
                            )
                        )
                    except Exception as exc:
                        results.append(
                            _result(
                                VerificationStatus.FAIL,
                                "Plugin",
                                "plugin.psu.set-voltage",
                                "Voltage write probe failed.",
                                details=str(exc),
                            )
                        )
                else:
                    results.append(
                        _result(
                            VerificationStatus.SKIP,
                            "Plugin",
                            "plugin.psu.set-voltage",
                            "Skipped voltage write probe because --allow-output-enable was not set.",
                        )
                    )
            if hasattr(context.instrument, "set_current") and current is not None:
                if context.allow_output_enable:
                    try:
                        context.instrument.set_current(channel, float(current))
                        results.append(
                            _result(
                                VerificationStatus.PASS,
                                "Plugin",
                                "plugin.psu.set-current",
                                "Current write probe succeeded with existing channel value.",
                                observed=current,
                            )
                        )
                    except Exception as exc:
                        results.append(
                            _result(
                                VerificationStatus.FAIL,
                                "Plugin",
                                "plugin.psu.set-current",
                                "Current write probe failed.",
                                details=str(exc),
                            )
                        )
                else:
                    results.append(
                        _result(
                            VerificationStatus.SKIP,
                            "Plugin",
                            "plugin.psu.set-current",
                            "Skipped current write probe because --allow-output-enable was not set.",
                        )
                    )
            if hasattr(context.instrument, "output"):
                if context.allow_output_enable:
                    try:
                        context.instrument.output(channel, state == "ON")
                        results.append(
                            _result(
                                VerificationStatus.PASS,
                                "Plugin",
                                "plugin.psu.output-state",
                                "Output state probe reapplied the existing output state.",
                                observed=state or "UNKNOWN",
                            )
                        )
                    except Exception as exc:
                        results.append(
                            _result(
                                VerificationStatus.FAIL,
                                "Plugin",
                                "plugin.psu.output-state",
                                "Output state probe failed.",
                                details=str(exc),
                            )
                        )
                else:
                    results.append(
                        _result(
                            VerificationStatus.SKIP,
                            "Plugin",
                            "plugin.psu.output-state",
                            "Skipped output-state probe because --allow-output-enable was not set.",
                        )
                    )
    return results


def _plugin_oscilloscope(context: VerificationContext) -> list[VerificationResult]:
    results: list[VerificationResult] = []
    for method_name in ("get_acquire_points", "get_sampling_rate"):
        if hasattr(context.instrument, method_name):
            try:
                value = getattr(context.instrument, method_name)()
                results.append(
                    _result(
                        VerificationStatus.PASS,
                        "Plugin",
                        f"plugin.scope.{method_name}",
                        f"{method_name} probe succeeded.",
                        observed=value,
                    )
                )
            except Exception as exc:
                results.append(
                    _result(
                        VerificationStatus.FAIL,
                        "Plugin",
                        f"plugin.scope.{method_name}",
                        f"{method_name} probe failed.",
                        details=str(exc),
                    )
                )
    return results


def _plugin_waveform_generator(context: VerificationContext) -> list[VerificationResult]:
    results: list[VerificationResult] = []
    channel = _first_channel_id(context.config)

    for method_name in ("get_frequency", "get_amplitude", "get_output_state"):
        if hasattr(context.instrument, method_name):
            try:
                value = getattr(context.instrument, method_name)(channel)
                results.append(
                    _result(
                        VerificationStatus.PASS,
                        "Plugin",
                        f"plugin.awg.{method_name}",
                        f"{method_name} probe succeeded on channel {channel}.",
                        observed=value,
                    )
                )
            except Exception as exc:
                results.append(
                    _result(
                        VerificationStatus.FAIL,
                        "Plugin",
                        f"plugin.awg.{method_name}",
                        f"{method_name} probe failed on channel {channel}.",
                        details=str(exc),
                    )
                )

    if context.probe_mode == "safe-write":
        if hasattr(context.instrument, "get_frequency") and hasattr(context.instrument, "set_frequency"):
            if context.allow_output_enable:
                try:
                    freq = context.instrument.get_frequency(channel)
                    context.instrument.set_frequency(channel, float(freq))
                    results.append(
                        _result(
                            VerificationStatus.PASS,
                            "Plugin",
                            "plugin.awg.set-frequency",
                            "Frequency write probe succeeded with the current value.",
                            observed=freq,
                        )
                    )
                except Exception as exc:
                    results.append(
                        _result(
                            VerificationStatus.FAIL,
                            "Plugin",
                            "plugin.awg.set-frequency",
                            "Frequency write probe failed.",
                            details=str(exc),
                        )
                    )
            else:
                results.append(
                    _result(
                        VerificationStatus.SKIP,
                        "Plugin",
                        "plugin.awg.set-frequency",
                        "Skipped frequency write probe because --allow-output-enable was not set.",
                    )
                )

        if hasattr(context.instrument, "get_amplitude") and hasattr(context.instrument, "set_amplitude"):
            if context.allow_output_enable:
                try:
                    amp = context.instrument.get_amplitude(channel)
                    context.instrument.set_amplitude(channel, float(amp))
                    results.append(
                        _result(
                            VerificationStatus.PASS,
                            "Plugin",
                            "plugin.awg.set-amplitude",
                            "Amplitude write probe succeeded with the current value.",
                            observed=amp,
                        )
                    )
                except Exception as exc:
                    results.append(
                        _result(
                            VerificationStatus.FAIL,
                            "Plugin",
                            "plugin.awg.set-amplitude",
                            "Amplitude write probe failed.",
                            details=str(exc),
                        )
                    )
            else:
                results.append(
                    _result(
                        VerificationStatus.SKIP,
                        "Plugin",
                        "plugin.awg.set-amplitude",
                        "Skipped amplitude write probe because --allow-output-enable was not set.",
                    )
                )

        if hasattr(context.instrument, "set_output_state"):
            if context.allow_output_enable:
                try:
                    state = context.instrument.get_output_state(channel)
                    context.instrument.set_output_state(channel, state)
                    results.append(
                        _result(
                            VerificationStatus.PASS,
                            "Plugin",
                            "plugin.awg.output-state",
                            "Output state probe reapplied the existing output state.",
                            observed=state,
                        )
                    )
                except Exception as exc:
                    results.append(
                        _result(
                            VerificationStatus.FAIL,
                            "Plugin",
                            "plugin.awg.output-state",
                            "Output state probe failed.",
                            details=str(exc),
                        )
                    )
            else:
                results.append(
                    _result(
                        VerificationStatus.SKIP,
                        "Plugin",
                        "plugin.awg.output-state",
                        "Skipped output-state probe because --allow-output-enable was not set.",
                    )
                )
    return results


_PLUGIN_REGISTRY: dict[str, Any] = {
    "multimeter": _plugin_multimeter,
    "power_supply": _plugin_power_supply,
    "oscilloscope": _plugin_oscilloscope,
    "waveform_generator": _plugin_waveform_generator,
}


def verify_instrument_profile(
    profile_source: str | Path,
    *,
    address: str | None = None,
    probe_mode: ProbeMode = "read-only",
    allow_output_enable: bool = False,
    timeout_ms: int | None = None,
    fail_fast: bool = False,
) -> VerificationReport:
    probe_mode = _validate_probe_mode(probe_mode)
    config = load_profile(profile_source)
    report = VerificationReport(
        profile_source=profile_source,
        device_type=config.device_type,
        manufacturer=config.manufacturer,
        model=config.model,
        probe_mode=probe_mode,
        address_override=address,
    )
    report.add(
        _result(
            VerificationStatus.PASS,
            "Schema",
            "schema.load-profile",
            "Profile loaded and validated successfully.",
            observed=f"{config.manufacturer} {config.model}",
        )
    )

    instrument = AutoInstrument.from_config(
        config_source=config,
        address_override=address,
        timeout_override_ms=timeout_ms,
    )
    connected = False
    try:
        instrument.connect_backend()
        connected = True
        report.add(
            _result(
                VerificationStatus.PASS,
                "Connection",
                "connection.backend",
                "Backend connection succeeded.",
                observed=type(getattr(instrument, "_backend", None)).__name__,
            )
        )

        context = VerificationContext(
            profile_source=profile_source,
            config=config,
            instrument=instrument,
            probe_mode=probe_mode,
            allow_output_enable=allow_output_enable,
            fail_fast=fail_fast,
            address_override=address,
            timeout_ms=timeout_ms,
        )

        blocks = [
            lambda: [_run_identity_check(context)],
            lambda: _run_scpi_presence_checks(context),
            lambda: _PLUGIN_REGISTRY.get(config.device_type, lambda _context: [])(context),
        ]
        if probe_mode == "safe-write":
            blocks.insert(1, lambda: _run_health_checks(context))
            blocks.insert(3, lambda: _run_generic_query_smoke_checks(context))

        for block_factory in blocks:
            block = block_factory()
            for result in block:
                report.add(result)
                if fail_fast and result.status in {VerificationStatus.FAIL, VerificationStatus.ERROR}:
                    return report
    except Exception as exc:
        status = VerificationStatus.ERROR if not connected else VerificationStatus.FAIL
        category = "Connection" if not connected else "Verification"
        report.add(
            _result(
                status,
                category,
                "runtime.exception",
                "Verification terminated with an exception.",
                details=str(exc),
            )
        )
    finally:
        try:
            instrument.close()
        except Exception as exc:
            report.add(
                _result(
                    VerificationStatus.WARN,
                    "Cleanup",
                    "cleanup.close",
                    "Instrument close raised an exception.",
                    details=str(exc),
                )
            )
    return report


def render_verification_report(report: VerificationReport, console: Console | None = None) -> None:
    console = console or Console()
    counts = report.counts
    status_text = Text(
        _STATUS_ICONS[report.overall_status.value],
        style=_STATUS_COLORS[report.overall_status.value],
    )

    console.rule("[bold cyan]Instrument Profile Verification[/bold cyan]")
    console.print(
        f"[bold]Profile:[/bold] {report.profile_source}\n"
        f"[bold]Instrument:[/bold] {report.manufacturer} {report.model} ({report.device_type})\n"
        f"[bold]Probe mode:[/bold] {report.probe_mode}\n"
        f"[bold]Address override:[/bold] {report.address_override or '-'}\n"
        f"[bold]Overall:[/bold] ",
        end="",
    )
    console.print(status_text)
    console.print(
        f"[green]PASS[/green]={counts['pass']}  "
        f"[red]FAIL[/red]={counts['fail']}  "
        f"[yellow]WARN[/yellow]={counts['warn']}  "
        f"[dim]SKIP[/dim]={counts['skip']}  "
        f"[bold red]ERROR[/bold red]={counts['error']}"
    )

    table = Table(show_header=True, header_style="bold")
    table.add_column("Status", style="bold", width=8)
    table.add_column("Category", style="cyan", width=12)
    table.add_column("Check", style="white")
    table.add_column("Details", style="white")

    for result in report.results:
        details = result.summary
        fragments = []
        if result.expected is not None:
            fragments.append(f"expected={result.expected}")
        if result.observed is not None:
            fragments.append(f"observed={result.observed}")
        if result.details:
            fragments.append(result.details)
        if fragments:
            details = f"{details} ({'; '.join(fragments)})"

        table.add_row(
            Text(_STATUS_ICONS[result.status.value], style=_STATUS_COLORS[result.status.value]),
            result.category,
            result.id,
            details,
        )

    console.print(table)
