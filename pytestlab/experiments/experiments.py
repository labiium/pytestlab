import polars as pl

class ExperimentParameter:
    """Represents a single experiment parameter."""
    def __init__(self, name, units, notes=""):
        self.name = name
        self.units = units
        self.notes = notes

    def __str__(self):
        return f"{self.name} ({self.units})"

class Experiment:
    """Experiment tracker to store measurements and parameters.
    
    Attributes:
        name (str): The name of the experiment.
        description (str): A description of the experiment.
        parameters (dict): A dictionary of ExperimentParameter objects.
        data (DataFrame): A DataFrame of experiment and parameters.
    """
    def __init__(self, name, description=""):
        """
        Args:
            name (str): The name of the experiment.
            description (str, optional): A description of the experiment.
        """
        self.name = name
        self.description = description
        self.parameters = {}  # Stores ExperimentParameter objects
        self.data = pl.DataFrame()
        self.schema = {}

    def add_parameter(self, name, units, notes=""):
        """Adds a base parameter to the experiment.
        
        Args:
            name (str): The name of the parameter.
            units (str): The units of the parameter.
        """
        self.parameters[name] = ExperimentParameter(name, units, notes=notes)

    def add_trial(self, measurement_result, **parameter_values):
        """Adds a trial with measurement results and parameter values to the experiment.

        Args:
            measurement_result (polars.DataFrame): A Polars DataFrame with measurement results.
            **parameter_values: Parameter values for the trial.
        """
        if len(parameter_values) != len(self.parameters):
            raise ValueError(f"Incorrect number of parameters. {len(parameter_values)} provided but {len(self.parameters)} expected.")
        for param in parameter_values:
            if param not in self.parameters:
                raise ValueError(f"Parameter '{param}' not defined.")
        
        # Check reserved column names not in data
        if "TRIAL_ID" in measurement_result.values.columns:
            raise ValueError("Column name 'EXPERIMENT_ID' is reserved for the experiment ID.")

        # Ensure the structure for new trials matches the first one or establish it for the first trial
        if self.data.height == 0:
            # Initialize measurements DataFrame with the correct schema
            schema = {name: pl.List(measurement_result.values.dtypes[i]) for i, name in enumerate(measurement_result.values.columns)}
            schema.update({name: pl.Float64 for name in parameter_values}) 
            schema = {"TRIAL_ID": pl.UInt64, **schema}
            self.schema = schema
            self.data = pl.DataFrame([], schema=schema)
        # elif set(measurement_result.values.columns) | set(parameter_values.keys()) != set(self.data.columns):
        #     raise ValueError("The structure of the trial does not match the existing structure of the measurements DataFrame.")
        # exclude the ID column and parameter_values
        elif set(measurement_result.values.columns) != set(self.data.columns[1:len(self.data.columns)-len(parameter_values)]):
            raise ValueError("The structure of the trial does not match the existing structure of the measurements DataFrame.")
        
        # Collapse the measurement DataFrame values into a Series
        experiment_row = pl.DataFrame(
            {
                "TRIAL_ID": pl.Series([self.data.height + 1], dtype=pl.UInt64),
                **{name: [value] for name, value in measurement_result.values.to_dict().items()},
                **{name: [value] for name, value in parameter_values.items()}
            },
            schema=self.schema
        )

        print(experiment_row)
        print(self.data)
        self.data = self.data.vstack(experiment_row)

    def __str__(self):
        return (f"Experiment: {self.name}\nDescription: {self.description}\n"
                f"Parameters: {', '.join([str(p) for p in self.parameters.values()])}\n"
                f"Measurements: {len(self.data)} trials")

    def list_trials(self):
        """Prints out all measurements with their parameters."""
        print(self.data)

    def __iter__(self):
        """Iterate over the trials in the experiment."""
        for trial in self.data.iterrows():
            yield trial



    def __len__(self):
        return len(self.data)
    
    def __getitem__(self, column):
        return self.data[column]