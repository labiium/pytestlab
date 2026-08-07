from __future__ import annotations

import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any
from typing import TypeGuard
from typing import cast
from typing import overload

import numpy as np
import polars as pl
from numpy.typing import NDArray

from ..uncertainty import Quantity as MeasurementQuantity
from ..uncertainty import QuantityArray as MeasurementQuantityArray
from .uncertainty_serialization import deserialize_uncertain_value
from .uncertainty_serialization import serialize_uncertain_value

if TYPE_CHECKING:
    from ..plotting import PlotSpec


def _is_quantity_array(value: Any) -> TypeGuard[np.ndarray]:
    return (
        isinstance(value, np.ndarray)
        and value.size > 0
        and all(isinstance(item, MeasurementQuantity) for item in value.flat)
    )


def _is_quantity_list(value: Any) -> TypeGuard[list[MeasurementQuantity]]:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, MeasurementQuantity) for item in value)
    )


class MeasurementResult:  # noqa: D101
    """A class to represent a collection of measurement values.

    Attributes:
        values (Union[np.ndarray, pl.DataFrame, np.float64, TypingList[Any], MeasurementQuantity]): The measurement data.
        units (str): The units of the measurements.
        instrument (str): The name of the instrument used for the measurements.
        measurement_type (str): The type of measurement.
        timestamp (float): Timestamp of when the result was created.
    """

    @overload
    def __init__(
        self,
        values: float,
        instrument: str,
        units: str,
        measurement_type: str,
        timestamp: float | None = ...,
        envelope: dict[str, Any] | None = ...,
        sampling_rate: float | None = ...,
        **kwargs: Any,
    ) -> None: ...
    @overload
    def __init__(
        self,
        values: np.ndarray
        | pl.DataFrame
        | np.float64
        | list[Any]
        | MeasurementQuantity
        | MeasurementQuantityArray,
        instrument: str,
        units: str,
        measurement_type: str,
        timestamp: float | None = ...,
        envelope: dict[str, Any] | None = ...,
        sampling_rate: float | None = ...,
        **kwargs: Any,
    ) -> None: ...
    def __init__(
        self,
        values: np.ndarray
        | pl.DataFrame
        | np.float64
        | list[Any]
        | MeasurementQuantity
        | MeasurementQuantityArray
        | float,
        instrument: str,
        units: str,
        measurement_type: str,
        timestamp: float | None = None,  # Allow optional timestamp override
        envelope: dict[str, Any] | None = None,  # Add envelope as an explicit argument
        sampling_rate: float | None = None,  # Add sampling_rate for FFT
        **kwargs: Any,
    ) -> None:  # Added **kwargs and type hint
        if isinstance(values, int | float | np.integer | np.floating):
            # Normalize Python and NumPy numeric scalars for one extraction contract.
            values = np.float64(values)
        self.values: (
            np.ndarray
            | pl.DataFrame
            | np.float64
            | list[Any]
            | MeasurementQuantity
            | MeasurementQuantityArray
        ) = cast(
            np.ndarray
            | pl.DataFrame
            | np.float64
            | list[Any]
            | MeasurementQuantity
            | MeasurementQuantityArray,
            values,
        )
        self.units: str = units
        self.instrument: str = instrument
        self.measurement_type: str = measurement_type
        self.timestamp: float = timestamp if timestamp is not None else time.time()
        # Envelope logic: always provide an envelope attribute
        if envelope is not None:
            self.envelope = envelope
        else:
            # Default: minimal valid envelope (empty dict, or customize as needed)
            self.envelope = {}

        # Store sampling rate for FFT calculations
        self.sampling_rate = sampling_rate

        # Store any additional kwargs as attributes
        for key, value in kwargs.items():
            setattr(self, key, value)

    def __str__(self) -> str:
        """String representation of the measurement result.

        For backward compatibility with tests, returns a newline-separated list for arrays.
        For other types, uses a more descriptive representation.
        """
        if isinstance(self.values, MeasurementQuantity | MeasurementQuantityArray):
            return f"{self.values}"
        if isinstance(self.values, np.float64):
            return f"{self.values} {self.units}"
        elif isinstance(self.values, pl.DataFrame):
            return str(self.values)
        elif isinstance(self.values, np.ndarray):
            # For numpy arrays, handle 1D arrays specially for backward compatibility
            if self.values.ndim == 1:
                return "\n".join([f"{val} {self.units}" for val in self.values])
            # For multi-dimensional arrays, provide a concise representation
            return (
                f"NumPy Array (shape: {self.values.shape}, dtype: {self.values.dtype}) {self.units}"
            )
        elif isinstance(self.values, list):
            # For lists, special handling for backward compatibility
            if all(isinstance(x, int | float) for x in self.values):
                return "\n".join([f"{val} {self.units}" for val in self.values])
            # For lists with mixed types or nested lists, show first few items if long
            if len(self.values) > 5:
                return f"List (first 5 of {len(self.values)}): {self.values[:5]}... {self.units}"
            return f"List: {self.values} {self.units}"

        # Fallback for other types
        return f"Values: {str(self.values)[:100]}... Type: {type(self.values)} {self.units}"

    def __repr__(self) -> str:
        """Detailed representation of the measurement result.

        For backward compatibility with tests, this matches __str__ behavior.
        In typical libraries, repr would show construction details instead.
        """
        return self.__str__()

    def _scalar_nominal(self) -> float:
        """Return one nominal scalar or reject an ambiguous result shape."""
        nominal = self.nominal
        if isinstance(nominal, int | float | np.integer | np.floating):
            return float(nominal)
        raise TypeError(
            "numeric conversion of MeasurementResult requires a scalar result; "
            "use .values or .nominal for non-scalar measurements"
        )

    def __float__(self) -> float:
        """Return the nominal value when this result contains one scalar."""

        return self._scalar_nominal()

    def __int__(self) -> int:
        """Return the scalar nominal value as an integer."""

        return int(self._scalar_nominal())

    def __format__(self, spec: str) -> str:
        """Format a scalar result without discarding explicit uncertainty formats."""

        if "u" in spec and isinstance(self.values, MeasurementQuantity):
            return format(self.values, spec)
        return format(self._scalar_nominal(), spec)

    def __round__(self, ndigits: int | None = None) -> int | float:
        """Round the scalar nominal value."""

        return round(self._scalar_nominal(), ndigits)

    def __abs__(self) -> float:
        """Return the absolute scalar nominal value."""

        return abs(self._scalar_nominal())

    def to_json_value(self) -> float:
        """Return a JSON-compatible scalar nominal value.

        Use :meth:`to_dict` instead when units and uncertainty metadata must be
        retained.
        """

        return self._scalar_nominal()

    # Add this method to convert MeasurementResult to a dict for Polars DataFrame
    def to_dict(self) -> dict[str, Any]:
        """Convert MeasurementResult to a dict for DataFrame conversion.

        This allows MeasurementResult objects to be directly used in Experiment.add_trial.
        """
        if isinstance(self.values, pl.DataFrame):
            # If values is already a DataFrame, convert to dict representation
            result = {}
            for col in self.values.columns:
                result[col] = self.values[col].to_list()
            return result
        elif isinstance(self.values, np.ndarray | list):
            # Convert array or list to a dict with a 'values' key
            return {"values": self.values}
        elif isinstance(self.values, MeasurementQuantity):
            return {
                "value": self.values.nominal,
                "unit": self.values.unit,
                "uncertainty": self.values.to_dict(),
            }
        elif isinstance(self.values, MeasurementQuantityArray):
            return {
                "values": self.values.nominal,
                "unit": self.values.unit,
                "uncertainty": self.values.to_dict(),
            }
        elif isinstance(self.values, np.float64 | MeasurementQuantity):
            # Convert scalar value to a dict with a 'value' key
            return {"value": self.values}
        else:
            # Default fallback
            return {"values": self.values}

    # Make the object dict-like so it can be used in Polars DataFrame constructor
    def keys(self):
        """Return the keys for dict-like behavior."""
        return self.to_dict().keys()

    def __getitem__(self, key):
        """Allow dictionary-style access or integer indexing into values."""
        if isinstance(self.values, MeasurementQuantityArray) and isinstance(key, int | slice):
            return self.values[key]
        if isinstance(key, int):
            if isinstance(self.values, np.ndarray | list):
                return self.values[key]
            if isinstance(self.values, pl.DataFrame):
                return self.values[key]
            if (
                isinstance(
                    self.values,
                    (np.float64 | MeasurementQuantity),
                )
                and key == 0
            ):
                return self.values
            raise IndexError(
                f"Index {key} out of range or type {type(self.values)} not directly indexable."
            )
        return self.to_dict()[key]

    def items(self):
        """Return items for dict-like behavior."""
        return self.to_dict().items()

    def save(self, path: str) -> None:
        """Saves the measurement data to a file.

        Uncertain values use a self-describing NPZ representation that retains
        the complete uncertainty model, provenance, units, and result metadata.
        If the data is a numpy array, it will be saved as a .npy file.
        If the data is a Polars DataFrame, it will be saved as a .parquet file.
        Other list-like data will be converted to numpy array and saved as .npy.
        np.float64 will be saved as a 0-D numpy array.
        """
        serialized_values, uncertainty_metadata = serialize_uncertain_value(self.values)
        default_ext = ".npz" if uncertainty_metadata else ".npy"
        if isinstance(self.values, pl.DataFrame):
            default_ext = ".parquet"

        if not path.endswith((".npy", ".parquet", ".npz")):
            path += default_ext
            print(f"Warning: File extension not specified. Saving as {path}")

        if uncertainty_metadata:
            if not path.endswith(".npz"):
                raise ValueError(
                    "Uncertain MeasurementResult values must be saved as .npz "
                    "so metrology metadata is not discarded."
                )
            metadata = {
                "schema_version": "1.0",
                "instrument": self.instrument,
                "units": self.units,
                "measurement_type": self.measurement_type,
                "timestamp": self.timestamp,
                "envelope": self.envelope,
                "sampling_rate": self.sampling_rate,
                "uncertainty": uncertainty_metadata,
                "extra_attributes": {
                    key: value
                    for key, value in self.__dict__.items()
                    if key
                    not in {
                        "values",
                        "instrument",
                        "units",
                        "measurement_type",
                        "timestamp",
                        "envelope",
                        "sampling_rate",
                    }
                },
            }
            np.savez_compressed(
                path,
                values=np.asarray(serialized_values),
                metadata_json=np.asarray(json.dumps(metadata, sort_keys=True)),
            )
        elif isinstance(self.values, np.ndarray):
            np.save(path, self.values)
        elif isinstance(self.values, pl.DataFrame):
            if not path.endswith(".parquet"):
                print(
                    f"Warning: Saving Polars DataFrame to non-parquet file '{path}'. Consider using .parquet for DataFrames."
                )
            self.values.write_parquet(path)
        elif isinstance(self.values, list | np.float64):  # Convert list or float64 to ndarray
            if not path.endswith(".npy"):
                print(
                    f"Warning: Saving {type(self.values).__name__} to non-npy file '{path}'. Consider using .npy."
                )
            np.save(path, np.array(self.values))
        else:
            raise TypeError(
                f"Unsupported data type for saving: {type(self.values)}. Can save np.ndarray, pl.DataFrame, list, np.float64, MeasurementQuantity, or MeasurementQuantityArray."
            )
        print(f"Measurement saved to {path}")

    @classmethod
    def load(cls, path: str | Path) -> MeasurementResult:
        """Load a self-describing uncertain result written by :meth:`save`."""

        path = Path(path)
        if path.suffix != ".npz":
            raise ValueError("MeasurementResult.load() requires a self-describing .npz file.")
        with np.load(path, allow_pickle=False) as archive:
            if "metadata_json" not in archive:
                raise ValueError("NPZ file does not contain MeasurementResult metadata.")
            metadata = json.loads(str(archive["metadata_json"].item()))
            values = deserialize_uncertain_value(
                np.asarray(archive["values"]),
                metadata.get("uncertainty", {}),
                unit=metadata.get("units", ""),
            )
        return cls(
            values=values,
            instrument=metadata["instrument"],
            units=metadata["units"],
            measurement_type=metadata["measurement_type"],
            timestamp=float(metadata["timestamp"]),
            envelope=metadata.get("envelope") or {},
            sampling_rate=metadata.get("sampling_rate"),
            **metadata.get("extra_attributes", {}),
        )

    @property
    def nominal(
        self,
    ) -> float | np.ndarray | pl.DataFrame:  # return type explicitly includes built-in float
        if isinstance(self.values, MeasurementQuantity):
            return self.values.nominal
        if isinstance(self.values, MeasurementQuantityArray):
            return self.values.nominal
        if _is_quantity_array(self.values):
            values = self.values
            return np.array([x.nominal for x in values.flat]).reshape(values.shape)
        if isinstance(self.values, pl.DataFrame | np.ndarray):
            return self.values
        if isinstance(self.values, np.float64):
            return float(self.values)
        if isinstance(self.values, list):
            if _is_quantity_list(self.values):
                return np.asarray([value.nominal for value in self.values])
            if all(isinstance(value, int | float | np.number) for value in self.values):
                return np.asarray(self.values)
        raise TypeError(f"Unsupported type for nominal: {type(self.values)}")

    @property
    def sigma(
        self,
    ) -> float | np.ndarray | pl.DataFrame | None:  # return type explicitly includes built-in float
        if isinstance(self.values, MeasurementQuantity):
            return self.values.u
        if isinstance(self.values, MeasurementQuantityArray):
            return self.values.u
        if _is_quantity_array(self.values):
            values = self.values
            return np.array([x.u for x in values.flat]).reshape(values.shape)
        if _is_quantity_list(self.values):
            values = self.values
            return np.asarray([value.u for value in values])
        return None  # Or handle DataFrame case

    # Removed duplicate __repr__ (original definition earlier retained)

    def add(self, value: Any) -> None:
        """Adds a new value to the collection. Behavior depends on self.values type."""
        if isinstance(self.values, np.ndarray):
            # This might be inefficient for frequent additions. Consider list then convert.
            self.values = np.append(self.values, value)
        elif isinstance(self.values, list):
            self.values.append(value)
        elif isinstance(self.values, np.float64):
            # Convert to list or ndarray if adding to a single float
            self.values = np.array([self.values, value])
            print("Warning: Added value to np.float64, converted 'values' to np.ndarray.")
        elif isinstance(self.values, MeasurementQuantity):
            self.values = [self.values, value]
            print(
                "Warning: Added value to MeasurementQuantity, converted 'values' to a list. Consider using a list initially."
            )
        elif isinstance(self.values, pl.DataFrame):
            # Appending to Polars DataFrame is complex; typically done by creating a new DF and vstacking.
            # This simple 'add' might not be suitable.
            raise NotImplementedError(
                "Direct 'add' to Polars DataFrame not supported. Use 'set_values' or manage DataFrame externally."
            )
        else:
            raise TypeError(f"Cannot 'add' to type {type(self.values)}")

    def set_values(
        self,
        values: np.ndarray
        | pl.DataFrame
        | np.float64
        | list[Any]
        | MeasurementQuantity
        | MeasurementQuantityArray
        | float,
    ) -> None:
        """Sets the MeasurementValues in the collection."""
        if isinstance(values, float) and not isinstance(values, np.floating):
            values = np.float64(values)
        self.values = cast(
            np.ndarray
            | pl.DataFrame
            | np.float64
            | list[Any]
            | MeasurementQuantity
            | MeasurementQuantityArray,
            values,
        )

    def get(self, index: int) -> Any:
        """Gets the MeasurementValue at a specified index. Assumes indexable values."""
        if isinstance(self.values, MeasurementQuantityArray):
            return self.values[index]
        if isinstance(self.values, np.ndarray | list):
            return self.values[index]
        elif isinstance(self.values, pl.DataFrame):
            # For DataFrame, 'get' by index might mean row.
            # This returns a new DataFrame with one row.
            return self.values[index]
        elif isinstance(self.values, (np.float64 | MeasurementQuantity)) and index == 0:
            return self.values
        raise IndexError(
            f"Index {index} out of range or type {type(self.values)} not directly indexable by single int."
        )

    def get_all(
        self,
    ) -> (
        np.ndarray
        | pl.DataFrame
        | np.float64
        | list[Any]
        | MeasurementQuantity
        | MeasurementQuantityArray
    ):
        """Returns all the MeasurementValues in the collection."""
        return self.values

    def clear(self) -> None:
        """Clears all the MeasurementValues from the collection, resetting to an empty/default state."""
        if isinstance(self.values, np.ndarray):
            self.values = np.array([])
        elif isinstance(self.values, (np.float64 | MeasurementQuantity)):
            self.values = np.float64(0.0)
        elif isinstance(self.values, pl.DataFrame):
            self.values = pl.DataFrame()
        elif isinstance(self.values, list):
            self.values = []
        else:  # Fallback for unknown types, attempt to set to a default float64
            print(
                f"Warning: Clearing unknown type {type(self.values)}, setting to np.float64(0.0)."
            )
            self.values = np.float64(0.0)

    def _to_numpy(self) -> np.ndarray:
        """
        Converts the measurement values to a numpy array if possible.
        For native uncertain values, it converts to [nominal, standard-uncertainty]
        pairs.
        """
        if isinstance(self.values, np.ndarray):
            if _is_quantity_array(self.values):
                return np.array([[x.nominal, x.u] for x in self.values.flat]).reshape(
                    self.values.shape + (2,)
                )
            return self.values
        elif isinstance(self.values, pl.DataFrame):
            # DataFrames are converted directly; native uncertainty metadata is
            # retained by the structured MeasurementResult persistence path.
            return self.values.to_numpy()
        elif isinstance(self.values, MeasurementQuantity):
            return np.array([self.values.nominal, self.values.u])
        elif isinstance(self.values, MeasurementQuantityArray):
            return np.column_stack((self.values.nominal, self.values.u))
        elif isinstance(self.values, list):
            if _is_quantity_list(self.values):
                return np.array([[x.nominal, x.u] for x in self.values])
            return np.array(self.values)
        elif isinstance(self.values, np.float64):
            return np.array(self.values)
        else:
            raise TypeError(f"Cannot convert type {type(self.values)} to NumPy array.")

    def __len__(self) -> int:
        if isinstance(self.values, np.ndarray | list | MeasurementQuantityArray):
            return len(self.values)
        elif isinstance(self.values, np.float64 | MeasurementQuantity):
            return 1
        elif isinstance(self.values, pl.DataFrame):
            return self.values.height  # Number of rows
        return 0  # Default for unknown types

    # Removed duplicate __getitem__ (logic merged into earlier __getitem__)

    def __iter__(self) -> Iterator[Any]:
        """Allows iteration over the 'values' attribute."""
        if isinstance(self.values, MeasurementQuantityArray):
            return (self.values[index] for index in range(len(self.values)))
        if isinstance(self.values, np.ndarray | list):
            return iter(self.values)
        elif isinstance(self.values, pl.DataFrame):
            return iter(self.values.iter_rows())
        elif isinstance(self.values, np.float64 | MeasurementQuantity):
            return iter([self.values])
        raise TypeError(f"Iteration not supported for type {type(self.values)}")

    def __delitem__(self, index: int) -> None:
        """Allows deleting an item from 'values' if it's a list or ndarray."""
        if isinstance(self.values, list):
            del self.values[index]
        elif isinstance(self.values, np.ndarray):
            self.values = np.delete(self.values, index, axis=0)
        else:
            raise TypeError(f"Deletion by index not supported for type {type(self.values)}")

    def perform_fft(self) -> MeasurementResult:
        """Perform Fast Fourier Transform on the measurement data.

        Requires:
        - self.values to be a numpy array of time-domain data
        - self.sampling_rate to be set (in Hz)

        Returns:
            A new MeasurementResult containing the FFT data, with frequency in Hz
            and magnitude in the same units as the original data.
        """
        if self.sampling_rate is None:
            raise ValueError("Sampling rate must be set to perform FFT")

        if not isinstance(self.values, np.ndarray):
            raise TypeError(f"FFT requires numpy array, got {type(self.values)}")

        # Ensure we're working with a 1D array
        values_arr = cast(NDArray[np.generic], self.values)
        values = values_arr.flatten() if values_arr.ndim > 1 else values_arr

        # Perform FFT
        fft_values = np.fft.rfft(values)
        fft_magnitude = np.abs(fft_values)

        # Create frequency axis
        freqs = np.fft.rfftfreq(len(values), 1 / self.sampling_rate)

        # Create result with frequency and magnitude
        result_df = pl.DataFrame({"frequency": freqs, "magnitude": fft_magnitude})

        return MeasurementResult(
            values=result_df,
            instrument=self.instrument,
            units=self.units,
            measurement_type="FFT",
            timestamp=time.time(),
            original_type=self.measurement_type,
            sampling_rate=self.sampling_rate,
        )

    # ------------------------------------------------------------------
    # Plotting convenience
    def plot(self, spec: PlotSpec | None = None, **kwargs: Any) -> Any:
        """
        Plot this measurement result.

        - If values is a Polars DataFrame, plots columns per PlotSpec.
        - If values is a 1D numpy array, uses plot_ndarray; honors sampling_rate and units.
        - If values is a scalar/list, attempts to plot as 1D series.

        Args:
            spec: Optional PlotSpec. If not provided, built from kwargs.
            **kwargs: Fields for PlotSpec.

        Returns:
            A matplotlib Figure object.
        """
        import numpy as np  # local import
        import polars as pl  # local import

        from ..plotting import PlotSpec  # noqa: E402
        from ..plotting import plot_dataframe  # noqa: E402
        from ..plotting import plot_ndarray  # noqa: E402

        pspec = spec or (PlotSpec(**kwargs) if kwargs else PlotSpec())

        if isinstance(self.values, pl.DataFrame):
            # If ylabel not provided and a single numeric y is chosen, prefer units
            if pspec.ylabel is None:
                try:
                    # The helper will set y label to the series name by default; we can override
                    pspec = PlotSpec(
                        kind=pspec.kind,
                        title=pspec.title or self.measurement_type,
                        x=pspec.x,
                        y=pspec.y,
                        xlabel=pspec.xlabel,
                        ylabel=self.units if self.units else pspec.ylabel,
                        legend=pspec.legend,
                        grid=pspec.grid,
                    )
                except Exception:
                    pass
            return plot_dataframe(self.values, pspec)

        # Convert scalar/list to numpy array for plotting
        arr: np.ndarray
        if isinstance(self.values, np.ndarray):
            arr = self.values
        elif isinstance(self.values, list):
            arr = np.asarray(self.values)
        else:
            arr = np.asarray([self.values])

        if arr.ndim != 1:
            raise ValueError("Only 1D arrays are supported for simple plotting in Phase 1.")

        title = pspec.title or self.measurement_type
        pspec = PlotSpec(
            kind=pspec.kind,
            title=title,
            x=pspec.x,
            y=pspec.y,
            xlabel=pspec.xlabel,
            ylabel=self.units or pspec.ylabel,
            legend=pspec.legend,
            grid=pspec.grid,
        )
        return plot_ndarray(arr, pspec, sampling_rate=self.sampling_rate, units=self.units)
