"""Shared typed trial storage used by sessions and direct native trials."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from typing import Any
from typing import TypeGuard

import numpy as np
import polars as pl

from .results import MeasurementResult
from .results import NativeMeasurementResult
from .results import coerce_measurement_result
from .uncertainty_serialization import serialize_uncertain_value

if TYPE_CHECKING:
    from polars.datatypes import DataTypeClass


def _is_numeric_vector(value: Any) -> TypeGuard[np.ndarray]:
    # Polars has no corresponding native dtype for half/extended precision
    # or complex NumPy arrays. Do not coerce them to a different type here.
    return (
        isinstance(value, np.ndarray)
        and value.ndim == 1
        and (
            (value.dtype.kind in "biu" and value.dtype.itemsize <= 8)
            or (value.dtype.kind == "f" and value.dtype.itemsize in {4, 8})
        )
    )


def _contains_object(dtype: pl.DataType | DataTypeClass) -> bool:
    if isinstance(dtype, pl.List | pl.Array):
        return _contains_object(dtype.inner)
    if isinstance(dtype, pl.Struct):
        return any(_contains_object(field.dtype) for field in dtype.fields)
    return dtype == pl.Object


def pack_samples(name: str, value: Any) -> pl.Series | None:
    if isinstance(value, np.ma.MaskedArray):
        raise ValueError(
            f"Measurement '{name}' uses a NumPy masked array. "
            "Use a typed Polars table with nulls for masked samples."
        )
    if isinstance(value, pl.DataFrame):
        if not value.width:
            raise ValueError(f"Measurement '{name}' needs a table with at least one column.")
        if any(_contains_object(dtype) for dtype in value.dtypes):
            raise ValueError(
                f"Measurement '{name}' table contains a Polars Object column. "
                "Use Arrow-compatible sample columns to save the measurement."
            )
        return value.to_struct(name).implode()
    if _is_numeric_vector(value):
        native = value if value.dtype.isnative else value.astype(value.dtype.newbyteorder("="))
        return pl.Series(name, native).implode()
    return None


def store_measurement_value(row: dict[str, Any], column: str, value: Any) -> None:
    """Keep numeric columns usable while retaining full metrology metadata."""

    result_metadata: dict[str, Any] | None = None
    raw_value = value
    result = coerce_measurement_result(value)
    if result is not None:
        value = result
        raw_value = result.values
        result_metadata = {
            "instrument": value.instrument,
            "units": value.units,
            "measurement_type": value.measurement_type,
            "timestamp": value.timestamp,
            "envelope": value.envelope,
            "sampling_rate": value.sampling_rate,
        }
        if isinstance(value, NativeMeasurementResult):
            result_metadata["native_capture"] = True

    serialized, uncertainty_metadata = serialize_uncertain_value(raw_value)
    value_kind = uncertainty_metadata.get("value_kind")
    if value_kind == "quantity":
        row[column] = float(np.asarray(serialized).flat[0])
    elif value_kind == "quantity_array":
        row[column] = np.asarray(serialized).tolist()
    elif value_kind in {"quantity_ndarray", "quantity_list"}:
        row[column] = np.asarray(serialized)[..., 0].tolist()
    elif isinstance(serialized, pl.DataFrame):
        row[column] = serialized.clone()
    elif _is_numeric_vector(serialized):
        row[column] = serialized.copy()
    else:
        row[column] = serialized

    if uncertainty_metadata or result_metadata is not None:
        row[f"{column}__measurement"] = json.dumps(
            {
                "schema_version": "1.0",
                "result": result_metadata,
                "uncertainty": uncertainty_metadata,
            },
            sort_keys=True,
            default=str,
        )


def native_trial_frame(result: MeasurementResult) -> pl.DataFrame:
    """Encode one native capture as one trial without flattening its samples."""
    row: dict[str, Any] = {}
    store_measurement_value(row, "result", result)
    samples = pack_samples("result", row["result"])
    columns = {name: [value] for name, value in row.items()}
    if samples is None:
        return pl.DataFrame(columns)
    del columns["result"]
    return pl.DataFrame([samples, *[pl.Series(name, value) for name, value in columns.items()]])
