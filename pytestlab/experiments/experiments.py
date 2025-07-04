from __future__ import annotations

import polars as pl
from typing import Dict, Any, Union, List, Iterator, TYPE_CHECKING

if TYPE_CHECKING:
    from .results import MeasurementResult

# Attempt to import pyarrow; if not available, raise an informative error.
# try:
#     import pyarrow as pa
# except ModuleNotFoundError:
#     raise ModuleNotFoundError("The module 'pyarrow' is required for exporting to Arrow. "
#                               "Please install it using 'pip install pyarrow'.")

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
        self.parameters: Dict[str, ExperimentParameter] = {}
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

    def add_trial(self, measurement_result: Union[pl.DataFrame, Dict[str, Any], List[Any], 'MeasurementResult'], **parameter_values: Any) -> None:
        """
        Add a new trial to the experiment.
        
        Accepts measurement data in various formats (list, dict, Polars DataFrame, or MeasurementResult)
        and converts it into a Polars DataFrame if needed. Additional parameter values
        are added as new columns.
        
        Args:
            measurement_result (Union[pl.DataFrame, Dict[str, Any], List[Any], MeasurementResult]): The measurement data.
            **parameter_values: Additional parameters to include with this trial.
            
        Raises:
            ValueError: If the conversion to a Polars DataFrame fails or if a
                        provided parameter is not defined.
        """
        trial_df: pl.DataFrame
        
        # Special handling for MeasurementResult objects
        if hasattr(measurement_result, 'values') and hasattr(measurement_result, 'to_dict'):
            # If it's a MeasurementResult, extract its values
            if isinstance(measurement_result.values, pl.DataFrame):
                trial_df = measurement_result.values
            else:
                # Convert to dict and then to DataFrame
                try:
                    trial_df = pl.DataFrame(measurement_result.to_dict(), strict=False)
                except Exception as e:
                    raise ValueError(f"Failed to convert MeasurementResult to DataFrame: {e}") from e
        elif not isinstance(measurement_result, pl.DataFrame):
            try:
                trial_df = pl.DataFrame(measurement_result, strict=False)
            except Exception as e:
                raise ValueError(f"Failed to convert measurement_result to a Polars DataFrame: {e}") from e
        else:
            trial_df = measurement_result

        for param_name, value in parameter_values.items():
            if param_name not in self.parameters:
                raise ValueError(f"Parameter '{param_name}' is not defined in the experiment. Add it first using add_parameter().")
            trial_df = trial_df.with_columns(pl.lit(value).alias(param_name))
        
        if self.data.is_empty():
            self.data = trial_df
        else:
            try:
                self.data = self.data.vstack(trial_df)
            except Exception as e: 
                raise ValueError(f"Failed to stack new trial data. Check for schema compatibility. Error: {e}") from e


    def list_trials(self) -> None:
        """Print the full trials DataFrame."""
        print(self.data)

    def __iter__(self) -> Iterator[Dict[str, Any]]:
        """Iterate over each trial (row) as a dictionary."""
        for row in self.data.to_dicts():
            yield row

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
        head_data: Union[pl.DataFrame, str]
        if not self.data.is_empty():
            head_data = self.data.head(5)
        else:
            head_data = "No trial data available."

        return (f"Experiment: {self.name}\n"
                f"Description: {self.description}\n"
                f"Notes: {self.notes or 'No notes'}\n"
                f"Parameters: {param_str}\n"
                f"Trial Data (first 5 rows):\n{head_data}")

    # def save_arrow(self, file_path: str) -> None:
    #     """
    #     Save the internal data as an Apache Arrow file to disk.
    #     
    #     Args:
    #         file_path (str): The file path (including filename) where the Arrow file will be saved.
            
    #     This method converts the internal Polars DataFrame to a pyarrow.Table and writes it
    #     to disk using the Arrow IPC file format.
    #     """
    #     arrow_table = self.data.to_arrow()
    #     # import pyarrow as pa # Ensure pyarrow is imported if this method is uncommented
    #     # pa.ipc.write_table(arrow_table, file_path)
    #     print(f"Data saved to Arrow file at: {file_path} (Arrow export currently commented out)")

    def save_parquet(self, file_path: str) -> None:
        """
        Save the internal Polars DataFrame as a Parquet file.
        
        Args:
            file_path (str): The file path (including filename) where the Parquet file will be saved.
        """
        self.data.write_parquet(file_path)
        print(f"Data saved to Parquet file at: {file_path}")
