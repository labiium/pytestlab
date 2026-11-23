from __future__ import annotations

# Ensure this module is discoverable as 'pytestlab.config.scpi_schema'
# in environments where the package loader may not auto-register submodules.
import sys as _sys
from typing import Any
from typing import Literal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import model_validator

if __name__ != "pytestlab.config.scpi_schema":
    _sys.modules["pytestlab.config.scpi_schema"] = (
        _sys.modules.get(__name__) or _sys.modules[__name__]
    )
    # Note: harmless no-op when already imported under the package path.


class RangeValidator(BaseModel):
    model_config = ConfigDict(validate_assignment=True, extra="forbid")
    min: float
    max: float


class SCPIChoiceSpec(BaseModel):
    """One SCPI choice with an optional semantic public value.

    ``token`` is the value substituted into a SCPI template.  ``value`` is an
    optional profile-defined semantic value used by the high-level operation
    resolver; it is never returned by low-level SCPI diagnostics as a token
    replacement.
    """

    model_config = ConfigDict(validate_assignment=True, extra="forbid")
    token: str | int | float | bool
    value: str | int | float | bool | None = None
    label: str | None = None
    aliases: list[str] = Field(default_factory=list)
    description: str | None = None
    evidence: dict[str, Any] | str | None = None


class SCPIParameterSpec(BaseModel):
    """Canonical profile/runtime metadata for a SCPI placeholder."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")
    kind: Literal["enum", "range", "open_string", "bool", "raw"] = "raw"
    required: bool = True
    strict: bool = False
    allow_raw: bool = False
    choices: list[SCPIChoiceSpec] = Field(default_factory=list)
    min: float | None = None
    max: float | None = None
    unit: str | None = None
    pattern: str | None = None
    examples: list[str | int | float] = Field(default_factory=list)
    default: str | int | float | bool | None = None
    description: str | None = None
    evidence: dict[str, Any] | str | None = None

    @model_validator(mode="after")
    def _validate_parameter_shape(self) -> SCPIParameterSpec:
        if self.kind in {"enum", "bool"} and self.strict and not self.choices:
            raise ValueError(f"strict {self.kind} parameter requires choices")
        if self.kind == "range" and (self.min is None or self.max is None):
            raise ValueError("range parameter requires min and max")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("parameter min cannot be greater than max")
        return self


class ResponseSpec(BaseModel):
    model_config = ConfigDict(validate_assignment=True, extra="forbid")
    transport: Literal["query", "read", "read_raw"] = "query"
    type: Literal[
        "raw",
        "str",
        "int",
        "float",
        "scpi_float",
        "csv",
        "csv_int",
        "csv_float",
        "csv_dict",
        "binblock",
    ] = "raw"
    units: str | None = None
    delimiter: str = ","
    fields: list[str] = Field(default_factory=list)
    numeric_map: dict[str, str] = Field(default_factory=dict)


class CommandSpec(BaseModel):
    model_config = ConfigDict(validate_assignment=True, extra="forbid")
    # Exactly one of template or sequence is required; we allow both optional for leniency
    template: str | None = None
    sequence: list[str] | None = None
    defaults: dict[str, str | int | float] = Field(default_factory=dict)
    validators: dict[str, RangeValidator] = Field(default_factory=dict)
    # Allow mixed-type keys (e.g., true/false/1/0) for convenience in YAML profiles
    enums: dict[str, dict[Any, str | int | float]] = Field(default_factory=dict)
    parameters: dict[str, SCPIParameterSpec] = Field(default_factory=dict)
    response: ResponseSpec | None = None


class CommandsQueries(BaseModel):
    model_config = ConfigDict(validate_assignment=True, extra="forbid")
    commands: dict[str, CommandSpec] = Field(default_factory=dict)
    queries: dict[str, CommandSpec] = Field(default_factory=dict)


class SCPISection(BaseModel):
    # Allow unknown keys to preserve backward compatibility with ad-hoc SCPI sections in tests/profiles
    model_config = ConfigDict(validate_assignment=True, extra="ignore")
    # Either commands/queries directly, or a variants block
    commands: dict[str, CommandSpec] | None = None
    queries: dict[str, CommandSpec] | None = None
    variants: dict[str, CommandsQueries] | None = None
    default_variant: str | None = None

    # Optional high-level feature → SCPI mapping for validation and capability docs
    feature_mappings: dict[str, dict[str, list[str]]] | None = Field(
        default=None,
        description=(
            "Declarative feature mapping: { feature_name: { required_scpi: [...], optional_scpi: [...] } }"
        ),
    )

    @model_validator(mode="after")
    def _validate_structure(self) -> SCPISection:
        has_direct = bool(self.commands or self.queries)
        has_variants = bool(self.variants)
        if not (has_direct or has_variants):
            # Allow empty to preserve legacy behavior, but recommend having one
            return self
        if has_direct and has_variants:
            raise ValueError("SCPISection cannot mix direct commands/queries with variants")
        return self
