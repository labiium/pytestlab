from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .accessories import AccessoryProfile
from .accessories import BoundAccessory
from .accessories import MeasurementChain
from .config.bench_config import BenchConfigExtended
from .config.bench_config import DCLoadReadbackTarget
from .config.bench_config import MeasurementPlanEntry
from .config.bench_config import MultimeterFunctionTarget
from .config.bench_config import OscilloscopeChannelTarget
from .config.bench_config import PowerSupplyReadbackTarget
from .config.bench_config import RouteEntry
from .config.loader import load_device_profile
from .config.switch_matrix_config import SwitchMatrixConfig
from .errors import InstrumentConfigurationError
from .experiments.results import MeasurementResult


@dataclass(frozen=True)
class PreparedMeasurementPlan:
    bound_accessories: dict[str, BoundAccessory]
    errors: list[str]


@dataclass(frozen=True)
class MeasurementDescriptor:
    name: str
    description: str | None
    resource: str
    target: dict[str, Any] | None
    physical_path: list[str]
    driver_call: str | None
    route: dict[str, Any] | None
    accessories: list[dict[str, Any]]
    budget_note: str

    def render(self) -> str:
        lines = [self.name]
        if self.description:
            lines.append(f"  Description: {self.description}")
        lines.append(f"  Resource: {self.resource}")
        lines.append(f"  Target: {self.target if self.target is not None else 'descriptive'}")
        if self.physical_path:
            lines.append(f"  Physical path: {' -> '.join(self.physical_path)}")
        if self.driver_call:
            lines.append(f"  Driver call: {self.driver_call}")
        if self.route:
            lines.append(f"  Route: {self.route['name']}")
            if self.route.get("description"):
                lines.append(f"    Description: {self.route['description']}")
            if self.route.get("device"):
                lines.append(f"    Switching device: {self.route['device']}")
            for connection in self.route.get("connects", []):
                path = f" via {' -> '.join(connection['path'])}" if connection.get("path") else ""
                lines.append(f"    {connection['from']} -> {connection['to']}{path}")
            if self.route.get("accessories"):
                lines.append(f"    Route accessories: {', '.join(self.route['accessories'])}")
            if self.route.get("settling_time_s") is not None:
                lines.append(f"    Settling time: {self.route['settling_time_s']} s")
        lines.append(f"  Budget status: {self.budget_note}")
        if self.accessories:
            lines.append("  Accessory chain:")
            for accessory in self.accessories:
                source = accessory.get("profile_key") or accessory.get("profile_file") or "direct"
                lines.append(
                    "    "
                    f"{accessory['alias']} ({accessory['display_name']}, "
                    f"{accessory['accessory_type']}, source={source}, "
                    f"review={accessory['review_status']})"
                )
                if accessory.get("serial_number"):
                    lines.append(f"      Serial: {accessory['serial_number']}")
                if accessory.get("notes"):
                    lines.append(f"      Notes: {accessory['notes']}")
                for correction in accessory.get("corrections", []):
                    unit = f" {correction['unit']}" if correction["unit"] else ""
                    lines.append(
                        f"      Correction: {correction['operation']} "
                        f"{correction['nominal']:g}{unit} ({correction['name']})"
                    )
        else:
            lines.append("  Accessory chain: none")
        return "\n".join(lines)


def prepare_declared_measurements(
    config: BenchConfigExtended,
    *,
    base_path: Path | None = None,
    include_route_validation: bool = True,
) -> PreparedMeasurementPlan:
    errors: list[str] = []
    bound_accessories: dict[str, BoundAccessory] = {}
    entries = config.devices | config.instruments
    if include_route_validation:
        errors.extend(validate_declared_routes(config, base_path=base_path))

    device_configs: dict[str, Any] = {}
    for alias, entry in entries.items():
        try:
            device_configs[alias] = load_device_profile(_device_entry_source(entry, base_path))
        except Exception as exc:
            errors.append(f"{alias}: failed to load {entry.source_kind} '{entry.source}': {exc}")

    for alias, entry in config.accessories.items():
        try:
            bound_accessories[alias] = bind_accessory(alias, entry, base_path=base_path)
        except Exception as exc:
            errors.append(f"{alias}: failed to load accessory profile: {exc}")

    for plan_entry in config.measurement_plan or []:
        target = plan_entry.execution_target
        if target is None:
            continue
        alias = plan_entry.target_alias
        if alias not in entries:
            errors.append(f"{plan_entry.name}: instrument/resource alias '{alias}' is not defined.")
            continue
        for accessory_alias in plan_entry.accessories:
            if accessory_alias not in config.accessories:
                errors.append(
                    f"{plan_entry.name}: accessory alias '{accessory_alias}' is not defined."
                )
            elif accessory_alias not in bound_accessories:
                errors.append(
                    f"{plan_entry.name}: accessory alias '{accessory_alias}' could not be loaded."
                )
            else:
                _validate_accessory_target_compatibility(
                    plan_entry.name,
                    accessory_alias,
                    bound_accessories[accessory_alias],
                    target,
                    errors,
                )
        if plan_entry.route is not None:
            route = config.routes.get(plan_entry.route)
            if route is None:
                errors.append(f"{plan_entry.name}: route '{plan_entry.route}' is not defined.")
            elif route.device is not None and route.device not in entries:
                errors.append(
                    f"{plan_entry.name}: route '{plan_entry.route}' uses unknown "
                    f"switching device '{route.device}'."
                )
            elif _expected_target_endpoints(plan_entry) is None:
                errors.append(
                    f"{plan_entry.name}: routes are not supported for target kind "
                    f"'{target.kind}' because PyTestLab v1 has no endpoint mapping for it."
                )
            elif not _route_matches_target(route, plan_entry):
                errors.append(
                    f"{plan_entry.name}: route '{plan_entry.route}' does not include "
                    f"one of the measurement target endpoint(s) "
                    f"{sorted(_expected_target_endpoints(plan_entry) or [])!r}."
                )
            elif plan_entry.accessories != route.accessories:
                errors.append(
                    f"{plan_entry.name}: route '{plan_entry.route}' declares accessories "
                    f"{route.accessories!r}, but measurement_plan applies "
                    f"{plan_entry.accessories!r}. For v1 auditable measurements these "
                    "lists must match in order so physical route provenance and applied "
                    "uncertainty corrections cannot drift."
                )
        device_config = device_configs.get(alias)
        if device_config is None:
            continue
        device_type = getattr(device_config, "device_type", None)
        if isinstance(target, OscilloscopeChannelTarget):
            if device_type != "oscilloscope":
                errors.append(f"{plan_entry.name}: oscilloscope target cannot use {device_type}.")
            _validate_channel(plan_entry.name, target.channel, device_config, errors)
        elif isinstance(target, MultimeterFunctionTarget):
            if device_type != "multimeter":
                errors.append(f"{plan_entry.name}: multimeter target cannot use {device_type}.")
        elif isinstance(target, PowerSupplyReadbackTarget):
            if device_type != "power_supply":
                errors.append(f"{plan_entry.name}: power-supply target cannot use {device_type}.")
            _validate_channel(plan_entry.name, target.channel, device_config, errors)
        elif isinstance(target, DCLoadReadbackTarget):
            if device_type != "dc_active_load":
                errors.append(f"{plan_entry.name}: dc-load target cannot use {device_type}.")

    return PreparedMeasurementPlan(bound_accessories=bound_accessories, errors=errors)


def validate_declared_routes(
    config: BenchConfigExtended, *, base_path: Path | None = None
) -> list[str]:
    """Return semantic validation errors for dry-run route declarations."""

    errors: list[str] = []
    entries = config.devices | config.instruments
    resources = set(config.devices) | set(config.instruments) | {"dut"}
    accessory_aliases = set(config.accessories)
    device_configs: dict[str, Any] = {}
    device_config_errors: dict[str, Exception] = {}
    for alias, entry in entries.items():
        try:
            device_configs[alias] = load_device_profile(_device_entry_source(entry, base_path))
        except Exception as exc:
            device_config_errors[alias] = exc
    for route_name, route in config.routes.items():
        if route.device is not None and route.device not in config.devices:
            errors.append(
                f"{route_name}: route device '{route.device}' must be declared under devices."
            )
        switch_config: SwitchMatrixConfig | None = None
        if route.device is not None and route.device in config.devices:
            try:
                candidate = load_device_profile(
                    _device_entry_source(config.devices[route.device], base_path)
                )
                if isinstance(candidate, SwitchMatrixConfig):
                    switch_config = candidate
                else:
                    errors.append(
                        f"{route_name}: route device '{route.device}' must resolve to "
                        f"a switch_matrix profile, not '{getattr(candidate, 'device_type', None)}'."
                    )
            except Exception as exc:
                errors.append(
                    f"{route_name}: failed to load route device '{route.device}' profile: {exc}"
                )
        for accessory_alias in route.accessories:
            if accessory_alias not in accessory_aliases:
                errors.append(f"{route_name}: route accessory '{accessory_alias}' is not defined.")
        for connection in route.connects:
            for endpoint in (connection.from_endpoint, connection.to):
                alias = endpoint.split(".", 1)[0]
                if alias not in resources:
                    errors.append(
                        f"{route_name}: route endpoint '{endpoint}' starts with unknown "
                        f"resource '{alias}'. Known resources: {', '.join(sorted(resources))}."
                    )
                else:
                    if alias != "dut" and alias not in device_configs:
                        exc = device_config_errors.get(alias)
                        detail = f": {exc}" if exc is not None else ""
                        errors.append(
                            f"{route_name}: failed to load route endpoint resource "
                            f"'{alias}' profile{detail}."
                        )
                        continue
                    endpoint_errors = _validate_route_endpoint(
                        endpoint,
                        None if alias == "dut" else device_configs.get(alias),
                        switch_config,
                    )
                    errors.extend(f"{route_name}: {error}" for error in endpoint_errors)
            if route.device is not None and not connection.path:
                errors.append(
                    f"{route_name}: route through switching device '{route.device}' must "
                    "declare a non-empty physical switch path."
                )
            if switch_config is not None:
                try:
                    route_terminals = {connection.from_endpoint, connection.to}
                    switch_config.validate_route_terminals(route_name, route_terminals)
                    if connection.path:
                        switch_config.validate_path(connection.path)
                except Exception as exc:
                    errors.append(f"{route_name}: invalid switch route: {exc}")
    return errors


def _validate_route_endpoint(
    endpoint: str, device_config: Any | None, switch_config: Any | None
) -> list[str]:
    errors: list[str] = []
    if "." not in endpoint:
        errors.append(f"route endpoint '{endpoint}' must include a terminal suffix.")
        return errors
    if switch_config is not None and endpoint not in getattr(switch_config, "terminals", []):
        allowed = ", ".join(getattr(switch_config, "terminals", []))
        errors.append(
            f"route endpoint '{endpoint}' is not declared on switch terminals: {allowed}."
        )
    if device_config is None:
        return errors
    device_type = getattr(device_config, "device_type", None)
    suffix = endpoint.split(".", 1)[1].upper()
    if device_type in {"oscilloscope", "power_supply"}:
        channels = getattr(device_config, "channels", None)
        if channels is None:
            return errors
        if not suffix.startswith("CH") or not suffix[2:].isdigit():
            errors.append(f"route endpoint '{endpoint}' must use CH<n> for {device_type}.")
            return errors
        channel = int(suffix[2:])
        if not 1 <= channel <= len(channels):
            errors.append(
                f"route endpoint '{endpoint}' channel is outside configured range 1-{len(channels)}."
            )
    elif device_type == "multimeter":
        allowed = {"HI", "LO", "V.HI", "V.LO", "I.HI", "I.LO"}
        if suffix not in allowed:
            errors.append(
                f"route endpoint '{endpoint}' must use one of {', '.join(sorted(allowed))}."
            )
    return errors


def _expected_target_endpoints(entry: MeasurementPlanEntry) -> set[str] | None:
    target = entry.execution_target
    alias = entry.target_alias
    if isinstance(target, OscilloscopeChannelTarget | PowerSupplyReadbackTarget):
        return {f"{alias}.CH{target.channel}"}
    if isinstance(target, MultimeterFunctionTarget):
        if target.function.startswith("current"):
            return {f"{alias}.I.HI", f"{alias}.HI"}
        return {f"{alias}.V.HI", f"{alias}.HI"}
    return None


def _route_matches_target(route: RouteEntry, entry: MeasurementPlanEntry) -> bool:
    expected = _expected_target_endpoints(entry)
    if not expected:
        return True
    endpoints = {
        endpoint
        for connection in route.connects
        for endpoint in (connection.from_endpoint, connection.to)
    }
    return bool(expected & endpoints)


def _device_entry_source(entry: Any, base_path: Path | None = None) -> str | Path:
    if hasattr(entry, "resolved_source"):
        return entry.resolved_source(base_path=base_path)
    return entry.profile


def build_route_descriptor(name: str, route: RouteEntry) -> dict[str, Any]:
    """Build a stable, human-readable route descriptor without touching hardware."""

    return {
        "name": name,
        "description": route.description,
        "device": route.device,
        "connects": [
            {
                "from": connection.from_endpoint,
                "to": connection.to,
                "path": list(connection.path),
            }
            for connection in route.connects
        ],
        "accessories": list(route.accessories),
        "settling_time_s": route.settling_time_s,
        "exclusive_group": route.exclusive_group,
    }


def describe_declared_route(name: str, route: RouteEntry) -> str:
    descriptor = build_route_descriptor(name, route)
    lines = [f"Route: {descriptor['name']}"]
    if descriptor.get("description"):
        lines.append(f"  Description: {descriptor['description']}")
    if descriptor.get("device"):
        lines.append(f"  Switching device: {descriptor['device']}")
    for connection in descriptor["connects"]:
        path = f" via {' -> '.join(connection['path'])}" if connection["path"] else ""
        lines.append(f"  {connection['from']} -> {connection['to']}{path}")
    if descriptor["accessories"]:
        lines.append(f"  Accessories: {', '.join(descriptor['accessories'])}")
    if descriptor.get("settling_time_s") is not None:
        lines.append(f"  Settling time: {descriptor['settling_time_s']} s")
    if descriptor.get("exclusive_group"):
        lines.append(f"  Exclusive group: {descriptor['exclusive_group']}")
    return "\n".join(lines)


def load_bound_accessories(
    config: BenchConfigExtended, *, base_path: Path | None = None
) -> dict[str, BoundAccessory]:
    prepared = prepare_declared_measurements(config, base_path=base_path)
    accessory_errors = [
        error for error in prepared.errors if "failed to load accessory profile" in error
    ]
    if accessory_errors:
        raise InstrumentConfigurationError("accessories", "\n".join(accessory_errors))
    return prepared.bound_accessories


def bind_accessory(alias: str, entry: Any, *, base_path: Path | None = None) -> BoundAccessory:
    if entry.profile is not None:
        profile = AccessoryProfile.from_config(entry.profile)
        profile_key = entry.profile
        profile_file = None
    else:
        if entry.file is None:  # pragma: no cover - pydantic validates this
            raise ValueError("missing file")
        profile_path = Path(entry.file)
        if not profile_path.is_absolute() and base_path is not None:
            profile_path = base_path / profile_path
        profile = AccessoryProfile.from_file(profile_path)
        profile_key = None
        profile_file = str(profile_path)
    if entry.parameters:
        profile = profile.with_parameters(**entry.parameters)
    else:
        profile.validate_parameters()
    return BoundAccessory(
        alias=alias,
        profile=profile,
        profile_key=profile_key,
        profile_file=profile_file,
        serial_number=entry.serial_number,
        parameters=dict(entry.parameters or {}),
        notes=entry.notes,
    )


def validate_declared_measurements(
    config: BenchConfigExtended,
    *,
    base_path: Path | None = None,
    include_route_validation: bool = True,
) -> list[str]:
    """Return semantic validation errors for executable measurement_plan entries."""

    return prepare_declared_measurements(
        config,
        base_path=base_path,
        include_route_validation=include_route_validation,
    ).errors


def raise_for_declared_measurement_errors(errors: list[str]) -> None:
    if errors:
        raise InstrumentConfigurationError("measurement_plan", "\n".join(errors))


def build_measurement_descriptor(
    entry: MeasurementPlanEntry,
    bound_accessories: dict[str, BoundAccessory],
    routes: dict[str, RouteEntry] | None = None,
) -> MeasurementDescriptor:
    target = entry.execution_target
    accessories = [_accessory_descriptor(bound_accessories[alias]) for alias in entry.accessories]
    route_descriptor = None
    if entry.route is not None and routes is not None and entry.route in routes:
        route_descriptor = build_route_descriptor(entry.route, routes[entry.route])
    return MeasurementDescriptor(
        name=entry.name,
        description=entry.description,
        resource=entry.target_alias,
        target=target.model_dump(mode="json") if target is not None else None,
        physical_path=_physical_path(entry, bound_accessories),
        driver_call=_driver_call(entry),
        route=route_descriptor,
        accessories=accessories,
        budget_note=(
            "known after execution; result envelope records whether instrument "
            "uncertainty was included"
        ),
    )


def describe_declared_measurement(
    entry: MeasurementPlanEntry,
    bound_accessories: dict[str, BoundAccessory],
    routes: dict[str, RouteEntry] | None = None,
) -> str:
    return build_measurement_descriptor(entry, bound_accessories, routes).render()


def measurement_chain_for(
    entry: MeasurementPlanEntry,
    bound_accessories: dict[str, BoundAccessory],
) -> MeasurementChain:
    missing = [alias for alias in entry.accessories if alias not in bound_accessories]
    if missing:
        raise ValueError(
            f"Measurement '{entry.name}' references unknown accessor"
            f"{'y' if len(missing) == 1 else 'ies'}: {', '.join(missing)}"
        )
    return MeasurementChain([bound_accessories[alias] for alias in entry.accessories])


def execute_declared_measurement(
    bench: Any,
    entry: MeasurementPlanEntry,
    bound_accessories: dict[str, BoundAccessory],
) -> Any:
    target = entry.execution_target
    if target is None:
        raise ValueError(f"Measurement plan entry '{entry.name}' is descriptive, not executable.")
    resource = getattr(bench, entry.target_alias)

    if isinstance(target, OscilloscopeChannelTarget):
        if target.measurement == "vpp":
            raw = resource.measure_voltage_peak_to_peak(target.channel)
        elif target.measurement == "rms_voltage":
            raw = resource.measure_rms_voltage(target.channel)
        else:  # pragma: no cover - pydantic enforces this
            raise NotImplementedError(target.measurement)
    elif isinstance(target, MultimeterFunctionTarget):
        from .config.multimeter_config import DMMFunction

        function_map = {
            "voltage_dc": DMMFunction.VOLTAGE_DC,
            "voltage_ac": DMMFunction.VOLTAGE_AC,
            "current_dc": DMMFunction.CURRENT_DC,
            "current_ac": DMMFunction.CURRENT_AC,
            "resistance": DMMFunction.RESISTANCE,
            "resistance_4wire": DMMFunction.FRESISTANCE,
            "capacitance": DMMFunction.CAPACITANCE,
            "frequency": DMMFunction.FREQUENCY,
            "temperature": DMMFunction.TEMPERATURE,
        }
        settings = entry.settings or {}
        raw = resource.measure(
            function_map[target.function],
            range_val=_dmm_setting_to_scpi(settings.get("range")),
            resolution=_dmm_setting_to_scpi(settings.get("resolution")),
        )
    elif isinstance(target, PowerSupplyReadbackTarget):
        if target.quantity == "voltage":
            raw = resource.read_voltage(target.channel)
            raw = _scalar_result(entry, raw, "V", "Voltage")
        elif target.quantity == "current":
            raw = resource.read_current(target.channel)
            raw = _scalar_result(entry, raw, "A", "Current")
        else:  # pragma: no cover - pydantic enforces this
            raise NotImplementedError(target.quantity)
    elif isinstance(target, DCLoadReadbackTarget):
        if target.quantity == "voltage":
            raw = resource.measure_voltage()
        elif target.quantity == "current":
            raw = resource.measure_current()
        elif target.quantity == "power":
            raw = resource.measure_power()
        else:  # pragma: no cover - pydantic enforces this
            raise NotImplementedError(target.quantity)
    else:  # pragma: no cover - pydantic enforces this
        raise NotImplementedError(type(target).__name__)

    chain = measurement_chain_for(entry, bound_accessories)
    result = chain.apply(raw) if entry.accessories else raw
    return _attach_route_envelope(bench, entry, result)


def _attach_route_envelope(bench: Any, entry: MeasurementPlanEntry, result: Any) -> Any:
    if entry.route is None or not isinstance(result, MeasurementResult):
        return result
    routes = getattr(getattr(bench, "_config", None), "routes", {})
    route = routes.get(entry.route) if isinstance(routes, dict) else None
    if route is None:
        return result
    envelope = dict(getattr(result, "envelope", {}) or {})
    envelope["route"] = build_route_descriptor(entry.route, route)
    return MeasurementResult(
        values=result.values,
        instrument=result.instrument,
        units=result.units,
        measurement_type=result.measurement_type,
        timestamp=result.timestamp,
        envelope=envelope,
        sampling_rate=getattr(result, "sampling_rate", None),
    )


def _accessory_descriptor(accessory: BoundAccessory) -> dict[str, Any]:
    metadata = accessory.envelope_metadata()
    metadata["corrections"] = [
        {
            "name": correction.name,
            "operation": correction.operation,
            "nominal": correction.nominal,
            "unit": correction.unit,
            "source": correction.source,
        }
        for correction in accessory.corrections
    ]
    return metadata


def _physical_path(
    entry: MeasurementPlanEntry,
    bound_accessories: dict[str, BoundAccessory],
) -> list[str]:
    if entry.execution_target is None:
        return []
    path = ["DUT"]
    for alias in entry.accessories:
        accessory = bound_accessories[alias]
        path.append(f"{alias} ({accessory.display_name})")
    target = entry.execution_target
    if isinstance(target, OscilloscopeChannelTarget | PowerSupplyReadbackTarget):
        path.append(f"{entry.target_alias} CH{target.channel}")
    else:
        path.append(entry.target_alias)
    return path


def _driver_call(entry: MeasurementPlanEntry) -> str | None:
    target = entry.execution_target
    alias = entry.target_alias
    if target is None:
        return None
    if isinstance(target, OscilloscopeChannelTarget):
        method = (
            "measure_voltage_peak_to_peak" if target.measurement == "vpp" else "measure_rms_voltage"
        )
        return f"{alias}.{method}(channel={target.channel})"
    if isinstance(target, MultimeterFunctionTarget):
        return f"{alias}.measure(function={target.function!r})"
    if isinstance(target, PowerSupplyReadbackTarget):
        method = "read_voltage" if target.quantity == "voltage" else "read_current"
        return f"{alias}.{method}(channel={target.channel})"
    if isinstance(target, DCLoadReadbackTarget):
        return f"{alias}.measure_{target.quantity}()"
    return f"{alias}.<unsupported>()"


def _scalar_result(
    entry: MeasurementPlanEntry, value: Any, unit: str, measurement_type: str
) -> MeasurementResult:
    return MeasurementResult(
        values=value,
        instrument=entry.target_alias,
        units=unit,
        measurement_type=measurement_type,
    )


def _validate_channel(name: str, channel: int, device_config: Any, errors: list[str]) -> None:
    channels = getattr(device_config, "channels", None)
    if channels is None:
        return
    if not 1 <= channel <= len(channels):
        errors.append(f"{name}: channel {channel} is outside configured range 1-{len(channels)}.")


def _validate_accessory_target_compatibility(
    measurement_name: str,
    accessory_alias: str,
    accessory: BoundAccessory,
    target: Any,
    errors: list[str],
) -> None:
    target_kind = target.kind
    compatibility = accessory.profile.compatibility
    target_kinds = compatibility.get("target_kinds")
    if target_kinds is None:
        if compatibility.get("unrestricted_target_kinds") is True:
            return
        errors.append(
            f"{measurement_name}: accessory '{accessory_alias}' must declare "
            "compatibility.target_kinds or compatibility.unrestricted_target_kinds: true "
            "to be used in an executable measurement_plan entry."
        )
        return
    if not isinstance(target_kinds, list) or not all(
        isinstance(kind, str) for kind in target_kinds
    ):
        errors.append(
            f"{measurement_name}: accessory '{accessory_alias}' has invalid "
            "compatibility.target_kinds metadata."
        )
        return
    if target_kind not in target_kinds:
        allowed = ", ".join(target_kinds)
        errors.append(
            f"{measurement_name}: accessory '{accessory_alias}' is compatible with "
            f"{allowed}, not {target_kind}."
        )
        return
    if isinstance(target, MultimeterFunctionTarget):
        functions = compatibility.get("multimeter_functions")
        if functions is None:
            return
        if not isinstance(functions, list) or not all(
            isinstance(function, str) for function in functions
        ):
            errors.append(
                f"{measurement_name}: accessory '{accessory_alias}' has invalid "
                "compatibility.multimeter_functions metadata."
            )
            return
        if target.function not in functions:
            allowed = ", ".join(functions)
            errors.append(
                f"{measurement_name}: accessory '{accessory_alias}' is compatible with "
                f"multimeter functions {allowed}, not {target.function}."
            )


def _dmm_setting_to_scpi(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
