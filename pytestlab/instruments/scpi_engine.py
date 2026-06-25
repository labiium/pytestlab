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
import re
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
                    f"Parameter '{name}'={value!r} not in allowed set {{{valid}}}."
                ) from None

        raise AssertionError(f"Unknown validator kind '{self.kind}'")

    def describe(self) -> dict[str, Any]:
        if self.kind == "range":
            return {"kind": "range", "min": self.min_val, "max": self.max_val}
        if self.kind == "enum":
            return {"kind": "enum", "choices": dict(self.enum_map or {})}
        return {"kind": self.kind}


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


@_register_parser("scpi_float")
def _parse_scpi_float(data: str | bytes, spec: _ResponseSpec):
    """Parse SCPI numeric responses that may include headers or qualifiers.

    Keysight scopes can return values such as ``1.00000E+00,RAT`` for
    measurements, or include a command header before the numeric value when
    response headers are enabled.  This parser keeps normal ``float`` strict for
    generic use while allowing profiles to opt into SCPI-specific extraction.
    """
    txt = (
        data.decode("utf-8", errors="ignore") if isinstance(data, bytes | bytearray) else str(data)
    ).strip()
    try:
        return float(txt)
    except ValueError:
        pass

    first_field = txt.split(",", 1)[0].strip()
    try:
        return float(first_field)
    except ValueError:
        pass

    matches = re.findall(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?", txt)
    if not matches:
        raise ValueError(f"could not find a numeric value in {txt!r}")
    return float(matches[-1])


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

    from .scpi_binary import BinaryBlockParseError
    from .scpi_binary import strip_definite_length_block

    try:
        return strip_definite_length_block(data)
    except (BinaryBlockParseError, UnicodeDecodeError) as exc:
        raise ParseError(f"binblock: {exc}") from exc


# ------------------------------------------------------------------------------
#                               Command spec
# ------------------------------------------------------------------------------


@dataclass(slots=True)
class _CommandSpec:
    sequence: list[str]
    defaults: dict[str, Any] = field(default_factory=dict)
    validators: dict[str, _Validator] = field(default_factory=dict)
    parameters: dict[str, dict[str, Any]] = field(default_factory=dict)
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

        # -------- optional variant lookup ----------------------------- #
        if isinstance(scpi_section.get("variants"), Mapping):
            variants = scpi_section["variants"]
            if not isinstance(variants, Mapping):
                raise SCPIEngineError("'variants' must map to an object")

            chosen = variant or scpi_section.get("default_variant")
            if chosen is None:
                raise SCPIEngineError(
                    "YAML has 'variants' but no variant selected and no 'default_variant' provided."
                )
            try:
                scpi_section = variants[chosen]
            except KeyError:
                avail = ", ".join(variants)
                raise SCPIEngineError(
                    f"Variant '{chosen}' not defined. Available: {avail}"
                ) from None

        # -------- commands / queries ---------------------------------- #
        commands_block = scpi_section.get("commands", {}) or {}
        queries_block = scpi_section.get("queries", {}) or {}

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

        # run profile-backed parameter resolution/validation
        for pname in set(spec.parameters) | set(spec.validators):
            if pname in merged:
                merged[pname] = self.resolve_parameter(cmd_name, pname, merged[pname])

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
                f"No parser registered for type '{spec.response.type}' (command '{cmd_name}')."
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

    def list_parameters(self, cmd_name: str) -> list[str]:
        """Return parameter names described for a SCPI command/query."""

        return list(self._spec(cmd_name).parameters.keys())

    def describe_parameter(self, cmd_name: str, parameter: str) -> dict[str, Any]:
        """Return canonical metadata for one SCPI placeholder."""

        spec = self._spec(cmd_name)
        try:
            return dict(spec.parameters[parameter])
        except KeyError:
            raise KeyError(
                f"SCPI command '{cmd_name}' has no parameter metadata for '{parameter}'"
            ) from None

    def list_options(self, cmd_name: str, parameter: str) -> list[dict[str, Any]]:
        """Return enum/bool raw-token choices for a parameter, or [] if not closed-choice."""

        param = self.describe_parameter(cmd_name, parameter)
        if param.get("kind") not in {"enum", "bool"}:
            return []
        return [dict(choice) for choice in param.get("choices", [])]

    def resolve_parameter(self, cmd_name: str, parameter: str, value: Any) -> Any:
        """Resolve/validate one parameter value using profile-backed metadata.

        For enum/bool parameters only the profile choice ``token`` is returned for
        template insertion. Labels and aliases are accepted input forms when the
        profile declares them. No driver-level token table participates here.
        """

        spec = self._spec(cmd_name)
        param = spec.parameters.get(parameter)
        validator = spec.validators.get(parameter)
        if param is None:
            return validator.validate(parameter, value) if validator is not None else value

        kind = str(param.get("kind", "raw"))
        if kind in {"enum", "bool"}:
            choices = list(param.get("choices", []) or [])
            lookup: dict[str, Any] = {}
            for choice in choices:
                token = choice.get("token")
                keys = [token, choice.get("label"), *list(choice.get("aliases", []) or [])]
                for key in keys:
                    if key is not None:
                        lookup[str(key).lower()] = token
            key = str(value.value if hasattr(value, "value") else value).lower()
            if key in lookup:
                return lookup[key]
            if param.get("strict", False):
                valid = ", ".join(str(choice.get("token")) for choice in choices)
                raise ValidationError(
                    f"Parameter '{parameter}'={value!r} not in allowed set {{{valid}}}."
                )
            return validator.validate(parameter, value) if validator is not None else value

        if kind == "range":
            min_val = param.get("min")
            max_val = param.get("max")
            if not isinstance(value, numbers.Real):
                raise ValidationError(
                    f"Parameter '{parameter}' must be numeric for range check, "
                    f"but got type {type(value).__name__}."
                )
            if min_val is not None and float(value) < float(min_val):
                raise ValidationError(
                    f"Parameter '{parameter}'={value!r} outside allowed range "
                    f"[{min_val}, {max_val}]."
                )
            if max_val is not None and float(value) > float(max_val):
                raise ValidationError(
                    f"Parameter '{parameter}'={value!r} outside allowed range "
                    f"[{min_val}, {max_val}]."
                )
            return value

        if kind == "open_string":
            pattern = param.get("pattern")
            if pattern and not re.match(str(pattern), str(value)):
                raise ValidationError(
                    f"Parameter '{parameter}'={value!r} does not match pattern {pattern!r}."
                )
            return value

        return validator.validate(parameter, value) if validator is not None else value

    def describe(self, cmd_name: str) -> dict[str, Any]:
        """
        Return a dictionary describing the SCPI entry:
        - sequence: list of templates
        - defaults: mapping of default parameter values
        - validators: mapping of parameter names to validator kind
        - response: minimal response spec (type/fields) if present
        """
        spec = self._spec(cmd_name)

        validators = {name: val.kind for name, val in spec.validators.items()}
        resp = None
        if spec.response is not None:
            resp = {"type": spec.response.type, "fields": list(spec.response.fields)}
        return {
            "sequence": list(spec.sequence),
            "defaults": dict(spec.defaults),
            "validators": validators,
            "parameters": {name: dict(param) for name, param in spec.parameters.items()},
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
    def _spec(self, cmd_name: str) -> _CommandSpec:
        try:
            return self._specs[cmd_name]
        except KeyError:
            raise KeyError(f"SCPI command '{cmd_name}' not defined") from None

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

        parameters = self._normalize_parameters(mapping, validators, enums_data)

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
            parameters=parameters,
            response=response,
        )

    def _normalize_parameters(
        self,
        mapping: Mapping[str, Any],
        validators: dict[str, _Validator],
        enums_data: Any,
    ) -> dict[str, dict[str, Any]]:
        """Build canonical runtime parameter metadata from explicit and legacy fields."""

        parameters: dict[str, dict[str, Any]] = {}
        raw_parameters = mapping.get("parameters")
        if isinstance(raw_parameters, Mapping):
            for name, raw_param in raw_parameters.items():
                parameters[str(name)] = self._explicit_parameter_metadata(raw_param)

        for name, validator in validators.items():
            if name in parameters:
                continue
            metadata = self._legacy_validator_metadata(validator)
            if metadata is not None:
                parameters[name] = metadata

        if isinstance(enums_data, Mapping):
            for name, enum in enums_data.items():
                if name not in parameters and isinstance(enum, Mapping):
                    parameters[str(name)] = self._legacy_enum_metadata(enum)

        placeholders = self._find_missing_placeholders(self._parameter_templates(mapping), {})
        for placeholder in placeholders:
            parameters.setdefault(
                placeholder,
                {
                    "kind": "raw",
                    "required": True,
                    "strict": False,
                    "choices": [],
                    "metadata_source": "inferred",
                },
            )

        return parameters

    @staticmethod
    def _explicit_parameter_metadata(raw_param: Any) -> dict[str, Any]:
        if isinstance(raw_param, Mapping):
            param = dict(raw_param)
        else:
            param = {"kind": "raw", "description": str(raw_param)}
        param["kind"] = str(param.get("kind") or param.get("type") or "raw")
        param["choices"] = [
            dict(choice) if isinstance(choice, Mapping) else {"token": choice}
            for choice in param.get("choices", []) or []
        ]
        param.setdefault("metadata_source", "explicit")
        return param

    @staticmethod
    def _legacy_validator_metadata(validator: _Validator) -> dict[str, Any] | None:
        if validator.kind == "range":
            return {
                "kind": "range",
                "required": True,
                "strict": True,
                "min": validator.min_val,
                "max": validator.max_val,
                "choices": [],
                "metadata_source": "legacy_validator",
            }
        if validator.kind != "enum":
            return None
        assert validator.enum_map is not None
        return SCPIEngine._legacy_enum_metadata(validator.enum_map)

    @staticmethod
    def _legacy_enum_metadata(enum: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "kind": "enum",
            "required": True,
            "strict": True,
            "choices": [
                {"token": token, "label": str(key), "aliases": [str(key)]}
                for key, token in enum.items()
            ],
            "metadata_source": "legacy_enum",
        }

    @staticmethod
    def _parameter_templates(mapping: Mapping[str, Any]) -> list[str]:
        sequence_value = mapping.get("sequence")
        template_value = mapping.get("template")
        if isinstance(sequence_value, list):
            return [item for item in sequence_value if isinstance(item, str)]
        if isinstance(template_value, str):
            return [template_value]
        return []


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
