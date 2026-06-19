from __future__ import annotations

from typing import Any

import numpy as np

from ..uncertainty import Quantity
from ..uncertainty import QuantityArray
from ..uncertainty.compat import UFloat
from ..uncertainty.compat import make_ufloat


def serialize_uncertain_value(value: Any) -> tuple[Any, dict[str, Any]]:
    """Convert supported uncertain values into DB-safe data plus metadata."""

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
    if isinstance(value, UFloat):
        return (
            np.array([value.nominal_value, value.std_dev], dtype=np.float64),
            {"value_kind": "ufloat"},
        )
    if _is_ufloat_array(value):
        return _ufloats_to_numpy(value), {
            "value_kind": "ufloat_ndarray",
            "shape": value.shape,
        }
    if _is_ufloat_list(value):
        return _ufloats_to_numpy(value), {"value_kind": "ufloat_list"}
    return value, {}


def deserialize_uncertain_value(value_data: Any, metadata: dict[str, Any]) -> Any:
    """Restore uncertain values serialized by :func:`serialize_uncertain_value`."""

    value_kind = metadata.get("value_kind")
    if value_kind == "quantity":
        quantity_data = metadata.get("quantity")
        if isinstance(quantity_data, dict):
            return Quantity.from_dict(quantity_data)
        return value_data
    if value_kind == "quantity_array":
        qa_data = metadata.get("quantity_array")
        if isinstance(qa_data, dict):
            return QuantityArray.from_dict(qa_data)
        return value_data
    if value_kind == "ufloat":
        values = np.asarray(value_data)
        return make_ufloat(float(values[0]), float(values[1]))
    if value_kind == "ufloat_ndarray":
        values = np.asarray(value_data)
        shape = tuple(metadata.get("shape", values.shape[:-1]))
        restored = np.empty(shape, dtype=object)
        for idx in np.ndindex(restored.shape):
            restored[idx] = make_ufloat(float(values[idx + (0,)]), float(values[idx + (1,)]))
        return restored
    if value_kind == "ufloat_list":
        values = np.asarray(value_data)
        return [make_ufloat(float(nominal), float(sigma)) for nominal, sigma in values]
    return value_data


def _is_ufloat_array(value: Any) -> bool:
    return isinstance(value, np.ndarray) and value.size > 0 and isinstance(value.flat[0], UFloat)


def _is_ufloat_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and isinstance(value[0], UFloat)


def _ufloats_to_numpy(value: Any) -> np.ndarray:
    arr = np.asarray(value, dtype=object)
    nominal = np.vectorize(lambda item: item.nominal_value, otypes=[float])(arr)
    sigma = np.vectorize(lambda item: item.std_dev, otypes=[float])(arr)
    return np.stack((nominal, sigma), axis=-1).astype(np.float64)
