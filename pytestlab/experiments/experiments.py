class ExperimentParameter:
    """Represents a single experiment parameter."""
    def __init__(self, name, units, notes=""):
        self.name = name
        self.units = units
        self.notes = notes

    def __str__(self):
        return f"{self.name} ({self.units})"

class Trial:
    """Represents an individual measurement with associated parameter values."""
    def __init__(self, data, parameters):
        self.data = data
        self.parameters = parameters

    def __repr__(self):
        parameters_str = ", ".join(f"{parameter}='{value}'" for parameter, value in self.parameters.items())
        return f"Trial({{{parameters_str}}}\n{self.data})"
    
    def __str__(self):
        parameters_str = ", ".join(f"{parameter}='{value}'" for parameter, value in self.parameters.items())
        return f"Trial({{{parameters_str}}}\n{self.data})"

class Experiment:
    """Experiment tracker to store measurements and parameters.
    
    Attributes:
        name (str): The name of the experiment.
        description (str): A description of the experiment.
        parameters (dict): A dictionary of ExperimentParameter objects.
        trials (list): A list of Trial objects.
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
        self.trials = []  # Stores tuples of measurement values and parameter values

    def add_parameter(self, name, units, notes=""):
        """Adds a base parameter to the experiment.
        
        Args:
            name (str): The name of the parameter.
            units (str): The units of the parameter.
        """
        self.parameters[name] = ExperimentParameter(name, units, notes=notes)

    def add_trial(self, values, **parameter_values):
        """Adds a measurement with specified parameter values.
        
        Args:
            values: Measurement values.
            **parameter_values: Arbitrary number of parameter values, passed as keyword arguments.
        """
        if len(parameter_values) != len(self.parameters):
            raise ValueError(f"Incorrect number of arguments. {len(parameter_values)} have been supplied but {len(self.parameters)} expected.")
        for param in parameter_values:
            if param not in self.parameters :
                raise ValueError(f"Parameter '{param}' not defined.")
        self.trials.append(Trial(values, parameter_values))

    def __str__(self):
        return (f"Experiment: {self.name}\nDescription: {self.description}\n"
                f"Parameters: {', '.join([str(p) for p in self.parameters.values()])}\n"
                f"Measurements: {len(self.trials)}")

    def list_trial(self):
        """Prints out all measurements with their parameters."""
        for trial in self.trials:
            print(trial)