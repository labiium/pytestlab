from __future__ import annotations

import json
import math
from collections.abc import Iterator
from collections.abc import Mapping
from collections.abc import Sequence
from typing import TYPE_CHECKING
from typing import Any
from typing import cast
from typing import overload

import polars as pl

from .result_storage import native_trial_frame
from .results import MeasurementResult
from .results import NativeMeasurementResult
from .results import SupportsMeasurementResult
from .results import coerce_measurement_result
from .results import is_native_measurement_result
from .uncertainty_serialization import deserialize_uncertain_value

if TYPE_CHECKING:
    from ..plotting import PlotSpec


class ExperimentParameter:
    """Represents a single experiment parameter."""

    def __init__(self, name: str, units: str, notes: str = "") -> None:
        self.name: str = name
        self.units: str = units
        self.notes: str = notes

    def __str__(self) -> str:
        return f"{self.name} ({self.units})"


class Experiment:
    """
    Experiment tracker to store measurements and parameters.

    This class maintains an internal Polars DataFrame (self.data) for trial data, regardless
    of whether the input is provided as a Polars DataFrame, dict, or list.

    It provides two export functionalities:
      - save_parquet(file_path): Saves the internal data as a Parquet file.

    Additionally, printing the Experiment instance (via __str__) shows a
    summary and the head (first few rows) of the data.
    """

    def __init__(self, name: str, description: str = "", notes: str = "") -> None:
        self.name: str = name
        self.description: str = description
        self.notes: str = notes
        self.parameters: dict[str, ExperimentParameter] = {}
        self.data: pl.DataFrame = pl.DataFrame()

    def add_parameter(self, name: str, units: str, notes: str = "") -> None:
        """
        Add a new parameter to the experiment.

        Args:
            name (str): Name of the parameter.
            units (str): Units for the parameter.
            notes (str, optional): Additional notes.
        """
        self.parameters[name] = ExperimentParameter(name, units, notes)

    def add_trial(
        self,
        measurement_result: pl.DataFrame
        | dict[str, Any]
        | list[Any]
        | MeasurementResult
        | SupportsMeasurementResult,
        **parameter_values: Any,
    ) -> None:
        """
        Add a new trial to the experiment.

        Accepts measurement data in various formats (list, dict, Polars DataFrame, or MeasurementResult)
        and converts it into a Polars DataFrame if needed. A native instrument result
        occupies one trial row with samples in "result" and its envelope in
        "result__measurement". Additional parameter values are added as new columns.

        Args:
            measurement_result (Union[pl.DataFrame, Dict[str, Any], List[Any], MeasurementResult]): The measurement data.
            **parameter_values: Additional parameters to include with this trial.

        Raises:
            ValueError: If the conversion to a Polars DataFrame fails or if a
                        provided parameter is not defined.
        """
        trial_df: pl.DataFrame

        native = (
            coerce_measurement_result(measurement_result)
            if is_native_measurement_result(measurement_result)
            else None
        )
        if native is not None:
            trial_df = native_trial_frame(native)
        # Preserve the historical shape for direct MeasurementResult inputs.
        elif hasattr(measurement_result, "values") and hasattr(measurement_result, "to_dict"):
            # If it's a MeasurementResult, extract its values
            if isinstance(measurement_result.values, pl.DataFrame):
                trial_df = measurement_result.values
            else:
                # Convert to dict and then to DataFrame
                try:
                    to_dict_fn = getattr(measurement_result, "to_dict", None)
                    if not callable(to_dict_fn):
                        raise TypeError("MeasurementResult.to_dict is not callable")
                    trial_df = pl.DataFrame(to_dict_fn(), strict=False)
                except Exception as e:
                    raise ValueError(
                        f"Failed to convert MeasurementResult to DataFrame: {e}"
                    ) from e
        elif not isinstance(measurement_result, pl.DataFrame):
            try:
                trial_df = pl.DataFrame(
                    cast(dict[str, Any] | list[Any], measurement_result), strict=False
                )
            except Exception as e:
                raise ValueError(
                    f"Failed to convert measurement_result to a Polars DataFrame: {e}"
                ) from e
        else:
            trial_df = measurement_result

        for param_name, value in parameter_values.items():
            if param_name not in self.parameters:
                raise ValueError(
                    f"Parameter '{param_name}' is not defined in the experiment. Add it first using add_parameter()."
                )
            if native is not None and param_name in trial_df.columns:
                raise ValueError(
                    f"Parameter '{param_name}' conflicts with the native result columns."
                )
            trial_df = trial_df.with_columns(pl.lit(value).alias(param_name))

        if self.data.is_empty():
            self.data = trial_df
        else:
            try:
                self.data = self.data.vstack(trial_df)
            except Exception as e:
                raise ValueError(
                    f"Failed to stack new trial data. Check for schema compatibility. Error: {e}"
                ) from e

    @property
    def measurements(self) -> Mapping[str, Sequence[MeasurementResult | None]]:
        """Named trial captures. A missing capture keeps its position as None."""
        return _StoredMeasurements(self)

    def _measurement_at(self, name: str, trial: int) -> MeasurementResult | None:
        if type(trial) is not int:
            raise TypeError("trial must be a zero-based integer.")
        if not 0 <= trial < self.data.height:
            raise IndexError(f"Trial {trial} is out of range for {self.data.height} rows.")
        sidecar = f"{name}__measurement"
        if name not in self.data.columns or sidecar not in self.data.columns:
            raise KeyError(f"No stored measurement named '{name}'.")

        raw = self.data[sidecar].item(trial)
        values = self.data[name].item(trial)
        if raw is None or values is None:
            return None
        try:
            metadata = json.loads(raw)
            if metadata["schema_version"] != "1.0":
                raise ValueError("unsupported measurement schema version")
            result = metadata["result"]
            if result is None:
                return None
            if not isinstance(result, dict):
                raise ValueError("invalid measurement metadata")
            timestamp = result["timestamp"]
            if type(timestamp) not in (int, float) or not math.isfinite(timestamp):
                raise ValueError("invalid measurement timestamp")
            instrument = result["instrument"]
            units = result["units"]
            measurement_type = result["measurement_type"]
            envelope = result.get("envelope")
            uncertainty = metadata.get("uncertainty", {})
            if not isinstance(uncertainty, dict):
                raise ValueError("invalid uncertainty metadata")
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                f"Cannot restore measurement '{name}' in trial {trial}: {exc}"
            ) from exc

        if isinstance(values, pl.Series):
            if isinstance(values.dtype, pl.Struct):
                values = values.struct.unnest()
            elif uncertainty:
                values = values.to_list()
            else:
                values = values.to_numpy()
        result_type = (
            NativeMeasurementResult if result.get("native_capture") is True else MeasurementResult
        )
        return result_type(
            values=deserialize_uncertain_value(values, uncertainty, unit=units),
            instrument=instrument,
            units=units,
            measurement_type=measurement_type,
            timestamp=timestamp,
            envelope=envelope,
            sampling_rate=result.get("sampling_rate"),
        )

    def list_trials(self) -> None:
        """Print the full trials DataFrame."""
        print(self.data)

    def __iter__(self) -> Iterator[dict[str, Any]]:
        """Iterate over each trial (row) as a dictionary."""
        yield from self.data.to_dicts()

    def __len__(self) -> int:
        """Return the number of trials."""
        return self.data.height

    def __str__(self) -> str:
        """
        Return a string representation of the experiment.

        This includes a summary of the experiment details and prints the first 5 rows
        of the trial data (the head).
        """
        param_str = ", ".join(str(param) for param in self.parameters.values())
        head_data: pl.DataFrame | str
        if not self.data.is_empty():
            head_data = self.data.head(5)
        else:
            head_data = "No trial data available."

        return (
            f"Experiment: {self.name}\n"
            f"Description: {self.description}\n"
            f"Notes: {self.notes or 'No notes'}\n"
            f"Parameters: {param_str}\n"
            f"Trial Data (first 5 rows):\n{head_data}"
        )

    def save_parquet(self, file_path: str) -> None:
        """
        Save the internal Polars DataFrame as a Parquet file.

        Args:
            file_path (str): The file path (including filename) where the Parquet file will be saved.
        """
        self.data.write_parquet(file_path)
        print(f"Data saved to Parquet file at: {file_path}")

    # ------------------------------------------------------------------
    # Plotting convenience
    def plot(self, spec: PlotSpec | None = None, **kwargs: Any) -> Any:
        """
        Plot the experiment's data using the lightweight plotting layer.

        Args:
            spec: Optional PlotSpec. If not provided, a PlotSpec is built from kwargs.
            **kwargs: Convenience fields for PlotSpec (e.g., kind, x, y, title, xlabel, ylabel, legend, grid).

        Returns:
            A matplotlib Figure object.
        """
        # Local import to keep plotting optional and to avoid import cycles at module import time
        from ..plotting import PlotSpec  # noqa: E402
        from ..plotting import plot_dataframe  # noqa: E402

        if self.data.is_empty():
            raise ValueError("Experiment has no data to plot.")

        spec_to_use = spec or (PlotSpec(**kwargs) if kwargs else PlotSpec())
        return plot_dataframe(self.data, spec_to_use)


class _StoredMeasurements(Mapping[str, Sequence[MeasurementResult | None]]):
    def __init__(self, experiment: Experiment) -> None:
        self._experiment = experiment

    def __iter__(self) -> Iterator[str]:
        columns = self._experiment.data.columns
        available = set(columns)
        return (name for name in columns if f"{name}__measurement" in available)

    def __len__(self) -> int:
        return sum(1 for _ in self)

    def __getitem__(self, name: str) -> Sequence[MeasurementResult | None]:
        columns = self._experiment.data.columns
        if name not in columns or f"{name}__measurement" not in columns:
            raise KeyError(f"No stored measurement named '{name}'.")
        return _StoredTrials(self._experiment, name)


class _StoredTrials(Sequence[MeasurementResult | None]):
    def __init__(self, experiment: Experiment, name: str) -> None:
        self._experiment = experiment
        self._name = name

    def __len__(self) -> int:
        return len(self._experiment)

    @overload
    def __getitem__(self, index: int) -> MeasurementResult | None: ...

    @overload
    def __getitem__(self, index: slice) -> list[MeasurementResult | None]: ...

    def __getitem__(
        self, index: int | slice
    ) -> MeasurementResult | None | list[MeasurementResult | None]:
        if isinstance(index, slice):
            return [self[i] for i in range(*index.indices(len(self)))]
        if index < 0:
            index += len(self)
        return self._experiment._measurement_at(self._name, index)
