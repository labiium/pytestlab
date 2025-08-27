"""
pytestlab.instruments.scpi_engine
=================================

A **single, production-grade implementation** that provides

•  string-safe SCPI **command building**                 (``build()``)
•  parameter **validation & enumeration mapping**        (range / enum)
•  automatic **query response parsing**                  (``parse()``)
•  optional **multi-variant** selection                  (different models, one YAML)

Everything is completely declarative – _100 % of the instrument-specific SCPI
lives in the YAML profile_, not in Python source code.

----------------------------------------------------------------------------
Quick start
----------------------------------------------------------------------------

    >>> import yaml
    >>> from pytestlab.instruments.scpi_engine import SCPIEngine
    >>>
    >>> cfg = yaml.safe_load(open("my_scope.yml", "rt"))["scpi"]
    >>> scpi = SCPIEngine(cfg)           # or SCPIEngine(cfg, variant="rigol")
    >>>
    >>> # 1) Build commands / sequences
    >>> cmds = scpi.build("set_voltage", channel=2, voltage=5)
    >>> print(cmds)                      # ['VOLT 5, (@2)']
    >>>
    >>> # 2) Parse query responses
    >>> raw  = "-3.14E-6"                # imagine this was read from the scope
    >>> val  = scpi.parse("measure_curr", raw)
    >>> print(val)                       # -3.14e-06   (float)

----------------------------------------------------------------------------
YAML snippet (per-instrument)
----------------------------------------------------------------------------

scpi:
  commands:
    set_voltage:
      template: "VOLT {voltage}, (@{channel})"
      defaults: {channel: 1}
      validators:
        voltage: {min: 0, max: 30}

  queries:
    measure_curr:
      template: "MEAS:CURR? (@{channel})"
      response:
        type: float          # will be converted by built-in parser
"""

from __future__ import annotations

import numbers
import string
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field
from typing import Any

from ..config.scpi_schema import SCPISection

__all__ = [
    "SCPIEngine",
    "SCPIEngineError",
    "ValidationError",
    "ParseError",
    "register_parser",
]

# ------------------------------------------------------------------------------
#                               Exceptions
# ------------------------------------------------------------------------------


class SCPIEngineError(RuntimeError):
    """Base class for all SCPI-engine related problems."""


class ValidationError(SCPIEngineError):
    """Raised when user-supplied parameters violate declared validators."""


class ParseError(SCPIEngineError):
    """Raised when a query response cannot be parsed as requested."""


# ------------------------------------------------------------------------------
#                               Validators
# ------------------------------------------------------------------------------


@dataclass(slots=True)
class _Validator:
    """Runtime representation of a parameter validator."""

    kind: str  # "range" │ "enum"
    min_val: float | None = None
    max_val: float | None = None
    enum_map: dict[str, Any] | None = None

    # ------------------------------------------------------------------ #
    def validate(self, name: str, value: Any) -> Any:
        """Return a (possibly mapped) value or raise ValidationError."""
        if self.kind == "range":
            if not isinstance(value, numbers.Real):
                raise ValidationError(
                    f"Parameter '{name}' must be numeric for range check, "
                    f"but got type {type(value).__name__}."
                )
            assert self.min_val is not None and self.max_val is not None
            if not (self.min_val <= float(value) <= self.max_val):
                raise ValidationError(
                    f"Parameter '{name}'={value!r} outside allowed range "
                    f"[{self.min_val}, {self.max_val}]."
                )
            return value

        if self.kind == "enum":
            assert self.enum_map is not None
            try:
                return self.enum_map[str(value).lower()]
            except KeyError:
                valid = ", ".join(self.enum_map.keys())
                raise ValidationError(
                    f"Parameter '{name}'={value!r} not in allowed set " f"{{{valid}}}."
                ) from None

        raise AssertionError(f"Unknown validator kind '{self.kind}'")


# ------------------------------------------------------------------------------
#                               Response parsing
# ------------------------------------------------------------------------------


@dataclass(slots=True)
class _ResponseSpec:
    """Description of how a query responds."""

    type: str = "raw"
    units: str | None = None
    delimiter: str = ","
    fields: list[str] = field(default_factory=list)
    extras: dict[str, Any] = field(default_factory=dict)


_ParserFunc = Any  # runtime, avoid circular typing
_PARSER_REGISTRY: dict[str, _ParserFunc] = {}


def _register_parser(name: str):
    """Decorator for registering built-in & user parsers."""

    def decorator(func: _ParserFunc):
        if name in _PARSER_REGISTRY:
            raise SCPIEngineError(f"Parser '{name}' already registered.")
        _PARSER_REGISTRY[name] = func
        return func

    return decorator


# ---------------------- built-in parsers ---------------------------------- #


@_register_parser("raw")
def _parse_raw(data: str | bytes, spec: _ResponseSpec):  # noqa: D401
    """Return data unchanged."""
    return data


@_register_parser("str")
def _parse_str(data: str | bytes, spec: _ResponseSpec):
    txt = (
        data.decode("utf-8", errors="ignore") if isinstance(data, bytes | bytearray) else str(data)
    )
    return txt.strip()


@_register_parser("int")
def _parse_int(data: str | bytes, spec: _ResponseSpec):
    txt = (
        data.decode("utf-8", errors="ignore") if isinstance(data, bytes | bytearray) else str(data)
    )
    return int(txt.strip())


@_register_parser("float")
def _parse_float(data: str | bytes, spec: _ResponseSpec):
    txt = (
        data.decode("utf-8", errors="ignore") if isinstance(data, bytes | bytearray) else str(data)
    )
    return float(txt.strip())


@_register_parser("csv")
def _parse_csv(data: str | bytes, spec: _ResponseSpec):
    txt = (
        data.decode("utf-8", errors="ignore") if isinstance(data, bytes | bytearray) else str(data)
    )
    txt = txt.strip()
    return [p.strip() for p in txt.split(spec.delimiter) if p]


@_register_parser("csv_int")
def _parse_csv_int(data: str | bytes, spec: _ResponseSpec):
    return [int(x) for x in _parse_csv(data, spec)]


@_register_parser("csv_float")
def _parse_csv_float(data: str | bytes, spec: _ResponseSpec):
    return [float(x) for x in _parse_csv(data, spec)]


@_register_parser("csv_dict")
def _parse_csv_dict(data: str | bytes, spec: _ResponseSpec):
    parts = _parse_csv(data, spec)
    if spec.fields and len(parts) != len(spec.fields):
        raise ParseError(
            f"csv_dict: expected {len(spec.fields)} fields ({spec.fields}), "
            f"got {len(parts)} in response {data!r}."
        )
    return dict(zip(spec.fields, parts, strict=False))


@_register_parser("binblock")
def _parse_binblock(data: str | bytes, spec: _ResponseSpec):
    """
    Strip SCPI definite-length binary-block header '#<n><len>'.

    Returns
    -------
    bytes
    """
    if isinstance(data, str):
        data = data.encode("utf-8")

    if not data.startswith(b"#"):
        raise ParseError("binblock: data does not start with '#' header")

    n_digits = int(chr(data[1]))
    length = int(data[2 : 2 + n_digits].decode())
    start = 2 + n_digits
    return data[start : start + length]


# ------------------------------------------------------------------------------
#                               Command spec
# ------------------------------------------------------------------------------


@dataclass(slots=True)
class _CommandSpec:
    sequence: list[str]
    defaults: dict[str, Any] = field(default_factory=dict)
    validators: dict[str, _Validator] = field(default_factory=dict)
    response: _ResponseSpec | None = None


# ------------------------------------------------------------------------------
#                               Engine
# ------------------------------------------------------------------------------


class SCPIEngine:
    """
    Build & parse SCPI messages from a declarative YAML section.

    Parameters
    ----------
    scpi_section
        Mapping taken from the YAML profile, **must** contain *commands:* and/or
        *queries:* blocks (unless a *variants:* mechanism is used, see below).
    variant
        Optional name when `scpi_section` holds a top-level *variants:* block.
        If omitted, ``scpi_section["default_variant"]`` is honoured.
    """

    # ------------------------------------------------------------------ #
    # Constructor
    # ------------------------------------------------------------------ #
    def __init__(
        self, scpi_section: SCPISection | Mapping[str, Any], *, variant: str | None = None
    ):
        if isinstance(scpi_section, SCPISection):
            scpi_section = scpi_section.model_dump(exclude_none=True)

        if not isinstance(scpi_section, Mapping):
            raise SCPIEngineError("'scpi_section' must be a mapping")
        if not isinstance(scpi_section, Mapping):
            raise SCPIEngineError("'scpi_section' must be a mapping")

        # -------- optional variant lookup ----------------------------- #
        if isinstance(scpi_section.get("variants"), Mapping):
            variants = scpi_section["variants"]
            if not isinstance(variants, Mapping):
                raise SCPIEngineError("'variants' must map to an object")

            chosen = variant or scpi_section.get("default_variant")
            if chosen is None:
                raise SCPIEngineError(
                    "YAML has 'variants' but no variant selected and no "
                    "'default_variant' provided."
                )
            try:
                scpi_section = variants[chosen]
            except KeyError:
                avail = ", ".join(variants)
                raise SCPIEngineError(
                    f"Variant '{chosen}' not defined. Available: {avail}"
                ) from None

        # -------- commands / queries ---------------------------------- #
        # Ensure scpi_section has the get method by checking if it's a Mapping
        if hasattr(scpi_section, "get"):
            commands_block = scpi_section.get("commands", {}) or {}
            queries_block = scpi_section.get("queries", {}) or {}
        else:
            # Fallback for SCPISection objects
            commands_block = getattr(scpi_section, "commands", {}) or {}
            queries_block = getattr(scpi_section, "queries", {}) or {}

        if not isinstance(commands_block, Mapping) or not isinstance(queries_block, Mapping):
            raise SCPIEngineError("'commands'/'queries' must map to objects")

        self._specs: dict[str, _CommandSpec] = {}
        for name, raw in {**commands_block, **queries_block}.items():
            if name in self._specs:
                raise SCPIEngineError(f"Duplicate SCPI name '{name}'")
            self._specs[name] = self._parse_raw_spec(name, raw)

    # ------------------------------------------------------------------ #
    # Public helpers
    # ------------------------------------------------------------------ #
    def build(self, cmd_name: str, **params: Any) -> list[str]:
        """
        Return the fully-formatted SCPI message list for ``cmd_name``.

        Raises
        ------
        KeyError
            If the command is not defined.
        ValidationError
            Missing or invalid parameters.
        """
        try:
            spec = self._specs[cmd_name]
        except KeyError:
            raise KeyError(f"SCPI command '{cmd_name}' not defined") from None

        merged = {**spec.defaults, **params}

        # Convert enum objects to their values for template substitution
        for key, value in merged.items():
            if hasattr(value, "value") and callable(getattr(value, "value", None)):
                # This is an enum object, convert to its value
                merged[key] = value.value

        missing = self._find_missing_placeholders(spec.sequence, merged)
        if missing:
            raise ValidationError(f"Missing parameter(s) {', '.join(missing)} for '{cmd_name}'.")

        # run validation
        for pname, validator in spec.validators.items():
            if pname in merged:
                merged[pname] = validator.validate(pname, merged[pname])

        try:
            return [tmpl.format(**merged) for tmpl in spec.sequence]
        except KeyError as e:  # pragma: no cover (should not happen)
            raise ValidationError(
                f"Placeholder {e.args[0]!r} not supplied for '{cmd_name}'."
            ) from e

    # ------------------------------------------------------------------ #
    def parse(self, cmd_name: str, raw_response: str | bytes) -> Any:
        """
        Parse *raw_response* according to YAML *response* description.

        If no response spec exists, the input is passed through unchanged.
        """
        try:
            spec = self._specs[cmd_name]
        except KeyError:
            raise KeyError(f"SCPI command '{cmd_name}' not defined") from None

        if spec.response is None:
            return raw_response

        parser = _PARSER_REGISTRY.get(spec.response.type)
        if parser is None:
            raise ParseError(
                f"No parser registered for type '{spec.response.type}' " f"(command '{cmd_name}')."
            )
        try:
            return parser(raw_response, spec.response)
        except Exception as exc:
            raise ParseError(f"Failed to parse response for '{cmd_name}': {exc}") from exc

    # ------------------------------------------------------------------ #
    # Introspection helpers
    # ------------------------------------------------------------------ #
    def list_names(self) -> list[str]:
        """Return a list of all SCPI command/query names known to the engine."""
        return list(self._specs.keys())

    def describe(self, cmd_name: str) -> dict[str, Any]:
        """
        Return a dictionary describing the SCPI entry:
        - sequence: list of templates
        - defaults: mapping of default parameter values
        - validators: mapping of parameter names to validator kind
        - response: minimal response spec (type/fields) if present
        """
        try:
            spec = self._specs[cmd_name]
        except KeyError:
            raise KeyError(f"SCPI command '{cmd_name}' not defined") from None

        validators = {name: val.kind for name, val in spec.validators.items()}
        resp = None
        if spec.response is not None:
            resp = {"type": spec.response.type, "fields": list(spec.response.fields)}
        return {
            "sequence": list(spec.sequence),
            "defaults": dict(spec.defaults),
            "validators": validators,
            "response": resp,
        }

    def validate_presence(self, names: list[str]) -> dict[str, bool]:
        """Check presence of each name in the engine."""
        present = set(self._specs.keys())
        return {n: (n in present) for n in names}

    def validate_placeholders(
        self, cmd_name: str, required_params: list[str] | None = None
    ) -> dict[str, Any]:
        """
        Inspect placeholders used by a command sequence and compare with required_params.
        Returns:
          - placeholders: sorted unique placeholder names found in templates
          - missing_required: required params not present in placeholders
          - extra_params: placeholders not listed in required_params (empty if required_params is None)
        """
        try:
            spec = self._specs[cmd_name]
        except KeyError:
            raise KeyError(f"SCPI command '{cmd_name}' not defined") from None

        # With empty params, _find_missing_placeholders returns all placeholders encountered
        placeholders = self._find_missing_placeholders(spec.sequence, {})
        req = required_params or []
        missing_required = sorted([p for p in req if p not in placeholders])
        extra_params = sorted([p for p in placeholders if req and p not in req])
        return {
            "placeholders": placeholders,
            "missing_required": missing_required,
            "extra_params": extra_params,
        }

    # ------------------------------------------------------------------ #
    # Private helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _find_missing_placeholders(templates: list[str], params: Mapping[str, Any]) -> list[str]:
        formatter = string.Formatter()
        missing: set[str] = set()
        for tmpl in templates:
            for _, field_name, *_ in formatter.parse(tmpl):
                if field_name and field_name not in params:
                    missing.add(field_name)
        return sorted(missing)

    # ------------------------------------------------------------------ #
    def _parse_raw_spec(self, name: str, raw: Any) -> _CommandSpec:
        """
        Normalise a YAML entry (string or mapping) into a _CommandSpec instance.
        """
        # ---- obtain sequence ---------------------------------------- #
        if isinstance(raw, str):
            sequence = [raw]
            mapping: Mapping[str, Any] = {}
        elif isinstance(raw, Mapping):
            mapping = raw
            key = next(
                (
                    k
                    for k in ("sequence", "template", "command", "query")
                    if k in raw and raw[k] is not None
                ),
                None,
            )
            if key is None:
                raise SCPIEngineError(f"Command '{name}' missing 'template/sequence'")
            seq_raw = raw[key]
            if isinstance(seq_raw, str):
                sequence = [seq_raw]
            elif isinstance(seq_raw, list) and all(isinstance(s, str) for s in seq_raw):
                sequence = list(seq_raw)
            else:
                raise SCPIEngineError(f"Command '{name}' '{key}' must be string or list of strings")
        else:
            raise SCPIEngineError(f"Command '{name}' must be string or mapping")

        # ---- defaults ---------------------------------------------- #
        defaults_data = mapping.get("defaults")
        if defaults_data is not None:
            defaults = dict(defaults_data)
        else:
            defaults = {}

        # ---- validators -------------------------------------------- #
        validators: dict[str, _Validator] = {}
        validators_data = mapping.get("validators")
        if validators_data is not None:
            for p, rng in validators_data.items():
                if not isinstance(rng, Mapping) or "min" not in rng or "max" not in rng:
                    raise SCPIEngineError(f"Validator for '{p}' needs 'min'/'max'")
                validators[p] = _Validator(
                    kind="range", min_val=float(rng["min"]), max_val=float(rng["max"])
                )

        enums_data = mapping.get("enums")
        if enums_data is not None:
            for p, enum in enums_data.items():
                if not isinstance(enum, Mapping):
                    raise SCPIEngineError(f"'enums' for '{p}' must map to values")
                validators[p] = _Validator(
                    kind="enum",
                    enum_map={str(k).lower(): v for k, v in enum.items()},
                )

        # ---- response ---------------------------------------------- #
        response = None
        if "response" in mapping and mapping["response"] is not None:
            resp_raw = mapping["response"]
            if isinstance(resp_raw, Mapping):
                response = _ResponseSpec(
                    type=str(resp_raw.get("type", "raw")).lower(),
                    units=resp_raw.get("units"),
                    delimiter=resp_raw.get("delimiter", ","),
                    fields=list(resp_raw.get("fields", [])),
                    extras={
                        k: v
                        for k, v in resp_raw.items()
                        if k not in {"type", "units", "delimiter", "fields"}
                    },
                )
            else:
                # Tolerate non-mapping response specs (e.g., strings, numbers, None)
                # by ignoring them instead of raising an error.
                response = None

        return _CommandSpec(
            sequence=sequence,
            defaults=defaults,
            validators=validators,
            response=response,
        )


# ------------------------------------------------------------------------------
#                       Public helper to add custom parsers
# ------------------------------------------------------------------------------


def register_parser(name: str, func: _ParserFunc) -> None:
    """
    Register a **custom response parser** available via YAML ``response.type``.

    Example
    -------
    >>> def hex_int(data, spec):
    ...     return int(data.strip(), 16)
    ...
    >>> register_parser("hex_int", hex_int)
    >>> # later in YAML:  response: {type: hex_int}
    """
    if name in _PARSER_REGISTRY:
        raise SCPIEngineError(f"Parser '{name}' already exists")
    _PARSER_REGISTRY[name] = func
