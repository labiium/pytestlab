"""Profile-backed semantic operation option metadata.

The models in this module describe the public side of an operation parameter.
A profile may also carry a private ``transport`` mapping; it is deliberately
excluded from normal serialization and is only consumed by the shared
operation resolver.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Any
from typing import Literal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import model_validator

OptionKind = Literal["enum", "range", "open_string", "bool", "unresolved"]
ProfileOperationMode = Literal["write", "query", "native"]
ProfileSafetyClass = Literal["read", "state-changing"]


class OperationTransportSpec(BaseModel):
    """Private semantic-to-transport value mapping for one profile option.

    Command aliases are declared once on :class:`ProfileOperationSpec` and
    selected by parameter bindings.  Keeping this record value-only prevents
    every enum option from repeating the same vendor command alias.
    """

    model_config = ConfigDict(extra="forbid")

    # ``value`` is the normal mapping form.  ``token`` and other vendor names
    # are accepted as private profile data for migration, but never serialized
    # by the public discovery models.
    value: Any = None
    function_token: str | None = None
    measure_alias: str | None = None


class OperationParameterBinding(BaseModel):
    """Private binding from a semantic parameter to a profile alias."""

    model_config = ConfigDict(extra="forbid")

    alias: str
    parameter: str


class ProfileOperationSpec(BaseModel):
    """One operation's semantic metadata and private transport bindings."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    # Keys are semantic operation-local names; values are SCPI-engine aliases.
    # This field is intentionally excluded from public discovery output.
    transport: dict[str, str] = Field(default_factory=dict, exclude=True)
    context_queries: dict[str, str] = Field(default_factory=dict, exclude=True)
    safety_class: ProfileSafetyClass | None = Field(
        None,
        description="Optional safety classification independent of transport mode.",
    )
    response_pattern: str | None = Field(
        None,
        description="Optional regular expression required for a successful query response.",
    )
    mode: ProfileOperationMode | None = Field(
        None,
        description="Generic execution mode; omitted legacy metadata is not executable generically.",
    )
    backend_method: str | None = Field(
        None,
        description="Whitelisted backend method used by native operations.",
    )
    requires_context: list[str] = Field(
        default_factory=list,
        description="Safety context keys that must be truthy before execution.",
    )
    parameters: dict[str, ProfileOperationParameter] = Field(default_factory=dict)
    group: str | None = Field(
        None,
        pattern=r"^[a-z][a-z0-9_]*$",
        description="Optional semantic group ID for offline operation discovery.",
    )
    description: str | None = Field(
        None, description="Optional public description of the operation."
    )
    references: list[str] = Field(
        default_factory=list,
        description="Profile-authored source references; not a claim of live verification.",
    )

    def discovery_metadata(self) -> dict[str, Any]:
        """Return optional public documentation without transport details."""
        return self.model_dump(
            mode="json", include={"group", "description", "references"}, exclude_defaults=True
        )

    @model_validator(mode="before")
    @classmethod
    def _accept_concise_parameters(cls, data: Any) -> Any:
        if not isinstance(data, Mapping) or "parameters" in data:
            return data
        # An operation field in concise YAML is distinct from a parameter spec,
        # which is a mapping even when its name coincides with an optional field.
        operation_keys = {"transport", "context_queries"}
        for key in (
            "safety_class",
            "response_pattern",
            "mode",
            "backend_method",
            "group",
            "description",
        ):
            if key in data and (data[key] is None or isinstance(data[key], str)):
                operation_keys.add(key)
        for key in ("requires_context", "references"):
            if isinstance(data.get(key), list):
                operation_keys.add(key)
        return {
            **{key: value for key, value in data.items() if key in operation_keys},
            "parameters": {key: value for key, value in data.items() if key not in operation_keys},
        }

    @model_validator(mode="after")
    def _validate_bindings(self) -> ProfileOperationSpec:
        if self.response_pattern is not None:
            try:
                re.compile(self.response_pattern)
            except re.error as exc:
                raise ValueError(
                    "operation response_pattern must be a valid regular expression"
                ) from exc
        if len(set(self.requires_context)) != len(self.requires_context):
            raise ValueError("operation requires_context entries must be unique")
        if any(not isinstance(key, str) or not key.strip() for key in self.requires_context):
            raise ValueError("operation requires_context entries must be non-empty strings")
        if self.mode == "native":
            if self.backend_method != "read_status_byte":
                raise ValueError(
                    "native profile operations must use the whitelisted backend method "
                    "'read_status_byte'"
                )
        elif self.backend_method is not None:
            raise ValueError("backend_method is only valid for native profile operations")
        for parameter, spec in self.parameters.items():
            for binding in spec.bindings:
                if binding.alias not in self.transport:
                    raise ValueError(
                        f"operation parameter '{parameter}' binds unknown transport alias "
                        f"'{binding.alias}'"
                    )
                if not self.transport[binding.alias].strip():
                    raise ValueError(f"operation transport alias '{binding.alias}' is empty")
        return self


class ProfileOperationOption(BaseModel):
    """One semantic option declared by an instrument profile."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    value: Any = None
    label: str | None = None
    aliases: list[str] = Field(default_factory=list)
    description: str | None = None
    unit: str | None = None
    supported: bool = True
    reason: str | None = None
    constraints: dict[str, Any] = Field(default_factory=dict)
    transport: OperationTransportSpec | dict[str, Any] | None = Field(
        None, exclude=True, description="Private semantic-to-transport value mapping."
    )

    @model_validator(mode="before")
    @classmethod
    def _accept_id_as_value(cls, data: Any) -> Any:
        if isinstance(data, Mapping):
            result = dict(data)
            if result.get("value") is None and result.get("id") is not None:
                result["value"] = result["id"]
            return result
        return data

    @model_validator(mode="after")
    def _validate_value(self) -> ProfileOperationOption:
        if self.value is None:
            raise ValueError("operation option requires a semantic 'value' (or 'id')")
        if isinstance(self.transport, Mapping):
            self.transport = OperationTransportSpec.model_validate(self.transport)
        return self


class ProfileOperationParameter(BaseModel):
    """Profile metadata for one public operation parameter."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    kind: OptionKind = "unresolved"
    required: bool = True
    strict: bool = True
    options: list[ProfileOperationOption] = Field(default_factory=list)
    min: float | None = None
    max: float | None = None
    positive: bool = False
    multiplier_parameter: str | None = None
    contextual_ranges: list[dict[str, Any]] = Field(default_factory=list)
    constraints: dict[str, Any] = Field(default_factory=dict)
    unit: str | None = None
    default: Any = None
    description: str | None = None
    dependencies: list[str] = Field(default_factory=list)
    source: str | None = Field(
        None,
        description="Profile metadata adapter source (for example measurement_functions).",
    )
    bindings: list[OperationParameterBinding] = Field(default_factory=list, exclude=True)
    integer: bool = Field(
        False,
        description="Require a numeric range value to be an integer.",
    )
    transport_parameter: bool = Field(
        True,
        exclude=True,
        description="Private flag; false marks a validated Python-only parameter.",
    )
    transport_identity: bool = Field(
        False,
        exclude=True,
        description="Private flag; true explicitly maps semantic values to identical transport values.",
    )
    supported: bool = True
    reason: str | None = None

    @model_validator(mode="after")
    def _validate_shape(self) -> ProfileOperationParameter:
        if self.kind in {"enum", "bool"} and self.strict and not self.options and not self.source:
            raise ValueError(f"strict {self.kind} operation parameter requires options")
        if self.kind == "range" and self.min is not None and self.max is not None:
            if self.min > self.max:
                raise ValueError("operation parameter min cannot exceed max")
        if self.positive and self.kind != "range":
            raise ValueError("positive operation parameter validation requires kind='range'")
        if self.multiplier_parameter and self.multiplier_parameter not in self.dependencies:
            raise ValueError("multiplier_parameter must be listed in dependencies")
        for contextual_range in self.contextual_ranges:
            when = contextual_range.get("when")
            minimum = contextual_range.get("min")
            maximum = contextual_range.get("max")
            if not isinstance(when, Mapping) or not when:
                raise ValueError("contextual range requires a non-empty 'when' mapping")
            if minimum is None or maximum is None or float(minimum) > float(maximum):
                raise ValueError("contextual range requires ordered numeric min/max values")
            if not math.isfinite(float(minimum)) or not math.isfinite(float(maximum)):
                raise ValueError("contextual range limits must be finite")
            for predicate in when.values():
                if not isinstance(predicate, Mapping):
                    continue
                allowed = {"min", "max", "exclusive_min", "exclusive_max", "multiplier_parameter"}
                bounds = {"min", "max", "exclusive_min", "exclusive_max"}
                if set(predicate) - allowed or not (bounds & set(predicate)):
                    raise ValueError("contextual band requires numeric min/max conditions")
                for bound in bounds & set(predicate):
                    if isinstance(predicate[bound], bool) or not math.isfinite(
                        float(predicate[bound])
                    ):
                        raise ValueError("contextual band limits must be finite")
                lowers = [
                    float(predicate[key]) for key in ("min", "exclusive_min") if key in predicate
                ]
                uppers = [
                    float(predicate[key]) for key in ("max", "exclusive_max") if key in predicate
                ]
                if lowers and uppers:
                    lower, upper = max(lowers), min(uppers)
                    if lower > upper or (
                        lower == upper
                        and (
                            predicate.get("exclusive_min") == lower
                            or predicate.get("exclusive_max") == upper
                        )
                    ):
                        raise ValueError("contextual band is empty")
                multiplier = predicate.get("multiplier_parameter")
                if multiplier is not None and multiplier not in self.dependencies:
                    raise ValueError("contextual band multiplier must be listed in dependencies")
        integer_constraint = self.constraints.get("integer")
        if integer_constraint is not None and not isinstance(integer_constraint, bool):
            raise ValueError("constraint 'integer' must be a boolean")
        if integer_constraint is not None and self.integer != integer_constraint:
            if self.integer:
                raise ValueError("constraint 'integer' conflicts with its declared parameter field")
            self.integer = integer_constraint
        for name in (
            "min",
            "max",
            "positive",
            "multiplier_parameter",
            "contextual_ranges",
            "integer",
        ):
            if name in self.constraints and self.constraints[name] != getattr(self, name):
                raise ValueError(f"constraint '{name}' conflicts with its declared parameter field")
        seen_values: list[Any] = []
        seen_aliases: dict[str, Any] = {}
        for option in self.options:
            if option.value in seen_values:
                raise ValueError(f"duplicate semantic operation option value {option.value!r}")
            seen_values.append(option.value)
            for alias in [option.value, *option.aliases, option.label]:
                if alias is None or alias == "":
                    continue
                key = str(alias).strip().casefold().replace("-", "_").replace(" ", "_")
                previous = seen_aliases.get(key)
                if previous is not None and previous != option.value:
                    raise ValueError(
                        f"ambiguous operation option alias {alias!r} for values "
                        f"{previous!r} and {option.value!r}"
                    )
                seen_aliases[key] = option.value
        if self.default is not None and self.kind in {"enum", "bool"} and self.options:
            allowed = {option.value for option in self.options}
            if self.default not in allowed:
                raise ValueError(
                    f"operation parameter default {self.default!r} is not a declared option"
                )
            default_option = next(option for option in self.options if option.value == self.default)
            if not default_option.supported:
                raise ValueError(f"operation parameter default {self.default!r} is not supported")
        if self.kind == "range":
            if self.default is not None and isinstance(self.default, bool):
                raise ValueError("range operation parameter default must be numeric")
            if self.default is not None:
                try:
                    numeric_default = float(self.default)
                except (TypeError, ValueError) as exc:
                    raise ValueError("operation parameter default must be numeric") from exc
                if not math.isfinite(numeric_default):
                    raise ValueError("operation parameter default must be finite")
                if self.min is not None and numeric_default < self.min:
                    raise ValueError("operation parameter default is below min")
                if self.max is not None and numeric_default > self.max:
                    raise ValueError("operation parameter default is above max")
        return self


class ProfileOperationOptions(BaseModel):
    """Validated root for the optional generic ``operation_options`` block."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    operations: dict[str, ProfileOperationSpec] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _accept_operation_mapping(cls, data: Any) -> Any:
        """Accept the concise YAML form ``operation: {parameter: ...}``."""
        if not isinstance(data, Mapping):
            return data
        if "operations" in data:
            return data
        return {"operations": dict(data)}

    @model_validator(mode="after")
    def _validate_dependencies(self) -> ProfileOperationOptions:
        for operation_id, operation in self.operations.items():
            parameters = operation.parameters
            graph = {name: set(spec.dependencies) for name, spec in parameters.items()}
            unknown = {
                dependency
                for dependencies in graph.values()
                for dependency in dependencies
                if dependency not in graph
            }
            if unknown:
                raise ValueError(
                    f"operation '{operation_id}' has unknown parameter dependencies: "
                    f"{sorted(unknown)!r}"
                )
            visiting: set[str] = set()
            visited: set[str] = set()

            def visit(
                name: str,
                _graph: dict[str, set[str]] = graph,
                _visiting: set[str] = visiting,
                _visited: set[str] = visited,
                _operation_id: str = operation_id,
            ) -> None:
                if name in _visiting:
                    raise ValueError(
                        f"operation '{_operation_id}' has a dependency cycle involving '{name}'"
                    )
                if name in _visited:
                    return
                _visiting.add(name)
                for dependency in _graph[name]:
                    visit(dependency)
                _visiting.remove(name)
                _visited.add(name)

            for name in graph:
                visit(name)
        return self

    def parameter(self, operation_id: str, parameter: str) -> ProfileOperationParameter | None:
        operation = self.operations.get(operation_id)
        return operation.parameters.get(parameter) if operation else None

    def operation(self, operation_id: str) -> ProfileOperationSpec | None:
        return self.operations.get(operation_id)

    def model_dump_public(self) -> dict[str, Any]:
        """Return only public metadata, excluding private transport mappings."""
        result: dict[str, Any] = {}
        for operation_id, operation in self.operations.items():
            result[operation_id] = {
                "mode": operation.mode,
                "safety_class": operation.safety_class,
                "response_pattern": operation.response_pattern,
                "requires_context": list(operation.requires_context),
                **operation.discovery_metadata(),
            }
            for parameter, spec in operation.parameters.items():
                public = spec.model_dump(mode="json", exclude_none=True, exclude={"transport"})
                result[operation_id][parameter] = public
        return result

    def model_dump_internal(self) -> dict[str, Any]:
        """Serialize complete profile metadata for persistence/replay only."""

        result: dict[str, Any] = {"operations": {}}
        for operation_id, operation in self.operations.items():
            result["operations"][operation_id] = {
                "transport": dict(operation.transport),
                "context_queries": dict(operation.context_queries),
                "response_pattern": operation.response_pattern,
                "safety_class": operation.safety_class,
                "mode": operation.mode,
                "requires_context": list(operation.requires_context),
                **operation.discovery_metadata(),
                "parameters": {},
            }
            if operation.backend_method is not None:
                result["operations"][operation_id]["backend_method"] = operation.backend_method
            for parameter, spec in operation.parameters.items():
                dumped = spec.model_dump(mode="python", exclude_none=True)
                dumped["bindings"] = [
                    binding.model_dump(mode="python") for binding in spec.bindings
                ]
                dumped["transport_parameter"] = spec.transport_parameter
                dumped["transport_identity"] = spec.transport_identity
                for option, option_dump in zip(
                    spec.options, dumped.get("options", []), strict=True
                ):
                    if option.transport is not None:
                        option_dump["transport"] = OperationTransportSpec.model_validate(
                            option.transport
                        ).model_dump(mode="python")
                result["operations"][operation_id]["parameters"][parameter] = dumped
        return result


ProfileOperationSpec.model_rebuild()
