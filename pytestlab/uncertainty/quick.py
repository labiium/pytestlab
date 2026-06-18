"""Ergonomic scalar uncertainty constructors and compatibility helpers."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np

from .atoms import AtomRegistry
from .atoms import Distribution
from .atoms import Kind
from .atoms import default_registry
from .atoms import divisor_for
from .metrology import traceability_ref_from_any
from .multivariate import QuantityVector
from .multivariate import _validate_covariance_matrix
from .quantity import Quantity


def _distribution(value: Distribution | str) -> Distribution:
    return value if isinstance(value, Distribution) else Distribution(value)


def _kind(value: Kind | str) -> Kind:
    return value if isinstance(value, Kind) else Kind(value)


def _standard_uncertainty(value: float, *, name: str = "std_uncertainty") -> float:
    std = float(value)
    if not np.isfinite(std):
        raise ValueError(f"{name} must be finite.")
    if std < 0.0:
        raise ValueError(f"{name} must be non-negative.")
    return std


def _unit_list(units: Sequence[str] | str, n: int) -> list[str]:
    if isinstance(units, str):
        return [units] * n
    out = list(units)
    if len(out) != n:
        raise ValueError("units length must match values length.")
    return out


def _label_list(labels: Sequence[str] | None, n: int, *, prefix: str = "x") -> list[str]:
    if labels is None:
        return [f"{prefix}{i}" for i in range(n)]
    out = list(labels)
    if len(out) != n:
        raise ValueError("labels length must match values length.")
    return out


class _UQFactory:
    """Callable uncertainty factory with discoverable metrology constructors."""

    def __call__(
        self,
        nominal: float,
        std_uncertainty: float,
        unit: str = "",
        *,
        label: str | None = None,
        tag: str | None = None,
        registry: AtomRegistry | None = None,
        distribution: Distribution | str = Distribution.STANDARD,
        degrees_of_freedom: float | None = None,
        kind: Kind | str = Kind.TYPE_B,
        source: str | None = None,
        traceability: Any | None = None,
        key: str | None = None,
    ) -> Quantity:
        reg = registry or default_registry()
        std = _standard_uncertainty(std_uncertainty)
        atom = reg.mint(
            nominal=float(nominal),
            std_uncertainty=std,
            label=label or tag or "uncertain value",
            unit=unit or None,
            distribution=_distribution(distribution),
            degrees_of_freedom=degrees_of_freedom,
            kind=_kind(kind),
            source=source,
            traceability=traceability_ref_from_any(traceability),
            key=key,
        )
        return Quantity.from_atom(atom, reg)

    def limit(
        self,
        nominal: float,
        half_width: float,
        unit: str = "",
        *,
        distribution: Distribution | str = Distribution.RECTANGULAR,
        coverage_factor: float = 1.0,
        **kwargs: Any,
    ) -> Quantity:
        dist = _distribution(distribution)
        std = abs(float(half_width)) / divisor_for(dist, coverage_factor)
        if not np.isfinite(std):
            raise ValueError("half_width must produce a finite standard uncertainty.")
        return self(nominal, std, unit, distribution=dist, **kwargs)

    from_limit = limit

    def relative(
        self,
        nominal: float,
        relative_uncertainty: float,
        unit: str = "",
        *,
        distribution: Distribution | str = Distribution.STANDARD,
        coverage_factor: float = 1.0,
        **kwargs: Any,
    ) -> Quantity:
        dist = _distribution(distribution)
        std = (
            abs(float(nominal))
            * abs(float(relative_uncertainty))
            / divisor_for(dist, coverage_factor)
        )
        if not np.isfinite(std):
            raise ValueError("relative_uncertainty must produce a finite standard uncertainty.")
        return self(nominal, std, unit, distribution=dist, **kwargs)

    from_relative = relative

    def percent(
        self,
        nominal: float,
        percent: float,
        unit: str = "",
        **kwargs: Any,
    ) -> Quantity:
        return self.relative(nominal, float(percent) / 100.0, unit, **kwargs)

    from_percent = percent

    def ppm(
        self,
        nominal: float,
        ppm: float,
        unit: str = "",
        **kwargs: Any,
    ) -> Quantity:
        return self.relative(nominal, float(ppm) * 1e-6, unit, **kwargs)

    from_ppm = ppm

    def fromstr(
        self,
        representation: str,
        unit: str = "",
        *,
        tag: str | None = None,
        label: str | None = None,
        registry: AtomRegistry | None = None,
        **kwargs: Any,
    ) -> Quantity:
        return ufloat_fromstr(
            representation,
            tag=tag or label,
            unit=unit,
            registry=registry,
            **kwargs,
        )


uq = _UQFactory()
uquantity = uq


def ufloat(
    nominal_value: float | str, std_dev: float | None = None, tag: str | None = None
) -> Quantity:
    """Compatibility constructor matching the common ``uncertainties.ufloat`` signature."""

    if isinstance(nominal_value, str):
        if std_dev is not None:
            raise TypeError("std_dev must be omitted when parsing a string ufloat.")
        return ufloat_fromstr(nominal_value, tag=tag)
    if std_dev is None:
        raise TypeError("ufloat() missing required std_dev argument.")
    return uq(float(nominal_value), float(std_dev), label=tag, tag=tag)


def ufloat_fromstr(
    representation: str,
    tag: str | None = None,
    *,
    unit: str = "",
    registry: AtomRegistry | None = None,
    **kwargs: Any,
) -> Quantity:
    from uncertainties import ufloat_fromstr as _uncertainties_ufloat_fromstr

    parsed = _uncertainties_ufloat_fromstr(representation, tag=tag)
    return uq(
        float(parsed.nominal_value),
        float(parsed.std_dev),
        unit,
        label=tag,
        tag=tag,
        registry=registry,
        **kwargs,
    )


def nominal_value(value: Any) -> Any:
    if isinstance(value, Quantity):
        return value.nominal
    if hasattr(value, "nominal_value"):
        return value.nominal_value
    return value


def std_dev(value: Any) -> Any:
    if isinstance(value, Quantity):
        return value.u
    if hasattr(value, "std_dev"):
        return value.std_dev
    if isinstance(value, int | float | np.number):
        return 0.0
    return np.zeros_like(np.asarray(value, dtype=float))


def nominal_values(values: Any) -> np.ndarray:
    arr = np.asarray(values, dtype=object)
    return np.vectorize(nominal_value, otypes=[float])(arr)


def std_devs(values: Any) -> np.ndarray:
    arr = np.asarray(values, dtype=object)
    return np.vectorize(std_dev, otypes=[float])(arr)


def _as_quantity_sequence(values: Sequence[Any]) -> list[Quantity] | None:
    seq = list(values)
    if not seq:
        raise ValueError("at least one value is required.")
    quantities = [v for v in seq if isinstance(v, Quantity)]
    if not quantities:
        return None
    reg = quantities[0].registry
    out: list[Quantity] = []
    for value in seq:
        if isinstance(value, Quantity):
            if value.registry is not reg:
                raise ValueError("all quantities must share one atom registry.")
            out.append(value)
        elif isinstance(value, int | float | np.number):
            out.append(Quantity.constant(float(value), registry=reg))
        else:
            return None
    return out


def covariance_matrix(values: Sequence[Any]) -> np.ndarray:
    qseq = _as_quantity_sequence(values)
    if qseq is not None:
        return QuantityVector(qseq).covariance_matrix()
    from uncertainties import covariance_matrix as _uncertainties_covariance_matrix

    return np.asarray(_uncertainties_covariance_matrix(values), dtype=float)


def correlation_matrix(values: Sequence[Any]) -> np.ndarray:
    cov = covariance_matrix(values)
    std = np.sqrt(np.diag(cov))
    outer = np.outer(std, std)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(outer > 0, cov / outer, 0.0)


def correlated_values(
    nom_values: Sequence[float] | np.ndarray,
    covariance_mat: Sequence[Sequence[float]] | np.ndarray,
    *,
    tags: Sequence[str] | None = None,
    labels: Sequence[str] | None = None,
    units: Sequence[str] | str = "",
    registry: AtomRegistry | None = None,
    method: str = "explicit",
) -> list[Quantity]:
    """Create correlated PyTestLab quantities from a covariance matrix."""

    if method != "explicit":
        raise ValueError("Only method='explicit' is currently supported.")
    means = np.asarray(nom_values, dtype=float)
    cov = _validate_covariance_matrix(covariance_mat, means.size)
    unit_list = _unit_list(units, means.size)
    label_list = _label_list(labels or tags, means.size)
    reg = registry or AtomRegistry()
    quantities: list[Quantity] = []
    atom_uids: list[str] = []
    for i, mean in enumerate(means):
        atom = reg.mint(
            nominal=float(mean),
            std_uncertainty=float(np.sqrt(max(cov[i, i], 0.0))),
            label=label_list[i],
            unit=unit_list[i] or None,
            distribution=Distribution.STANDARD,
            key=None,
        )
        atom_uids.append(atom.uid)
        quantities.append(Quantity.from_atom(atom, reg))
    for i in range(means.size):
        for j in range(i + 1, means.size):
            if cov[i, j] != 0.0:
                reg.set_covariance(atom_uids[i], atom_uids[j], float(cov[i, j]))
    return quantities


def correlated_values_norm(
    values_with_std_dev: Sequence[tuple[float, float]],
    correlation_mat: Sequence[Sequence[float]],
    **kwargs: Any,
) -> list[Quantity]:
    values = np.asarray(values_with_std_dev, dtype=float)
    if values.ndim != 2 or values.shape[1] != 2:
        raise ValueError("values_with_std_dev must be a sequence of (nominal, std_dev) pairs.")
    corr = np.asarray(correlation_mat, dtype=float)
    if corr.shape != (values.shape[0], values.shape[0]):
        raise ValueError("correlation matrix shape must match values length.")
    if not np.all(np.isfinite(values)):
        raise ValueError("values_with_std_dev must contain only finite values.")
    if np.any(values[:, 1] < 0.0):
        raise ValueError("standard uncertainties must be non-negative.")
    if not np.allclose(np.diag(corr), 1.0):
        raise ValueError("correlation matrix diagonal must be one.")
    std = values[:, 1]
    cov = corr * np.outer(std, std)
    return correlated_values(values[:, 0], cov, **kwargs)


def from_ufloat(
    value: Any, unit: str = "", *, label: str | None = None, registry: AtomRegistry | None = None
) -> Quantity:
    return uq(
        float(value.nominal_value),
        float(value.std_dev),
        unit,
        label=label or getattr(value, "tag", None),
        registry=registry,
    )


def from_ufloats(
    values: Sequence[Any],
    units: Sequence[str] | str = "",
    *,
    labels: Sequence[str] | None = None,
    registry: AtomRegistry | None = None,
) -> list[Quantity]:
    from uncertainties import covariance_matrix as _uncertainties_covariance_matrix

    seq = list(values)
    noms = [float(v.nominal_value) for v in seq]
    cov = np.asarray(_uncertainties_covariance_matrix(seq), dtype=float)
    return correlated_values(noms, cov, labels=labels, units=units, registry=registry)


def to_ufloat_correlated(
    values: Sequence[Quantity], tags: Sequence[str] | None = None
) -> list[Any]:
    from uncertainties import correlated_values as _uncertainties_correlated_values

    seq = list(values)
    noms = [q.nominal for q in seq]
    cov = covariance_matrix(seq)
    return list(_uncertainties_correlated_values(noms, cov, tags=tags))
