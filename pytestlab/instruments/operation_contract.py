from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import Any
from typing import Literal

OperationScope = Literal["family", "model"]


@dataclass(frozen=True)
class OperationOption:
    """Public, JSON-serializable semantic option returned by discovery."""

    value: Any
    label: str
    description: str | None = None
    aliases: tuple[str, ...] = ()
    unit: str | None = None
    supported: bool = True
    reason: str | None = None
    constraints: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "value": self.value,
            "label": self.label,
            "aliases": list(self.aliases),
            "supported": self.supported,
        }
        if isinstance(self.value, str):
            # ``id`` is a convenience alias for string semantic values; unlike
            # a transport token it is stable profile intent metadata.
            result["id"] = self.value
        for name, value in (
            ("description", self.description),
            ("unit", self.unit),
            ("reason", self.reason),
        ):
            if value is not None:
                result[name] = value
        if self.constraints:
            result["constraints"] = self.constraints
        return result


@dataclass(frozen=True)
class OperationParameterDescription:
    """Public description of one callable operation parameter."""

    name: str
    kind: str
    required: bool = True
    default: Any = None
    unit: str | None = None
    dependencies: tuple[str, ...] = ()
    constraints: dict[str, Any] = field(default_factory=dict)
    options: tuple[OperationOption, ...] = ()
    supported: bool = True
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "name": self.name,
            "kind": self.kind,
            "required": self.required,
            "supported": self.supported,
        }
        if self.default is not None:
            result["default"] = self.default
        if self.unit is not None:
            result["unit"] = self.unit
        if self.dependencies:
            result["dependencies"] = list(self.dependencies)
        if self.constraints:
            result["constraints"] = self.constraints
        if self.options:
            result["options"] = [option.to_dict() for option in self.options]
        if self.reason is not None:
            result["reason"] = self.reason
        return result


@dataclass(frozen=True)
class OperationDescription:
    """Typed container for the JSON operation-description contract."""

    operation_id: str
    method: str
    parameters: dict[str, OperationParameterDescription | dict[str, Any]]
    profile: dict[str, Any]
    support: OperationSupportReport | dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        support = (
            self.support.to_dict()
            if isinstance(self.support, OperationSupportReport)
            else self.support
        )
        return {
            "operation_id": self.operation_id,
            "method": self.method,
            "parameters": {
                name: value.to_dict() if isinstance(value, OperationParameterDescription) else value
                for name, value in self.parameters.items()
            },
            "profile": dict(self.profile),
            "support": support,
        }


@dataclass(frozen=True)
class ResolvedOperationParameter:
    """Internal result shared by discovery, execution, and plan validation."""

    value: Any
    transport_value: Any
    option: OperationOption | None = None
    alias: str | None = None
    transport_parameter: str | None = None


@dataclass(frozen=True)
class OperationPythonArgument:
    """Required Python object supplied by the caller, not resolved from a profile.

    The type name is a public documentation label, not an import path or
    serialization contract. The driver's method keeps validation responsibility.
    """

    name: str
    type_name: str
    description: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "name": self.name,
            "type_name": self.type_name,
            "required": True,
        }
        if self.description is not None:
            result["description"] = self.description
        return result


@dataclass(frozen=True)
class OperationDescriptor:
    """Driver-level contract for one high-level instrument operation.

    The descriptor names operation semantics, safety, and optional discovery
    grouping. A profile owns all transport aliases and parameter bindings.
    Scope describes the API surface, not vendor conformance or live support.
    """

    operation_id: str
    capability: str | None = None
    safety_class: str = "state-changing"
    required: bool = True
    public_method: str | None = None
    group: str | None = None
    scope: OperationScope | None = None
    python_arguments: tuple[OperationPythonArgument, ...] = ()
    direct_python_only: bool = False
    # Side-effecting query keys in this direct operation's profile transport.
    direct_transport_queries: tuple[str, ...] = ()

    @property
    def python_only(self) -> bool:
        """Whether this operation is excluded from generic execution."""
        return self.direct_python_only or bool(self.python_arguments)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "operation_id": self.operation_id,
            "method": self.public_method or self.operation_id,
            "capability": self.capability,
            "safety_class": self.safety_class,
            "required": self.required,
        }
        if self.group is not None:
            result["group"] = self.group
        if self.scope is not None:
            result["scope"] = self.scope
        if self.python_only:
            result["python_only"] = True
        if self.python_arguments:
            result["python_arguments"] = [argument.to_dict() for argument in self.python_arguments]
        return result


@dataclass(frozen=True)
class OperationSupportReport:
    """Support status for an operation against one loaded instrument profile."""

    operation_id: str
    supported: bool
    capability_enabled: bool
    missing_required_aliases: tuple[str, ...] = ()
    missing_optional_aliases: tuple[str, ...] = ()
    missing_parameter_metadata: tuple[str, ...] = ()
    missing_capability_metadata: tuple[str, ...] = ()
    required: bool = True
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "supported": self.supported,
            "capability_enabled": self.capability_enabled,
            "missing_parameters": sorted(
                set(self.missing_parameter_metadata) | set(self.missing_capability_metadata)
            ),
            "required": self.required,
            "reason": self.reason,
        }
