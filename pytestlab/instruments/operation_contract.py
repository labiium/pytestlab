from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import Any


@dataclass(frozen=True)
class OperationDescriptor:
    """Driver-level contract for one high-level instrument operation.

    The descriptor is intentionally generic: it names operation semantics and
    the SCPI aliases a profile must provide for that operation to be usable. It
    does not contain manufacturer or model-specific behavior.
    """

    operation_id: str
    required_aliases: tuple[str, ...] = ()
    optional_aliases: tuple[str, ...] = ()
    capability: str | None = None
    safety_class: str = "state-changing"
    required: bool = True
    parameters: dict[str, Any] = field(default_factory=dict)
    parameter_exemptions: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "required_aliases": list(self.required_aliases),
            "optional_aliases": list(self.optional_aliases),
            "capability": self.capability,
            "safety_class": self.safety_class,
            "required": self.required,
            "parameters": dict(self.parameters),
            "parameter_exemptions": dict(self.parameter_exemptions),
        }


@dataclass(frozen=True)
class OperationSupportReport:
    """Support status for an operation against one loaded instrument profile."""

    operation_id: str
    supported: bool
    capability_enabled: bool
    missing_required_aliases: tuple[str, ...] = ()
    missing_optional_aliases: tuple[str, ...] = ()
    missing_parameter_metadata: tuple[str, ...] = ()
    required: bool = True
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "supported": self.supported,
            "capability_enabled": self.capability_enabled,
            "missing_required_aliases": list(self.missing_required_aliases),
            "missing_optional_aliases": list(self.missing_optional_aliases),
            "missing_parameter_metadata": list(self.missing_parameter_metadata),
            "required": self.required,
            "reason": self.reason,
        }
