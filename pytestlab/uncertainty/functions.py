"""Elementary math functions with first-order uncertainty propagation.

Each function evaluates the nominal value and propagates the gradient by the
chain rule: ``f(Y)`` has gradient ``f'(y0) · grad(Y)``. Transcendental functions
require a dimensionless argument.
"""

from __future__ import annotations

import math

from . import units
from .quantity import Number
from .quantity import Quantity


def _as_quantity(x: Quantity | Number) -> Quantity:
    return x if isinstance(x, Quantity) else Quantity.constant(x)


def _require_dimensionless(q: Quantity, name: str) -> None:
    if not units.is_dimensionless(q.unit):
        raise units.UnitCompatibilityError(f"{name}() requires a dimensionless argument, got {q.unit!r}")


def _unary(x: Quantity | Number, value: float, deriv: float, unit: str = "") -> Quantity:
    q = _as_quantity(x)
    grad = {uid: deriv * g for uid, g in q.grad.items() if deriv * g != 0.0}
    return Quantity(value, unit, grad, q.registry)


def sqrt(x: Quantity | Number) -> Quantity:
    q = _as_quantity(x)
    value = math.sqrt(q.nominal)
    deriv = 0.5 / value if value != 0 else math.inf
    return _unary(q, value, deriv, q._pow_unit(0.5))


def log(x: Quantity | Number) -> Quantity:
    q = _as_quantity(x)
    _require_dimensionless(q, "log")
    return _unary(q, math.log(q.nominal), 1.0 / q.nominal)


def log10(x: Quantity | Number) -> Quantity:
    q = _as_quantity(x)
    _require_dimensionless(q, "log10")
    return _unary(q, math.log10(q.nominal), 1.0 / (q.nominal * math.log(10.0)))


def exp(x: Quantity | Number) -> Quantity:
    q = _as_quantity(x)
    _require_dimensionless(q, "exp")
    value = math.exp(q.nominal)
    return _unary(q, value, value)


def sin(x: Quantity | Number) -> Quantity:
    q = _as_quantity(x)
    _require_dimensionless(q, "sin")
    return _unary(q, math.sin(q.nominal), math.cos(q.nominal))


def cos(x: Quantity | Number) -> Quantity:
    q = _as_quantity(x)
    _require_dimensionless(q, "cos")
    return _unary(q, math.cos(q.nominal), -math.sin(q.nominal))


def tan(x: Quantity | Number) -> Quantity:
    q = _as_quantity(x)
    _require_dimensionless(q, "tan")
    return _unary(q, math.tan(q.nominal), 1.0 / math.cos(q.nominal) ** 2)


def atan2(y: Quantity | Number, x: Quantity | Number) -> Quantity:
    qy = _as_quantity(y)
    qx = _as_quantity(x)
    if qx.registry is not qy.registry:
        raise ValueError("atan2 operands must share an atom registry.")
    denom = qx.nominal**2 + qy.nominal**2
    value = math.atan2(qy.nominal, qx.nominal)
    # d atan2 = (x dy - y dx) / (x^2 + y^2)
    grad = qy._combine_grads(qx, qx.nominal / denom, -qy.nominal / denom)
    return Quantity(value, "", grad, qy.registry)


def power(x: Quantity | Number, p: Number) -> Quantity:
    return _as_quantity(x) ** float(p)


def absolute(x: Quantity | Number) -> Quantity:
    q = _as_quantity(x)
    sign = 1.0 if q.nominal >= 0 else -1.0
    return _unary(q, abs(q.nominal), sign, q.unit)
