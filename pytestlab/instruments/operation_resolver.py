"""Shared semantic operation-option discovery and resolution.

This module is deliberately independent of communication backends.  It consumes
an already validated profile, a driver's explicit operation contract, and the
SCPI engine only as a private transport mapping source.
"""

from __future__ import annotations

import math
import numbers
import re
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field
from enum import Enum
from typing import Any

from ..config.operation_options import ProfileOperationParameter
from ..errors import InstrumentConfigurationError
from ..errors import InstrumentParameterError
from ..errors import OperationDiscoveryError
from .operation_contract import OperationDescription
from .operation_contract import OperationDescriptor
from .operation_contract import OperationOption
from .operation_contract import OperationParameterDescription
from .operation_contract import OperationSupportReport
from .operation_contract import ResolvedOperationParameter

_MISSING = object()


@dataclass
class _Candidate:
    value: Any
    label: str
    aliases: tuple[str, ...] = ()
    description: str | None = None
    unit: str | None = None
    supported: bool = True
    reason: str | None = None
    constraints: dict[str, Any] = field(default_factory=dict)
    transport_value: Any = _MISSING
    source: str | None = None

    def public(self) -> OperationOption:
        transport_aliases: set[str] = set()
        if self.transport_value is not _MISSING:
            token = str(self.transport_value)
            transport_aliases.add(token.casefold())
            abbreviated = "".join(character for character in token if not character.islower())
            if abbreviated:
                transport_aliases.add(abbreviated.casefold())
        aliases = tuple(
            alias for alias in self.aliases if str(alias).casefold() not in transport_aliases
        )
        constraints = {
            key: value
            for key, value in self.constraints.items()
            if key not in {"response_tokens", "transport", "token", "scpi"}
        }
        return OperationOption(
            value=self.value,
            label=self.label,
            description=self.description,
            aliases=aliases,
            unit=self.unit,
            supported=self.supported,
            reason=self.reason,
            constraints=constraints,
        )


@dataclass
class _ParameterData:
    kind: str
    required: bool = True
    default: Any = None
    unit: str | None = None
    description: str | None = None
    dependencies: tuple[str, ...] = ()
    constraints: dict[str, Any] = field(default_factory=dict)
    candidates: list[_Candidate] = field(default_factory=list)
    supported: bool = True
    reason: str | None = None
    source: str | None = None
    metadata_present: bool = False
    bindings: tuple[tuple[str, str], ...] = ()


class OperationResolver:
    """Resolve operation parameters against one profile and one driver contract."""

    def __init__(self, config: Any, descriptors: tuple[OperationDescriptor, ...], scpi_engine: Any):
        self.config = config
        self.descriptors = descriptors
        self._scpi_engine = scpi_engine

    # ------------------------------------------------------------------
    # Public API used by Instrument and offline CLI construction
    # ------------------------------------------------------------------
    def list_options(
        self,
        operation_id: str,
        parameter: str,
        *,
        context: Mapping[str, Any] | None = None,
        include_unsupported: bool = False,
        method_owner: Any | None = None,
    ) -> list[dict[str, Any]]:
        descriptor = self._descriptor(operation_id)
        if not include_unsupported and not self._capability_enabled(descriptor):
            raise OperationDiscoveryError(
                f"capability '{descriptor.capability}' is not enabled",
                code="unsupported_operation",
                operation_id=operation_id,
            )
        if parameter not in self._parameter_names(descriptor):
            raise OperationDiscoveryError(
                f"Parameter '{parameter}' is not declared for operation '{operation_id}'.",
                code="unknown_parameter",
                operation_id=operation_id,
                parameter=parameter,
            )
        normalized_context = self._validate_context(descriptor, context)
        data = self._parameter_data(descriptor, parameter, normalized_context)
        missing_dependencies = [
            dependency for dependency in data.dependencies if dependency not in normalized_context
        ]
        if missing_dependencies:
            raise OperationDiscoveryError(
                f"Parameter '{parameter}' requires context parameter(s): "
                f"{', '.join(missing_dependencies)}.",
                code="missing_dependency",
                operation_id=operation_id,
                parameter=parameter,
                context=dict(normalized_context),
                details={"required_parameters": list(data.dependencies)},
            )
        if data.kind not in {"enum", "bool"}:
            code = "parameter_not_enumerable" if data.metadata_present else "metadata_unresolved"
            reason = data.reason or (
                f"Parameter '{parameter}' is not an enumerable semantic option. "
                "Use describe_operation() for its numeric or textual constraints."
            )
            raise OperationDiscoveryError(
                reason,
                code=code,
                operation_id=operation_id,
                parameter=parameter,
                context=dict(normalized_context),
                details={"kind": data.kind},
            )
        candidates = data.candidates
        if not candidates and data.reason:
            # A declared but empty finite capability is an actionable metadata
            # failure, rather than an apparently unrestricted parameter.
            raise OperationDiscoveryError(
                data.reason,
                code="metadata_unresolved",
                operation_id=operation_id,
                parameter=parameter,
                context=dict(normalized_context),
            )
        if (
            candidates
            and not include_unsupported
            and not any(candidate.supported for candidate in candidates)
        ):
            reasons = [candidate.reason for candidate in candidates if candidate.reason]
            raise OperationDiscoveryError(
                reasons[0]
                if reasons
                else f"No supported semantic options are available for '{operation_id}.{parameter}'.",
                code="unsupported_options",
                operation_id=operation_id,
                parameter=parameter,
                context=dict(normalized_context),
                details={"option_count": len(candidates)},
            )
        if not include_unsupported:
            candidates = [candidate for candidate in candidates if candidate.supported]
        return [candidate.public().to_dict() for candidate in candidates]

    def describe_operation(
        self,
        operation_id: str,
        *,
        context: Mapping[str, Any] | None = None,
        include_unsupported: bool = False,
        method_owner: Any | None = None,
    ) -> dict[str, Any]:
        descriptor = self._descriptor(operation_id)
        normalized_context = self._validate_context(descriptor, context)
        result: dict[str, Any] = {
            # Public descriptions contain semantic operation metadata only.
            **descriptor.to_dict(),
            "profile": {
                "manufacturer": getattr(self.config, "manufacturer", None),
                "model": getattr(self.config, "model", None),
                "device_type": getattr(self.config, "device_type", None),
            },
        }
        operation = self._profile_operation(operation_id)
        if operation is not None:
            result.update(operation.discovery_metadata())

        parameter_names = list(self._parameter_names(descriptor))
        descriptions: dict[str, OperationParameterDescription | dict[str, Any]] = {}
        for parameter in parameter_names:
            data = self._parameter_data(descriptor, parameter, normalized_context)
            parameter_supported = (
                data.supported
                and data.reason is None
                and (
                    not data.candidates or any(candidate.supported for candidate in data.candidates)
                )
            )
            parameter_reason = data.reason
            if (
                parameter_reason is None
                and data.candidates
                and not any(candidate.supported for candidate in data.candidates)
            ):
                parameter_reason = next(
                    (candidate.reason for candidate in data.candidates if candidate.reason),
                    "No supported semantic options are available.",
                )
            description = OperationParameterDescription(
                name=parameter,
                kind=data.kind,
                required=data.required,
                default=data.default,
                unit=data.unit,
                dependencies=data.dependencies,
                constraints=data.constraints,
                options=tuple(
                    candidate.public()
                    for candidate in data.candidates
                    if include_unsupported or candidate.supported
                ),
                supported=parameter_supported,
                reason=parameter_reason,
            ).to_dict()
            descriptions[parameter] = description

        # Keep one canonical public serializer for Python and CLI consumers.
        # ``descriptions`` intentionally remains a compatibility-friendly dict
        # until the final conversion so descriptor extension fields survive.
        support = self.support_report(
            operation_id,
            check_parameters=False,
            context=normalized_context,
            method_owner=method_owner,
        )
        descriptor_projection = {
            key: value
            for key, value in result.items()
            if key not in {"operation_id", "method", "parameters", "profile", "support"}
        }
        result = OperationDescription(
            operation_id=descriptor.operation_id,
            method=descriptor.public_method or descriptor.operation_id,
            parameters=descriptions,
            profile=result["profile"],
            support=support,
        ).to_dict()
        result.update(descriptor_projection)
        if normalized_context:
            result["context"] = dict(normalized_context)
        return result

    def resolve_parameter(
        self,
        operation_id: str,
        parameter: str,
        value: Any,
        *,
        context: Mapping[str, Any] | None = None,
    ) -> ResolvedOperationParameter:
        descriptor = self._descriptor(operation_id)
        if parameter not in self._parameter_names(descriptor):
            raise OperationDiscoveryError(
                f"Parameter '{parameter}' is not declared for operation '{operation_id}'.",
                code="unknown_parameter",
                operation_id=operation_id,
                parameter=parameter,
            )
        normalized_context = self._validate_context(descriptor, context)
        # A parameter can depend on itself only through malformed metadata;
        # profile validation normally catches cycles, but keep runtime failure
        # explicit for hand-built configs.
        return self._resolve_parameter(descriptor, parameter, value, normalized_context, set())

    def resolve_transport_response(
        self,
        operation_id: str,
        parameter: str,
        transport_value: Any,
        *,
        context: Mapping[str, Any] | None = None,
    ) -> Any:
        """Map a private profile response back to its semantic public value."""

        descriptor = self._descriptor(operation_id)
        data = self._parameter_data(descriptor, parameter, dict(context or {}))
        for candidate in data.candidates:
            if candidate.supported and self._same_value(candidate.transport_value, transport_value):
                return candidate.value
        raise OperationDiscoveryError(
            f"Profile could not map the instrument response for '{operation_id}.{parameter}'.",
            code="unmapped_response",
            operation_id=operation_id,
            parameter=parameter,
        )

    def resolve_arguments(
        self,
        operation_id: str,
        arguments: Mapping[str, Any],
        *,
        context: Mapping[str, Any] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Validate all public arguments and return private alias arguments.

        The returned mapping is ``{transport_alias: {placeholder: value}}``.
        It is intended for drivers immediately before calling SCPIEngine; no
        caller needs to perform a second public resolver call.
        """

        descriptor = self._descriptor(operation_id)
        supplied = dict(arguments)
        unknown = [
            parameter
            for parameter in supplied
            if parameter not in self._parameter_names(descriptor)
        ]
        if unknown:
            raise OperationDiscoveryError(
                f"Unknown operation argument(s): {', '.join(sorted(unknown))}.",
                code="unknown_parameter",
                operation_id=operation_id,
                details={"unknown": sorted(unknown)},
            )
        supplied_context = dict(context or {})
        supplied_context.update(
            {key: value for key, value in supplied.items() if value is not None}
        )
        normalized_context = self._validate_context(descriptor, supplied_context)
        result: dict[str, dict[str, Any]] = {}
        for parameter, value in supplied.items():
            if value is None:
                continue
            resolved = self._resolve_parameter(
                descriptor, parameter, value, normalized_context, set()
            )
            if resolved.alias is None or resolved.transport_parameter is None:
                # A Python-only control parameter (uncertainty, for example)
                # has no SCPI binding and is already validated.
                continue
            result.setdefault(resolved.alias, {})[resolved.transport_parameter] = (
                resolved.transport_value
            )
        return result

    def support_report(
        self,
        operation_id: str,
        *,
        check_parameters: bool = False,
        context: Mapping[str, Any] | None = None,
        method_owner: Any | None = None,
    ) -> OperationSupportReport:
        descriptor = self._descriptor(operation_id)
        capability_enabled = self._capability_enabled(descriptor)
        if not capability_enabled:
            return OperationSupportReport(
                operation_id=operation_id,
                supported=False,
                capability_enabled=False,
                required=descriptor.required,
                reason=f"capability '{descriptor.capability}' is not enabled",
            )

        if self._profile_operation(descriptor.operation_id) is None:
            return OperationSupportReport(
                operation_id=operation_id,
                supported=False,
                capability_enabled=True,
                missing_required_aliases=("profile_operation",),
                required=descriptor.required,
                reason="profile does not implement this operation",
            )

        aliases = self._operation_aliases(descriptor)
        required_presence = self._scpi_engine.validate_presence(list(aliases))
        optional_presence: dict[str, bool] = {}
        missing_required = tuple(
            alias for alias, present in required_presence.items() if not present
        )
        missing_optional = tuple(
            alias for alias, present in optional_presence.items() if not present
        )
        missing_parameter_metadata: tuple[str, ...] = ()
        missing_capability_metadata: list[str] = []
        if check_parameters:
            missing_parameter_metadata = tuple(
                self._missing_parameter_metadata(descriptor, method_owner=method_owner)
            )
        support_context = dict(context or {})
        parameters: list[str] = list(self._parameter_names(descriptor))
        for parameter in parameters:
            data = self._parameter_data(descriptor, parameter, support_context)
            # Dependency-dependent metadata can only be assessed when all of
            # its dependency values are known.  With context, support reflects
            # the selected capability rather than only the operation shell.
            if data.dependencies and not all(
                dependency in support_context for dependency in data.dependencies
            ):
                continue
            if data.required and (
                not data.supported
                or data.kind == "unresolved"
                or data.reason
                or (data.candidates and not any(item.supported for item in data.candidates))
            ):
                missing_capability_metadata.append(parameter)

        supported = (
            not missing_required
            and not missing_parameter_metadata
            and not missing_capability_metadata
        )
        reason: str | None = None
        if missing_required:
            reason = "profile does not implement this operation"
        elif missing_parameter_metadata:
            reason = "missing parameter metadata"
        elif missing_capability_metadata:
            reason = "missing capability metadata"
        return OperationSupportReport(
            operation_id=operation_id,
            supported=supported,
            capability_enabled=True,
            missing_required_aliases=missing_required,
            missing_optional_aliases=missing_optional,
            missing_parameter_metadata=missing_parameter_metadata,
            missing_capability_metadata=tuple(sorted(set(missing_capability_metadata))),
            required=descriptor.required,
            reason=reason,
        )

    # ------------------------------------------------------------------
    # Parameter metadata and profile adaptation
    # ------------------------------------------------------------------
    def _parameter_data(
        self,
        descriptor: OperationDescriptor,
        parameter: str,
        context: Mapping[str, Any],
    ) -> _ParameterData:
        profile_spec = self._generic_profile_spec(descriptor.operation_id, parameter)
        if profile_spec is None:
            data = _ParameterData(
                kind="unresolved",
                reason=f"Profile metadata omits '{descriptor.operation_id}.{parameter}'.",
                metadata_present=False,
            )
        elif profile_spec.source and profile_spec.source.startswith("measurement_functions"):
            raw = profile_spec.model_dump(mode="python", exclude_none=True)
            data = self._from_measurement_source(
                descriptor, parameter, profile_spec.source, context, raw
            )
        else:
            data = self._from_profile_spec(
                profile_spec,
                source=profile_spec.source,
                operation_id=descriptor.operation_id,
                parameter=parameter,
            )
        if profile_spec is not None:
            data.required = profile_spec.required
            if data.default is None:
                data.default = profile_spec.default
            if data.description is None:
                data.description = profile_spec.description
            if data.unit is None:
                data.unit = profile_spec.unit
        # Dependent semantic parameters may inherit constraints from the
        # selected option.  Profiles use this for mode-specific limits without
        # hardcoding device modes in the driver, e.g. mode option
        # ``constraints: {value: {min: 0, max: 40, unit: A}}``.
        for dependency in data.dependencies:
            selected = context.get(dependency, _MISSING)
            if selected is _MISSING:
                continue
            dependency_data = self._parameter_data(descriptor, dependency, context)
            dependency_option = self._find_candidate(dependency_data.candidates, selected)
            if dependency_option is None:
                continue
            inherited = dependency_option.constraints.get(parameter)
            if not isinstance(inherited, Mapping):
                continue
            for key in ("min", "max", "pattern"):
                if key in inherited:
                    data.constraints.setdefault(key, inherited[key])
            if data.unit is None and inherited.get("unit") is not None:
                data.unit = str(inherited["unit"])
        contextual_ranges = data.constraints.get("contextual_ranges", ())
        for contextual_range in contextual_ranges:
            when = contextual_range.get("when", {})
            if all(
                self._matches_context_condition(key, expected, context)
                for key, expected in when.items()
            ):
                for key in ("min", "max", "unit"):
                    if key in contextual_range:
                        data.constraints[key] = contextual_range[key]
                break
        multiplier_parameter = data.constraints.get("multiplier_parameter")
        if multiplier_parameter and multiplier_parameter in context:
            try:
                multiplier = float(context[multiplier_parameter])
            except (TypeError, ValueError) as exc:
                raise InstrumentParameterError(
                    parameter=multiplier_parameter,
                    value=context[multiplier_parameter],
                    message="Range multiplier must be a positive finite number.",
                ) from exc
            if not math.isfinite(multiplier) or multiplier <= 0:
                raise InstrumentParameterError(
                    parameter=multiplier_parameter,
                    value=context[multiplier_parameter],
                    message="Range multiplier must be a positive finite number.",
                )
            for key in ("min", "max"):
                if data.constraints.get(key) is not None:
                    limit = float(data.constraints[key]) * multiplier
                    if not math.isfinite(limit):
                        raise InstrumentParameterError(
                            parameter=multiplier_parameter,
                            value=context[multiplier_parameter],
                            message="Probe attenuation produces a non-finite scale limit.",
                        )
                    data.constraints[key] = limit
        if not self._capability_enabled(descriptor):
            data.supported = False
            data.reason = f"capability '{descriptor.capability}' is not enabled"
        missing_aliases = [
            alias
            for alias, present in self._scpi_engine.validate_presence(
                list(self._operation_aliases(descriptor))
            ).items()
            if not present
        ]
        if missing_aliases:
            data.supported = False
            data.reason = f"profile does not implement operation '{descriptor.operation_id}'"
        self._apply_binding_support(descriptor, parameter, data)
        if not data.supported:
            for candidate in data.candidates:
                candidate.supported = False
                candidate.reason = (
                    candidate.reason or data.reason or "parameter is disabled in the profile"
                )
        return data

    def _apply_binding_support(
        self, descriptor: OperationDescriptor, parameter: str, data: _ParameterData
    ) -> None:
        """Disable semantic options whose declared transport binding is absent."""

        bindings = data.bindings or tuple(self._bindings(descriptor, parameter))
        if not bindings or not data.supported:
            return

        def binding_error(candidate_bindings: tuple[tuple[str, str], ...]) -> str | None:
            available = self._scpi_engine.validate_presence(
                [alias for alias, _ in candidate_bindings]
            )
            for alias, alias_parameter in candidate_bindings:
                if not available.get(alias, False):
                    return f"profile does not implement operation '{descriptor.operation_id}'"
                try:
                    placeholders = self._scpi_engine.validate_placeholders(alias)["placeholders"]
                except KeyError:
                    return f"profile does not implement operation '{descriptor.operation_id}'"
                if alias_parameter not in placeholders:
                    return "profile option transport mapping is incomplete"
            return None

        if data.source != "measurement_functions":
            error = binding_error(bindings)
            if error is not None:
                data.supported = False
                data.reason = error
                for candidate in data.candidates:
                    candidate.supported = False
                    candidate.reason = error
            return

        for candidate in data.candidates:
            if not candidate.supported:
                continue
            spec = self._function_spec(self.config.measurement_functions, candidate.value)
            error = binding_error(((self._function_measure_alias(spec), "function"),))
            if error is not None:
                candidate.supported = False
                candidate.reason = error

    def _matches_context_condition(
        self, parameter: str, expected: Any, context: Mapping[str, Any]
    ) -> bool:
        if parameter not in context:
            return False
        value = context[parameter]
        if not isinstance(expected, Mapping):
            return self._same_value(value, expected)
        multiplier_parameter = expected.get("multiplier_parameter")
        if multiplier_parameter is not None and multiplier_parameter not in context:
            return False
        try:
            numeric = float(value)
            multiplier = float(context[multiplier_parameter]) if multiplier_parameter else 1.0
        except (TypeError, ValueError) as exc:
            raise InstrumentParameterError(
                parameter=parameter,
                value=value,
                message="Contextual range requires numeric context.",
            ) from exc
        if not math.isfinite(numeric) or not math.isfinite(multiplier) or multiplier <= 0:
            raise InstrumentParameterError(
                parameter=parameter,
                value=value,
                message="Contextual range requires finite context and a positive finite multiplier.",
            )
        for bound in ("min", "max", "exclusive_min", "exclusive_max"):
            if bound not in expected:
                continue
            limit = float(expected[bound]) * multiplier
            if not math.isfinite(limit):
                raise InstrumentParameterError(
                    parameter=parameter, value=value, message="Contextual band limit is not finite."
                )
            if bound == "min" and numeric < limit:
                return False
            if bound == "max" and numeric > limit:
                return False
            if bound == "exclusive_min" and numeric <= limit:
                return False
            if bound == "exclusive_max" and numeric >= limit:
                return False
        return True

    def _from_profile_spec(
        self,
        spec: ProfileOperationParameter,
        *,
        source: str | None,
        operation_id: str | None = None,
        parameter: str | None = None,
    ) -> _ParameterData:
        candidates: list[_Candidate] = []
        for option in spec.options:
            transport_spec = getattr(option, "transport", None)
            transport = self._transport_value(transport_spec)
            supported = bool(option.supported)
            reason = option.reason
            if transport is _MISSING and not spec.transport_parameter:
                transport = option.value
            elif transport is _MISSING and spec.transport_identity:
                transport = option.value
            if transport is _MISSING and spec.transport_parameter:
                supported = False
                reason = reason or "profile option has no transport mapping"
            candidates.append(
                _Candidate(
                    value=option.value,
                    label=option.label or str(option.value),
                    aliases=tuple(dict.fromkeys(str(a) for a in option.aliases if a)),
                    description=option.description,
                    unit=option.unit or spec.unit,
                    supported=supported,
                    reason=reason,
                    constraints=self._json_value(dict(option.constraints)),
                    transport_value=transport,
                    source=source,
                )
            )
        return _ParameterData(
            kind=spec.kind,
            required=spec.required,
            default=spec.default,
            unit=spec.unit,
            description=spec.description,
            dependencies=tuple(spec.dependencies),
            constraints={
                **spec.constraints,
                **{
                    key: value
                    for key, value in (
                        ("min", spec.min),
                        ("max", spec.max),
                        ("positive", spec.positive),
                        ("multiplier_parameter", spec.multiplier_parameter),
                        ("contextual_ranges", spec.contextual_ranges),
                        ("integer", spec.integer),
                    )
                    if value is not None and value is not False and value != []
                },
            },
            candidates=candidates,
            supported=spec.supported,
            reason=spec.reason,
            source=source,
            metadata_present=True,
            bindings=tuple(
                self._profile_bindings(operation_id, parameter)
                if operation_id is not None and parameter is not None
                else ()
            ),
        )

    def _from_measurement_source(
        self,
        descriptor: OperationDescriptor,
        parameter: str,
        source: str,
        context: Mapping[str, Any],
        raw: Mapping[str, Any],
    ) -> _ParameterData:
        functions = self._get_path(self.config, "measurement_functions")
        dependencies = tuple(str(item) for item in raw.get("dependencies", []) or [])
        if parameter == "function" or source == "measurement_functions":
            candidates: list[_Candidate] = []
            for function_id, spec in self._function_specs(functions):
                normalized_id = self._normalize_id(function_id)
                token = self._function_transport(spec)
                try:
                    measure_alias = self._function_measure_alias(spec)
                except ValueError:
                    measure_alias = ""
                alias_presence = (
                    self._scpi_engine.validate_presence([measure_alias]) if measure_alias else {}
                )
                aliases = tuple(
                    dict.fromkeys(
                        str(alias)
                        for alias in (getattr(spec, "aliases", None) or [])
                        if self._normalize_id(alias) != normalized_id
                    )
                )
                supported = (
                    token is not _MISSING
                    and bool(str(token).strip())
                    and bool(alias_presence.get(measure_alias, False))
                )
                candidates.append(
                    _Candidate(
                        value=normalized_id,
                        label=getattr(spec, "label", None)
                        or normalized_id.replace("_", " ").title(),
                        aliases=aliases,
                        description=getattr(spec, "description", None),
                        unit=getattr(spec, "unit", None),
                        supported=supported,
                        reason=None
                        if supported
                        else (
                            "profile function has no transport mapping"
                            if token is _MISSING or not bool(str(token).strip())
                            else f"profile function transport alias '{measure_alias}' is missing"
                        ),
                        transport_value=token,
                        source=f"measurement_functions.{normalized_id}",
                    )
                )
            if not candidates:
                return _ParameterData(
                    kind="enum",
                    dependencies=dependencies,
                    reason="Profile declares no measurement_functions options.",
                    source="measurement_functions",
                    metadata_present=False,
                )
            return _ParameterData(
                kind="enum",
                required=bool(raw.get("required", True)),
                description=raw.get("description"),
                dependencies=dependencies,
                candidates=candidates,
                source="measurement_functions",
                metadata_present=True,
            )

        if not dependencies:
            dependencies = ("function",)
        function_value = context.get("function", _MISSING)
        if function_value is _MISSING:
            return _ParameterData(
                kind="enum",
                dependencies=dependencies,
                description=raw.get("description"),
                reason=(
                    f"Parameter '{parameter}' requires dependency context: "
                    f"{', '.join(dependencies)}."
                ),
                source=f"measurement_functions.{parameter}",
                metadata_present=True,
            )
        try:
            function_result = self._resolve_parameter(
                descriptor, "function", function_value, context, set()
            )
        except OperationDiscoveryError as exc:
            return _ParameterData(
                kind="enum",
                dependencies=dependencies,
                reason=f"Cannot resolve dependency 'function': {exc}",
                source=f"measurement_functions.{parameter}",
                metadata_present=True,
            )
        function_id = self._normalize_id(function_result.value)
        spec = self._function_spec(functions, function_id)
        if spec is None:
            return _ParameterData(
                kind="enum",
                dependencies=dependencies,
                reason=f"Profile has no measurement function '{function_id}'.",
                source=f"measurement_functions.{parameter}",
                metadata_present=True,
            )

        if parameter == "range_val" or source.endswith(".ranges"):
            data = self._range_data(spec, function_id, dependencies)
            data.bindings = ((self._function_measure_alias(spec), "range"),)
            return data
        if parameter == "resolution" or source.endswith(".resolution"):
            data = self._resolution_data(spec, function_id, dependencies)
            data.bindings = ((self._function_measure_alias(spec), "resolution"),)
            return data
        nested = getattr(spec, parameter, _MISSING)
        if nested is _MISSING:
            return _ParameterData(
                kind="unresolved",
                dependencies=dependencies,
                reason=(
                    f"Measurement function '{function_id}' does not declare "
                    f"metadata for '{parameter}'."
                ),
                source=f"measurement_functions.{function_id}.{parameter}",
                metadata_present=False,
            )
        data = self._data_from_generic_value(
            nested, f"measurement_functions.{function_id}.{parameter}", raw
        )
        data.dependencies = dependencies
        return data

    def _range_data(
        self, spec: Any, function_id: str, dependencies: tuple[str, ...]
    ) -> _ParameterData:
        if (
            "range"
            not in self._scpi_engine.validate_placeholders(self._function_measure_alias(spec))[
                "placeholders"
            ]
        ):
            return _ParameterData(
                kind="enum",
                dependencies=dependencies,
                candidates=[],
                source=f"measurement_functions.{function_id}.ranges",
                metadata_present=True,
                supported=False,
                reason=f"Measurement function '{function_id}' query does not accept range settings.",
            )
        ranges = list(getattr(spec, "ranges", None) or [])
        candidates: list[_Candidate] = [
            _Candidate(
                value="AUTO",
                label="Automatic range",
                aliases=("auto",),
                unit=getattr(spec, "unit", None),
                source=f"measurement_functions.{function_id}.ranges",
                transport_value="AUTO",
            )
        ]
        for range_spec in ranges:
            value = self._range_nominal_value(range_spec)
            if value is _MISSING:
                continue
            public_range = self._json_value(value)
            constraints = self._json_value(
                range_spec.model_dump(mode="json", exclude_none=True)
                if hasattr(range_spec, "model_dump")
                else dict(range_spec)
            )
            candidates.append(
                _Candidate(
                    value=public_range,
                    label=str(public_range),
                    unit=getattr(range_spec, "units", None) or getattr(spec, "unit", None),
                    constraints=constraints if isinstance(constraints, dict) else {},
                    source=f"measurement_functions.{function_id}.ranges",
                    transport_value=public_range,
                )
            )
        if ranges:
            return _ParameterData(
                kind="enum",
                dependencies=dependencies,
                unit=getattr(spec, "unit", None),
                candidates=self._dedupe_candidates(candidates),
                source=f"measurement_functions.{function_id}.ranges",
                metadata_present=True,
                reason=None,
            )

        # Some profiles declare a continuous function-specific range (for
        # example ``range_Hz: {min, max}``) rather than discrete range rows.
        # Keep AUTO executable but describe the numeric constraint instead of
        # fabricating a finite list.
        dumped = spec.model_dump(exclude_none=True) if hasattr(spec, "model_dump") else {}
        range_constraints: dict[str, Any] = {}
        for key, value in dumped.items():
            if not str(key).lower().startswith("range") or not isinstance(value, Mapping):
                continue
            minimum = value.get("min", value.get("min_val"))
            maximum = value.get("max", value.get("max_val"))
            if minimum is not None:
                range_constraints["min"] = minimum
            if maximum is not None:
                range_constraints["max"] = maximum
            if range_constraints:
                break
        return _ParameterData(
            kind="range" if range_constraints else "enum",
            dependencies=dependencies,
            unit=getattr(spec, "unit", None),
            candidates=candidates,
            constraints=range_constraints,
            source=f"measurement_functions.{function_id}.ranges",
            metadata_present=True,
        )

    def _resolution_data(
        self, spec: Any, function_id: str, dependencies: tuple[str, ...]
    ) -> _ParameterData:
        if (
            "resolution"
            not in self._scpi_engine.validate_placeholders(self._function_measure_alias(spec))[
                "placeholders"
            ]
        ):
            return _ParameterData(
                kind="enum",
                dependencies=dependencies,
                candidates=[],
                source=f"measurement_functions.{function_id}.resolution",
                metadata_present=True,
                supported=False,
                reason=f"Measurement function '{function_id}' query does not accept resolution settings.",
            )
        raw_resolution = getattr(spec, "resolution", _MISSING)
        if raw_resolution is _MISSING or raw_resolution is None:
            # DEF is the only safe semantic value when no finite table exists;
            # do not interpret absent metadata as unrestricted text.
            return _ParameterData(
                kind="enum",
                default="DEF",
                dependencies=dependencies,
                candidates=[
                    _Candidate(
                        value="DEF",
                        label="Instrument default",
                        aliases=("default",),
                        transport_value="DEF",
                        source=f"measurement_functions.{function_id}.resolution",
                    )
                ],
                source=f"measurement_functions.{function_id}.resolution",
                metadata_present=True,
            )
        if isinstance(raw_resolution, (list, tuple)) and all(
            not isinstance(item, Mapping) for item in raw_resolution
        ):
            candidates = [
                _Candidate(
                    value="DEF",
                    label="Instrument default",
                    aliases=("default",),
                    transport_value="DEF",
                    source=f"measurement_functions.{function_id}.resolution",
                )
            ]
            candidates.extend(
                _Candidate(
                    value=self._json_value(item),
                    label=str(self._json_value(item)),
                    transport_value=self._json_value(item),
                    source=f"measurement_functions.{function_id}.resolution",
                )
                for item in raw_resolution
            )
            return _ParameterData(
                kind="enum",
                default="DEF",
                dependencies=dependencies,
                candidates=self._dedupe_candidates(candidates),
                source=f"measurement_functions.{function_id}.resolution",
                metadata_present=True,
            )
        # Span-dependent records are constraints rather than selectable values;
        # DEF remains the only safe finite choice.
        return _ParameterData(
            kind="enum",
            default="DEF",
            dependencies=dependencies,
            candidates=[
                _Candidate(
                    value="DEF",
                    label="Instrument default",
                    aliases=("default",),
                    transport_value="DEF",
                    source=f"measurement_functions.{function_id}.resolution",
                )
            ],
            description=(
                f"Measurement function '{function_id}' has span-dependent resolution metadata; "
                "only the instrument default is selectable."
            ),
            source=f"measurement_functions.{function_id}.resolution",
            metadata_present=True,
        )

    def _data_from_generic_value(
        self, value: Any, source: str, raw: Mapping[str, Any]
    ) -> _ParameterData:
        if isinstance(value, ProfileOperationParameter):
            return self._from_profile_spec(value, source=source)
        if hasattr(value, "model_dump") and not isinstance(value, (str, bytes)):
            dumped = value.model_dump(exclude_none=True)
            # A single mapping containing option-like fields is not an enum;
            # preserve it as metadata unless it clearly contains choices.
            value = dumped
        if isinstance(value, Mapping):
            if "options" in value:
                try:
                    spec = ProfileOperationParameter.model_validate(value)
                    return self._from_profile_spec(spec, source=source)
                except (TypeError, ValueError) as exc:
                    raise InstrumentConfigurationError(
                        getattr(self.config, "model", None),
                        f"Invalid profile option metadata at '{source}': {exc}",
                    ) from exc
            candidates: list[_Candidate] = []
            for key, transport in value.items():
                if isinstance(transport, Mapping):
                    semantic = transport.get("value", transport.get("id", key))
                    label = transport.get("label", str(semantic))
                    option_transport = transport.get(
                        "transport", transport.get("token", transport.get("scpi", _MISSING))
                    )
                    aliases = tuple(str(a) for a in transport.get("aliases", []) or [])
                    description = transport.get("description")
                else:
                    semantic = key
                    label = str(key)
                    option_transport = transport
                    aliases = ()
                    description = None
                candidates.append(
                    _Candidate(
                        value=self._json_value(semantic),
                        label=str(label),
                        aliases=aliases,
                        description=description,
                        transport_value=option_transport,
                        source=source,
                    )
                )
            return _ParameterData(
                kind="enum",
                candidates=self._dedupe_candidates(candidates),
                source=source,
                metadata_present=True,
            )
        if isinstance(value, (list, tuple, set)):
            candidates = [
                _Candidate(
                    value=self._json_value(item),
                    label=str(self._json_value(item)),
                    transport_value=_MISSING,
                    source=source,
                )
                for item in value
            ]
            return _ParameterData(
                kind="enum",
                candidates=self._dedupe_candidates(candidates),
                source=source,
                metadata_present=True,
            )
        if isinstance(value, numbers.Real) and not isinstance(value, bool):
            return _ParameterData(
                kind="range",
                constraints={"value": self._json_value(value)},
                source=source,
                metadata_present=True,
            )
        if isinstance(value, bool):
            return _ParameterData(
                kind="bool",
                candidates=[
                    _Candidate(True, "True", transport_value=True, source=source),
                    _Candidate(False, "False", transport_value=False, source=source),
                ],
                source=source,
                metadata_present=True,
            )
        return _ParameterData(
            kind="open_string",
            source=source,
            metadata_present=True,
            reason="Profile metadata does not declare finite choices or constraints.",
        )

    # ------------------------------------------------------------------
    # Resolution helpers
    # ------------------------------------------------------------------
    def _resolve_parameter(
        self,
        descriptor: OperationDescriptor,
        parameter: str,
        value: Any,
        context: Mapping[str, Any],
        resolving: set[str],
    ) -> ResolvedOperationParameter:
        missing_aliases = [
            alias
            for alias, present in self._scpi_engine.validate_presence(
                list(self._operation_aliases(descriptor))
            ).items()
            if not present
        ]
        if missing_aliases:
            raise InstrumentConfigurationError(
                getattr(self.config, "model", None),
                "Profile does not implement the requested operation.",
            )
        if parameter in resolving:
            raise OperationDiscoveryError(
                f"Dependency cycle while resolving '{descriptor.operation_id}.{parameter}'.",
                code="dependency_cycle",
                operation_id=descriptor.operation_id,
                parameter=parameter,
            )
        resolving.add(parameter)
        data = self._parameter_data(descriptor, parameter, context)
        if not data.supported:
            raise InstrumentParameterError(
                parameter=parameter,
                value=value,
                message=data.reason or f"Parameter '{parameter}' is unsupported.",
            )
        for dependency in data.dependencies:
            if dependency not in context:
                raise OperationDiscoveryError(
                    f"Parameter '{parameter}' requires context parameter '{dependency}'.",
                    code="missing_dependency",
                    operation_id=descriptor.operation_id,
                    parameter=parameter,
                    context=dict(context),
                    details={"required_parameters": list(data.dependencies)},
                )
            self._resolve_parameter(descriptor, dependency, context[dependency], context, resolving)

        candidate = self._find_candidate(data.candidates, value)
        if candidate is not None:
            if not candidate.supported or candidate.transport_value is _MISSING:
                raise InstrumentParameterError(
                    parameter=parameter,
                    value=value,
                    message=candidate.reason or "Profile option has no transport mapping.",
                )
            if data.source == "measurement_functions":
                spec = self._function_spec(self.config.measurement_functions, candidate.value)
                measure_alias = self._function_measure_alias(spec)
                if not self._scpi_engine.validate_presence([measure_alias])[measure_alias]:
                    raise InstrumentConfigurationError(
                        getattr(self.config, "model", None),
                        "Profile does not implement the selected measurement function.",
                    )
            canonical = candidate.value
            transport = candidate.transport_value
            if isinstance(value, str) and isinstance(candidate.value, numbers.Real):
                # Preserve an explicitly supplied textual numeric spelling for
                # SCPI formatting while retaining the profile's numeric
                # canonical value for context and plan validation.
                transport = value
        elif data.kind in {"enum", "bool"}:
            valid = [item.value for item in data.candidates if item.supported]
            raise InstrumentParameterError(
                parameter=parameter,
                value=value,
                valid_range=tuple(valid),
                message=(
                    f"Unsupported semantic option for profile '{getattr(self.config, 'model', '')}'. "
                    f"Choose one of: {', '.join(map(str, valid)) or 'none declared'}."
                ),
            )
        elif data.kind == "range":
            range_value = getattr(value, "value", value)
            special_values = {
                str(item).strip().casefold(): item
                for item in data.constraints.get("special_values", [])
            }
            if isinstance(range_value, str) and range_value.strip().casefold() in special_values:
                canonical = special_values[range_value.strip().casefold()]
                transport = canonical
            else:
                # Profiles may intentionally leave a numeric input
                # unconstrained when no reliable vendor limit is known.
                # Numeric inputs are still required to be finite.
                canonical = self._validate_numeric(parameter, range_value, data.constraints)
                transport = canonical
        elif data.kind == "open_string":
            canonical = self._validate_open(parameter, value, data.constraints, data.reason)
            transport = canonical
        elif data.kind == "unresolved":
            raise OperationDiscoveryError(
                data.reason
                or f"No semantic metadata is declared for '{descriptor.operation_id}.{parameter}'.",
                code="metadata_unresolved",
                operation_id=descriptor.operation_id,
                parameter=parameter,
            )
        else:
            canonical = value
            transport = value

        bindings = data.bindings or tuple(self._bindings(descriptor, parameter))
        alias: str | None = None
        alias_parameter: str | None = None
        if bindings:
            alias, alias_parameter = bindings[0]
        profile_spec = self._generic_profile_spec(descriptor.operation_id, parameter)
        if (
            profile_spec is not None
            and profile_spec.transport_parameter
            and not bindings
            and not (data.source or "").startswith("measurement_functions")
        ):
            raise InstrumentConfigurationError(
                getattr(self.config, "model", None),
                f"Profile operation parameter '{descriptor.operation_id}.{parameter}' "
                "has no private transport binding.",
            )
        if data.source == "measurement_functions":
            spec = self._function_spec(self.config.measurement_functions, canonical)
            alias, alias_parameter = self._function_measure_alias(spec), "function"
        resolving.remove(parameter)
        return ResolvedOperationParameter(
            value=canonical,
            transport_value=transport,
            option=candidate.public() if candidate is not None else None,
            alias=alias,
            transport_parameter=alias_parameter,
        )

    def _validate_numeric(self, parameter: str, value: Any, constraints: Mapping[str, Any]) -> Any:
        if isinstance(value, bool) or not isinstance(value, numbers.Real):
            # Numeric strings are useful for drivers whose public API accepts
            # SCPI-compatible values, but only when they parse unambiguously.
            try:
                parsed = float(value)
            except (TypeError, ValueError) as exc:
                raise InstrumentParameterError(
                    parameter=parameter, value=value, message="Expected a numeric value."
                ) from exc
            value = parsed
        numeric = float(value)
        if not math.isfinite(numeric):
            raise InstrumentParameterError(
                parameter=parameter,
                value=value,
                message="Value must be finite.",
            )
        if constraints.get("positive") and numeric <= 0:
            raise InstrumentParameterError(
                parameter=parameter,
                value=value,
                message="Value must be positive.",
            )
        if constraints.get("integer"):
            if not numeric.is_integer():
                raise InstrumentParameterError(
                    parameter=parameter,
                    value=value,
                    message="Value must be an integer.",
                )
            value = int(numeric)
            numeric = float(value)
        if constraints.get("value") is not None and not math.isclose(
            numeric, float(constraints["value"]), rel_tol=0.0, abs_tol=1e-12
        ):
            raise InstrumentParameterError(
                parameter=parameter,
                value=value,
                valid_range=(constraints["value"], constraints["value"]),
                message="Value does not match the profile-declared value.",
            )
        minimum = constraints.get("min")
        maximum = constraints.get("max")
        if (
            minimum is not None
            and numeric < float(minimum)
            or maximum is not None
            and numeric > float(maximum)
        ):
            raise InstrumentParameterError(
                parameter=parameter,
                value=value,
                valid_range=(minimum, maximum),
                message="Value is outside the profile-declared range; it must be between the declared limits.",
            )
        return value

    def _validate_open(
        self, parameter: str, value: Any, constraints: Mapping[str, Any], reason: str | None
    ) -> Any:
        if not isinstance(value, (str, numbers.Real, bool)):
            raise InstrumentParameterError(
                parameter=parameter, value=value, message="Expected a scalar value."
            )
        if (
            isinstance(value, numbers.Real)
            and not isinstance(value, bool)
            and not math.isfinite(value)
        ):
            raise InstrumentParameterError(
                parameter=parameter, value=value, message="Value must be finite."
            )
        pattern = constraints.get("pattern")
        if pattern and not re.match(str(pattern), str(value)):
            raise InstrumentParameterError(
                parameter=parameter,
                value=value,
                message=f"Value does not match profile pattern {pattern!r}.",
            )
        if reason and not constraints:
            if parameter == "resolution" and str(value).strip().casefold() in {
                "def",
                "default",
            }:
                return "DEF"
            raise OperationDiscoveryError(reason, code="metadata_unresolved", parameter=parameter)
        return value

    # ------------------------------------------------------------------
    # Context, bindings, and profile utility methods
    # ------------------------------------------------------------------
    def _validate_context(
        self, descriptor: OperationDescriptor, context: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        if context is None:
            return {}
        if not isinstance(context, Mapping):
            raise OperationDiscoveryError(
                "Operation context must be a JSON/object mapping.",
                code="invalid_context",
                operation_id=descriptor.operation_id,
            )
        allowed = set(self._parameter_names(descriptor))
        method_name = descriptor.public_method or descriptor.operation_id
        # Context may contain parameters declared by a method but omitted from a
        # compact descriptor.  It is still safer to reject arbitrary keys.
        unknown = sorted(set(context) - allowed)
        if unknown:
            raise OperationDiscoveryError(
                f"Unknown context parameter(s): {', '.join(unknown)}.",
                code="unknown_context",
                operation_id=descriptor.operation_id,
                details={"unknown": unknown, "allowed": sorted(allowed), "method": method_name},
            )
        normalized: dict[str, Any] = {}
        for parameter, value in context.items():
            # Validate supplied context now, including aliases, so discovery
            # and execution cannot disagree about dependent selections.
            resolved = self._resolve_parameter(descriptor, parameter, value, context, set())
            normalized[parameter] = resolved.value
        return normalized

    def _parameter_names(self, descriptor: OperationDescriptor) -> tuple[str, ...]:
        """Return parameters declared by profile metadata for this operation."""

        operation = self._profile_operation(descriptor.operation_id)
        names: list[str] = []
        if operation is not None:
            names.extend(name for name in operation.parameters if name not in names)
        return tuple(names)

    def _bindings(self, descriptor: OperationDescriptor, parameter: str) -> list[tuple[str, str]]:
        profile_bindings = self._profile_bindings(descriptor.operation_id, parameter)
        if profile_bindings:
            return profile_bindings
        return []

    def _operation_aliases(self, descriptor: OperationDescriptor) -> tuple[str, ...]:
        """Resolve private operation-local names to SCPI-engine aliases."""

        operation = self._profile_operation(descriptor.operation_id)
        if operation is None:
            return ()
        aliases = (*operation.transport.values(), *operation.context_queries.values())
        return tuple(dict.fromkeys(str(alias) for alias in aliases if alias))

    def _profile_bindings(self, operation_id: str, parameter: str) -> list[tuple[str, str]]:
        """Return bindings owned by profile option metadata, when declared."""
        operation = self._profile_operation(operation_id)
        spec = operation.parameters.get(parameter) if operation else None
        if spec is None:
            return []
        bindings: list[tuple[str, str]] = []
        for binding in getattr(spec, "bindings", ()):
            alias = (
                operation.transport.get(binding.alias, binding.alias)
                if operation
                else binding.alias
            )
            bindings.append((str(alias), str(binding.parameter)))
        return list(dict.fromkeys(bindings))

    def _profile_operation(self, operation_id: str) -> Any | None:
        options = getattr(self.config, "operation_options", None)
        if options is None:
            return None
        operation = options.operation(operation_id) if hasattr(options, "operation") else None
        return operation

    def _generic_profile_spec(
        self, operation_id: str, parameter: str
    ) -> ProfileOperationParameter | None:
        options = getattr(self.config, "operation_options", None)
        if options is None:
            return None
        if hasattr(options, "parameter"):
            return options.parameter(operation_id, parameter)
        if isinstance(options, Mapping):
            raw_operation = options.get(operation_id, {})
            if isinstance(raw_operation, Mapping):
                raw_operation = raw_operation.get("parameters", raw_operation)
                raw = raw_operation.get(parameter)
                if raw is not None:
                    try:
                        return ProfileOperationParameter.model_validate(raw)
                    except (TypeError, ValueError) as exc:
                        raise InstrumentConfigurationError(
                            message=(
                                f"Invalid operation_options metadata for "
                                f"'{operation_id}.{parameter}': {exc}"
                            )
                        ) from exc
        return None

    def _capability_enabled(self, descriptor: OperationDescriptor) -> bool:
        if descriptor.capability is None:
            return True
        value = self._get_path(self.config, descriptor.capability)
        return bool(value) if value is not _MISSING else False

    def _descriptor(self, operation_id: str) -> OperationDescriptor:
        for descriptor in self.descriptors:
            if descriptor.operation_id == operation_id:
                return descriptor
        raise OperationDiscoveryError(
            f"Operation '{operation_id}' is not declared by the driver.",
            code="unknown_operation",
            operation_id=operation_id,
        )

    def _missing_parameter_metadata(
        self, descriptor: OperationDescriptor, *, method_owner: Any | None = None
    ) -> list[str]:
        # Retain the strict SCPI contract check implemented historically by
        # Instrument without importing the driver back into this module.  This
        # method checks only explicitly declared operation parameters.
        missing: list[str] = []
        for parameter in self._parameter_names(descriptor):
            data = self._parameter_data(descriptor, parameter, {})
            if data.required and (
                data.kind == "unresolved" or data.reason and not data.dependencies
            ):
                missing.append(parameter)
        return sorted(set(missing))

    def _function_specs(self, functions: Any) -> list[tuple[str, Any]]:
        if functions is None:
            return []
        method = getattr(functions, "function_specs", None)
        if callable(method):
            return list(method())
        if isinstance(functions, Mapping):
            result = []
            for key, value in functions.items():
                if key == "required_scpi_commands":
                    continue
                result.append((str(key), value))
            return result
        return []

    def _function_spec(self, functions: Any, function_id: str) -> Any | None:
        wanted = self._normalize_id(function_id)
        for declared_id, spec in self._function_specs(functions):
            if self._normalize_id(declared_id) == wanted:
                return spec
        return None

    @staticmethod
    def _function_measure_alias(spec: Any) -> str:
        transport = getattr(spec, "transport", None)
        if isinstance(transport, Mapping):
            alias = transport.get("measure_alias")
        else:
            alias = getattr(transport, "measure_alias", None)
        if not alias:
            raise ValueError("measurement function has no profile query alias")
        return str(alias)

    def _function_transport(self, spec: Any) -> Any:
        transport = getattr(spec, "transport", _MISSING)
        return self._transport_value(
            transport, preferred=("function_token", "value", "token", "scpi")
        )

    @staticmethod
    def _range_nominal_value(range_spec: Any) -> Any:
        fields = ("nominal_V", "nominal_A", "nominal_ohm", "nominal_F", "nominal", "max")
        for field_name in fields:
            value = getattr(range_spec, field_name, _MISSING)
            if value is not _MISSING and value is not None:
                return value
        value = getattr(range_spec, "max_val", _MISSING)
        return value

    @staticmethod
    def _transport_value(
        transport: Any,
        *,
        preferred: tuple[str, ...] = ("value", "token", "function_token", "scpi"),
    ) -> Any:
        if transport is None:
            return _MISSING
        if isinstance(transport, Mapping):
            for key in preferred:
                if transport.get(key) is not None:
                    return transport[key]
            return _MISSING
        for key in preferred:
            value = getattr(transport, key, _MISSING)
            if value is not _MISSING and value is not None:
                return value
        return _MISSING

    @staticmethod
    def _same_value(left: Any, right: Any) -> bool:
        if left is _MISSING or right is _MISSING:
            return False
        left = getattr(left, "value", left)
        right = getattr(right, "value", right)
        if isinstance(left, numbers.Real) and isinstance(right, numbers.Real):
            return math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=1e-12)
        if isinstance(left, numbers.Real) and isinstance(right, str):
            try:
                return math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=1e-12)
            except ValueError:
                pass
        if isinstance(right, numbers.Real) and isinstance(left, str):
            try:
                return math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=1e-12)
            except ValueError:
                pass
        return str(left).strip().casefold() == str(right).strip().casefold()

    def _find_candidate(self, candidates: list[_Candidate], value: Any) -> _Candidate | None:
        for candidate in candidates:
            if self._same_value(candidate.value, value):
                return candidate
            if any(
                self._same_value(alias, value) for alias in [candidate.label, *candidate.aliases]
            ):
                return candidate
            if isinstance(value, str):
                normalized = self._normalize_id(value)
                if any(
                    normalized == self._normalize_id(str(alias))
                    for alias in [candidate.label, *candidate.aliases]
                ):
                    return candidate
        return None

    @staticmethod
    def _dedupe_candidates(candidates: list[_Candidate]) -> list[_Candidate]:
        result: list[_Candidate] = []
        for candidate in candidates:
            existing = next(
                (
                    item
                    for item in result
                    if OperationResolver._same_value(item.value, candidate.value)
                ),
                None,
            )
            if existing is None:
                result.append(candidate)
                continue
            existing.aliases = tuple(dict.fromkeys([*existing.aliases, *candidate.aliases]))
            if existing.description is None:
                existing.description = candidate.description
            if existing.transport_value is _MISSING:
                existing.transport_value = candidate.transport_value
            existing.supported = existing.supported and candidate.supported
            if not existing.supported and existing.reason is None:
                existing.reason = candidate.reason
        return result

    @staticmethod
    def _get_path(root: Any, path: str) -> Any:
        current = root
        for part in path.split(".") if path else []:
            if isinstance(current, Mapping):
                if part not in current:
                    return _MISSING
                current = current[part]
            else:
                current = getattr(current, part, _MISSING)
                if current is _MISSING:
                    return _MISSING
        return current

    @staticmethod
    def _normalize_id(value: Any) -> str:
        value = getattr(value, "value", value)
        return str(value).strip().lower().replace("-", "_").replace(" ", "_")

    @staticmethod
    def _json_value(value: Any) -> Any:
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, Mapping):
            return {str(key): OperationResolver._json_value(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [OperationResolver._json_value(item) for item in value]
        if hasattr(value, "item") and callable(value.item):
            try:
                return value.item()
            except (AttributeError, TypeError, ValueError):
                pass
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json", exclude_none=True)
        return value
