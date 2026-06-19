"""Optional interoperability with the third-party ``uncertainties`` package."""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any


class _MissingUFloat:
    """Sentinel class used when optional uncertainties is not installed."""


def ufloat_type() -> type:
    try:
        from uncertainties.core import UFloat

        return UFloat
    except Exception:  # pragma: no cover - exercised in packaging/no-extra installs
        return _MissingUFloat


if TYPE_CHECKING:  # pragma: no cover
    from uncertainties.core import UFloat as UFloat
else:
    UFloat = ufloat_type()


def is_ufloat(value: Any) -> bool:
    return isinstance(value, UFloat)


def make_ufloat(nominal: float, std_dev: float) -> Any:
    try:
        from uncertainties import ufloat
    except Exception as exc:  # pragma: no cover - depends on optional extra absence
        raise ImportError(
            "The optional 'uncertainties' package is required for legacy ufloat interop. "
            "Install pytestlab[uncertainties-compat] or use pytestlab.uncertainty.uq instead."
        ) from exc
    return ufloat(nominal, std_dev)


def uncertainties_covariance_matrix(values: list[Any]) -> Any:
    try:
        from uncertainties import covariance_matrix
    except Exception as exc:  # pragma: no cover
        raise ImportError(
            "The optional 'uncertainties' package is required to import external ufloat covariance. "
            "Install pytestlab[uncertainties-compat]."
        ) from exc
    return covariance_matrix(values)


def uncertainties_correlated_values(
    nominal_values: list[float], covariance: Any, tags: Any = None
) -> list[Any]:
    try:
        from uncertainties import correlated_values
    except Exception as exc:  # pragma: no cover
        raise ImportError(
            "The optional 'uncertainties' package is required to export legacy correlated ufloats. "
            "Install pytestlab[uncertainties-compat]."
        ) from exc
    return list(correlated_values(nominal_values, covariance, tags=tags))
