import polars as pl

# Attempt to import pyarrow; if not available, raise an informative error.
# try:
#     import pyarrow as pa
# except ModuleNotFoundError:
#     raise ModuleNotFoundError("The module 'pyarrow' is required for exporting to Arrow. "
#                               "Please install it using 'pip install pyarrow'.")

class ExperimentParameter:
    """Represents a single experiment parameter."""
    def __init__(self, name, units, notes=""):
        self.name = name
        self.units = units
        self.notes = notes

    def __str__(self):
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
    def __init__(self, name, description=""):
        self.name = name
        self.description = description
        self.parameters = {}  # key: parameter name, value: ExperimentParameter
        self.data = pl.DataFrame()  # Always stored as a Polars DataFrame

    def add_parameter(self, name, units, notes=""):
        """
        Add a new parameter to the experiment.
        
        Args:
            name (str): Name of the parameter.
            units (str): Units for the parameter.
            notes (str, optional): Additional notes.
        """
        self.parameters[name] = ExperimentParameter(name, units, notes)

    def add_trial(self, measurement_result, **parameter_values):
        """
        Add a new trial to the experiment.
        
        Accepts measurement data in various formats (list, dict, or Polars DataFrame)
        and converts it into a Polars DataFrame if needed. Additional parameter values
        are added as new columns.
        
        Args:
            measurement_result (pl.DataFrame, dict, or list): The measurement data.
            **parameter_values: Additional parameters to include with this trial.
            
        Raises:
            ValueError: If the conversion to a Polars DataFrame fails or if a
                        provided parameter is not defined.
        """
        # Convert non-DataFrame input into a Polars DataFrame.
        if not isinstance(measurement_result, pl.DataFrame):
            try:
                # strict=False allows mixed types (e.g. int and float) in the same column.
                measurement_result = pl.DataFrame(measurement_result, strict=False)
            except Exception as e:
                raise ValueError("Failed to convert measurement_result to a Polars DataFrame") from e

        # Append additional parameter values as new columns.
        for param_name, value in parameter_values.items():
            if param_name not in self.parameters:
                raise ValueError(f"Parameter '{param_name}' is not defined in the experiment.")
            measurement_result = measurement_result.with_columns(pl.lit(value).alias(param_name))
        
        # Stack the new trial onto the existing data.
        if self.data.is_empty():
            self.data = measurement_result
        else:
            self.data = self.data.vstack(measurement_result)

    def list_trials(self):
        """Print the full trials DataFrame."""
        print(self.data)

    def __iter__(self):
        """Iterate over each trial (row) as a dictionary."""
        for row in self.data.to_dicts():
            yield row

    def __len__(self):
        """Return the number of trials."""
        return self.data.height

    def __str__(self):
        """
        Return a string representation of the experiment.
        
        This includes a summary of the experiment details and prints the first 5 rows
        of the trial data (the head).
        """
        param_str = ", ".join(str(param) for param in self.parameters.values())
        head = self.data.head(5) if not self.data.is_empty() else "No trial data available."
        return (f"Experiment: {self.name}\n"
                f"Description: {self.description}\n"
                f"Parameters: {param_str}\n"
                f"Trial Data (first 5 rows):\n{head}")

    # def save_arrow(self, file_path):
    #     """
    #     Save the internal data as an Apache Arrow file to disk.
        
    #     Args:
    #         file_path (str): The file path (including filename) where the Arrow file will be saved.
            
    #     This method converts the internal Polars DataFrame to a pyarrow.Table and writes it
    #     to disk using the Arrow IPC file format.
    #     """
    #     arrow_table = self.data.to_arrow()
    #     pa.ipc.write_table(arrow_table, file_path)
    #     print(f"Data saved to Arrow file at: {file_path}")

    def save_parquet(self, file_path):
        """
        Save the internal Polars DataFrame as a Parquet file.
        
        Args:
            file_path (str): The file path (including filename) where the Parquet file will be saved.
        """
        self.data.write_parquet(file_path)
        print(f"Data saved to Parquet file at: {file_path}")
