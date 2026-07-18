"""Unit algebra for the uncertainty engine.

Ported from the previous ``config/accuracy.py`` implementation. ``pint`` is used
when available; a string-based fallback keeps the core usable in minimal envs.
"""

from __future__ import annotations

from typing import Any

try:  # pragma: no cover - exercised when optional dependency is installed
    import pint

    _UNIT_REGISTRY = pint.UnitRegistry()
except Exception:  # pragma: no cover - fallback keeps core usable in minimal envs
    _UNIT_REGISTRY = None


class UnitCompatibilityError(ValueError):
    """Raised when uncertainty operands use incompatible units."""


def unit_name(unit: str | None) -> str:
    return unit or ""


def assert_compatible_units(left: str | None, right: str | None) -> None:
    """Validate unit compatibility, using pint when available."""

    if not left or not right or left == right:
        return
    if _UNIT_REGISTRY is None:
        raise UnitCompatibilityError(f"Incompatible units: {left!r} and {right!r}")
    try:
        (1 * _UNIT_REGISTRY(left)).to(right)
    except Exception as exc:
        raise UnitCompatibilityError(f"Incompatible units: {left!r} and {right!r}") from exc


def convert_units(value: float, source: str | None, target: str | None) -> float:
    if not source or not target or source == target:
        return value
    assert_compatible_units(source, target)
    if _UNIT_REGISTRY is None:
        return value
    return float((value * _UNIT_REGISTRY(source)).to(target).magnitude)


def _format_unit(unit: Any) -> str:
    unit_text = str(unit)
    return "" if unit_text == "dimensionless" else unit_text


def combine_units(left: str | None, right: str | None, op: str) -> str:
    left = unit_name(left)
    right = unit_name(right)
    if _UNIT_REGISTRY is not None:
        try:
            left_quantity = 1 * _UNIT_REGISTRY(left) if left else 1
            right_quantity = 1 * _UNIT_REGISTRY(right) if right else 1
            if op == "mul":
                return _format_unit(getattr(left_quantity * right_quantity, "units", ""))
            if op == "truediv":
                return _format_unit(getattr(left_quantity / right_quantity, "units", ""))
        except Exception as exc:
            raise UnitCompatibilityError(f"Incompatible units: {left!r} and {right!r}") from exc
    if op == "mul":
        if left and right:
            return f"{left}*{right}"
        return left or right
    if op == "truediv":
        if left and right:
            return "" if left == right else f"{left}/{right}"
        return left or (f"1/{right}" if right else "")
    raise NotImplementedError(op)


def _pint_quantity(value: float, unit: str | None) -> Any:
    if _UNIT_REGISTRY is None:
        return None
    return value * (_UNIT_REGISTRY(unit) if unit else _UNIT_REGISTRY.dimensionless)


def add_sub_nominal(
    left_value: float,
    left_unit: str | None,
    right_value: float,
    right_unit: str | None,
    op: str,
) -> tuple[float, str]:
    """Compute nominal for add/sub, enforcing unit compatibility, result in left unit."""

    if _UNIT_REGISTRY is not None:
        try:
            left_quantity = _pint_quantity(left_value, left_unit)
            right_quantity = _pint_quantity(right_value, right_unit)
            result = (
                left_quantity + right_quantity if op == "add" else left_quantity - right_quantity
            )
            result = result.to(unit_name(left_unit)) if left_unit else result
            return float(result.magnitude), unit_name(left_unit)
        except Exception as exc:
            raise UnitCompatibilityError(
                f"Incompatible units: {left_unit!r} and {right_unit!r}"
            ) from exc
    other_value = convert_units(right_value, right_unit, left_unit)
    nominal = left_value + other_value if op == "add" else left_value - other_value
    return nominal, unit_name(left_unit)


def product_nominal(
    left_value: float,
    left_unit: str | None,
    right_value: float,
    right_unit: str | None,
    op: str,
) -> tuple[float, str, float]:
    """Nominal/unit for mul/div, returning ``(nominal, unit, scale)``.

    ``scale`` is the ratio between the unit-reconciled nominal and the raw
    numeric ``left op right`` (e.g. 1000 for ``V / mV``); callers multiply the
    propagated gradient by it so sensitivities stay consistent with the unit.
    """

    raw = left_value * right_value if op == "mul" else left_value / right_value
    if _UNIT_REGISTRY is not None:
        try:
            lq = _pint_quantity(left_value, left_unit)
            rq = _pint_quantity(right_value, right_unit)
            result = lq * rq if op == "mul" else lq / rq
            if op == "truediv":
                try:
                    result = result.to("")
                except Exception:
                    pass
            nominal = float(result.magnitude)
            scale = (nominal / raw) if raw else 1.0
            return nominal, _format_unit(result.units), scale
        except UnitCompatibilityError:
            raise
        except Exception as exc:
            raise UnitCompatibilityError(
                f"Incompatible units: {left_unit!r} and {right_unit!r}"
            ) from exc
    return raw, combine_units(left_unit, right_unit, op), 1.0


def is_dimensionless(unit: str | None) -> bool:
    if not unit:
        return True
    if _UNIT_REGISTRY is None:
        return False
    try:
        return bool((1 * _UNIT_REGISTRY(unit)).dimensionless)
    except Exception:
        return False


_DSI_BASE_UNITS = {
    "": "one",
    "dimensionless": "one",
    "V": "V",
    "volt": "V",
    "A": "A",
    "ampere": "A",
    "s": "s",
    "second": "s",
    "Hz": "Hz",
    "hertz": "Hz",
    "ohm": "Ohm",
    "Ω": "Ohm",
    "W": "W",
    "watt": "W",
    "F": "F",
    "farad": "F",
}


def is_unit_resolvable(unit: str | None) -> bool:
    """Return whether a unit string can be resolved by the configured unit resolver."""

    if not unit:
        return True
    if unit in _DSI_BASE_UNITS:
        return True
    if _UNIT_REGISTRY is None:
        return False
    try:
        _UNIT_REGISTRY(unit)
        return True
    except Exception:
        return False


def to_dsi_unit(unit: str | None) -> tuple[str, bool]:
    """Return a D-SI-compatible unit identifier and whether resolution succeeded.

    PyTestLab validates against D-SI profile logic at export time; this helper is
    intentionally conservative and never guesses for unparseable units.
    """

    normalized = unit_name(unit)
    if normalized in _DSI_BASE_UNITS:
        return _DSI_BASE_UNITS[normalized], True
    if not normalized:
        return "one", True
    if _UNIT_REGISTRY is None:
        return normalized, False
    try:
        parsed = _UNIT_REGISTRY(normalized)
    except Exception:
        return normalized, False
    base = parsed.to_base_units()
    formatted = _format_unit(base.units)
    if formatted in _DSI_BASE_UNITS:
        return _DSI_BASE_UNITS[formatted], True
    # Keep Pint's normalized spelling for compound units; DCC/D-SI export can
    # reject if a stricter profile map is required.
    return formatted.replace(" ", "_"), True


def require_dsi_unit(unit: str | None) -> str:
    """Return D-SI unit or raise instead of guessing."""

    resolved, ok = to_dsi_unit(unit)
    if not ok:
        raise UnitCompatibilityError(f"Unit {unit!r} cannot be resolved to D-SI.")
    return resolved
