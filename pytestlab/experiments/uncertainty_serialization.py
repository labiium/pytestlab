from __future__ import annotations

from typing import Any

import numpy as np

from ..uncertainty import Quantity
from ..uncertainty import QuantityArray
from ..uncertainty import uq
from ..uncertainty.atoms import AtomRegistry

_LEGACY_VALUE_KINDS = frozenset({"ufloat", "ufloat_ndarray", "ufloat_list"})
_NATIVE_SEQUENCE_KINDS = frozenset({"quantity_ndarray", "quantity_list"})


def serialize_uncertain_value(value: Any) -> tuple[Any, dict[str, Any]]:
    """Convert native uncertain values into database-safe data and metadata."""

    if isinstance(value, Quantity):
        return (
            np.array([value.nominal, value.u], dtype=np.float64),
            {"value_kind": "quantity", "quantity": value.to_dict()},
        )
    if isinstance(value, QuantityArray):
        return (
            np.asarray(value.nominal, dtype=np.float64),
            {"value_kind": "quantity_array", "quantity_array": value.to_dict()},
        )
    if _is_quantity_array(value):
        return _serialize_quantity_sequence(value, value_kind="quantity_ndarray")
    if _is_quantity_list(value):
        return _serialize_quantity_sequence(value, value_kind="quantity_list")
    return value, {}


def deserialize_uncertain_value(
    value_data: Any,
    metadata: dict[str, Any],
    *,
    unit: str = "",
) -> Any:
    """Restore native uncertain values, including old serialized payloads.

    Older database and NPZ records may contain nominal/standard-uncertainty
    pairs tagged with the historical ``ufloat`` value kinds.  Those payloads
    are migrated directly into PyTestLab ``Quantity`` objects without loading
    the third-party package.
    """

    value_kind = metadata.get("value_kind")
    if value_kind == "quantity":
        quantity_data = metadata.get("quantity")
        if isinstance(quantity_data, dict):
            return Quantity.from_dict(quantity_data)
        return value_data
    if value_kind == "quantity_array":
        quantity_array_data = metadata.get("quantity_array")
        if isinstance(quantity_array_data, dict):
            return QuantityArray.from_dict(quantity_array_data)
        return value_data
    if value_kind in _NATIVE_SEQUENCE_KINDS:
        return _restore_quantity_sequence(
            value_data,
            metadata,
            value_kind=value_kind,
            unit=unit,
        )
    if value_kind in _LEGACY_VALUE_KINDS:
        return _migrate_legacy_payload(value_data, metadata, unit=unit)
    return value_data


def _is_quantity_array(value: Any) -> bool:
    return (
        isinstance(value, np.ndarray)
        and value.size > 0
        and all(isinstance(item, Quantity) for item in value.flat)
    )


def _is_quantity_list(value: Any) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, Quantity) for item in value)
    )


def _serialize_quantity_sequence(
    value: list[Quantity] | np.ndarray,
    *,
    value_kind: str,
) -> tuple[np.ndarray, dict[str, Any]]:
    quantities = list(np.asarray(value, dtype=object).flat)
    nominal = np.asarray([quantity.nominal for quantity in quantities], dtype=np.float64)
    standard_uncertainty = np.asarray([quantity.u for quantity in quantities], dtype=np.float64)
    payload = np.stack((nominal, standard_uncertainty), axis=-1)
    return payload, {
        "value_kind": value_kind,
        "shape": list(np.asarray(value, dtype=object).shape),
        "quantities": [quantity.to_dict() for quantity in quantities],
        "covariances": _shared_covariances(quantities),
    }


def _shared_covariances(quantities: list[Quantity]) -> list[list[str | float]]:
    if not quantities or any(
        quantity.registry is not quantities[0].registry for quantity in quantities
    ):
        return []
    uids = {uid for quantity in quantities for uid in quantity.grad}
    return [
        [first, second, covariance]
        for (first, second), covariance in quantities[0].registry._covariances.items()
        if first in uids and second in uids
    ]


def _restore_quantity_sequence(
    value_data: Any,
    metadata: dict[str, Any],
    *,
    value_kind: str,
    unit: str,
) -> list[Quantity] | np.ndarray:
    values = np.asarray(value_data, dtype=float)
    shape = tuple(metadata.get("shape", values.shape[:-1]))
    quantity_data = metadata.get("quantities")
    if isinstance(quantity_data, list) and len(quantity_data) == int(np.prod(shape)):
        registry = AtomRegistry()
        quantities = [
            Quantity.from_dict(item, registry) for item in quantity_data if isinstance(item, dict)
        ]
        if len(quantities) == len(quantity_data):
            for first, second, covariance in metadata.get("covariances", []):
                registry.set_covariance(first, second, float(covariance))
            if value_kind == "quantity_list":
                return quantities
            return np.asarray(quantities, dtype=object).reshape(shape)

    if values.ndim < 2 or values.shape[-1] != 2:
        raise ValueError(
            "native quantity sequence payload must end with nominal/standard-uncertainty pairs"
        )
    nominal = values[..., 0].reshape(shape)
    standard_uncertainty = values[..., 1].reshape(shape)
    if value_kind == "quantity_list":
        return [
            _native_quantity(
                float(nominal[index]),
                float(standard_uncertainty[index]),
                unit=unit,
            )
            for index in np.ndindex(nominal.shape)
        ]
    return _native_quantity_array(nominal, standard_uncertainty, unit=unit)


def _migrate_legacy_payload(value_data: Any, metadata: dict[str, Any], *, unit: str) -> Any:
    values = np.asarray(value_data, dtype=float)
    value_kind = metadata.get("value_kind")
    if value_kind == "ufloat":
        flat = values.reshape(-1)
        if flat.size < 2:
            raise ValueError(
                "legacy scalar uncertainty payload must contain nominal and standard uncertainty"
            )
        return _native_quantity(float(flat[0]), float(flat[1]), unit=unit)

    if values.ndim < 2 or values.shape[-1] != 2:
        raise ValueError(
            "legacy array uncertainty payload must end with nominal/standard-uncertainty pairs"
        )
    nominal = values[..., 0]
    standard_uncertainty = values[..., 1]
    shape = tuple(metadata.get("shape", nominal.shape))
    nominal = nominal.reshape(shape)
    standard_uncertainty = standard_uncertainty.reshape(shape)

    if value_kind == "ufloat_list":
        return [
            _native_quantity(float(nominal[index]), float(standard_uncertainty[index]), unit=unit)
            for index in np.ndindex(nominal.shape)
        ]
    if value_kind == "ufloat_ndarray":
        return _native_quantity_array(nominal, standard_uncertainty, unit=unit)
    raise ValueError(f"unsupported legacy uncertainty value kind: {value_kind!r}")


def _native_quantity(nominal: float, standard_uncertainty: float, *, unit: str) -> Quantity:
    return uq(
        nominal,
        standard_uncertainty,
        unit,
        label="migrated legacy uncertainty",
        source="migrated legacy uncertainty",
    )


def _native_quantity_array(
    nominal: np.ndarray,
    standard_uncertainty: np.ndarray,
    *,
    unit: str,
) -> np.ndarray:
    registry = AtomRegistry()
    restored = np.empty(nominal.shape, dtype=object)
    for index in np.ndindex(nominal.shape):
        restored[index] = uq(
            float(nominal[index]),
            float(standard_uncertainty[index]),
            unit,
            label="migrated legacy uncertainty",
            source="migrated legacy uncertainty",
            registry=registry,
        )
    return restored
