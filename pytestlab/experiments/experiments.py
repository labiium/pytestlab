class ExperimentParameter:
    """Represents a single experiment parameter."""
    def __init__(self, name, units, notes=""):
        self.name = name
        self.units = units
        self.notes = notes

    def __str__(self):
        return f"{self.name} ({self.units})"

class Trial:
    """Represents a parameters and experiement results"""
    def __init__(self, data, parameters):
        self.data = []
        self.parameters = []
        self.index = 0  # Initialize an index for iteration

    def __iter__(self):
        # The object itself is the iterator in this case.
        return self

    def __next__(self):
        # This method should return the next item in the sequence.
        if self.index < len(self.data):
            result = self.data[self.index]
            self.index += 1
            return result
        # If there are no more items, raise StopIteration
        raise StopIteration

    # def __str__(self):
    #     return f"Trial({parameter'='value',' for paramter, value in paramters  })"

class Experiment:
    """Manages an experiment with parameters that can vary across measurements."""
    def __init__(self, name, description=""):
        self.name = name
        self.description = description
        self.parameters = {}  # Stores ExperimentParameter objects
        self.measurements = []  # Stores tuples of measurement values and parameter values

    def add_parameter(self, name, units):
        """Adds a base parameter to the experiment."""
        self.parameters[name] = ExperimentParameter(name, units)

    def add_trial(self, values, **parameter_values):
        """Adds a measurement with specified parameter values.
        
        Args:
            values: Measurement values.
            **parameter_values: Arbitrary number of parameter values, passed as keyword arguments.
        """
        if len(parameter_values) != len(parameters):
            raise ValueError(f"Incorrect number of arguments. {len(parameter_values)} have been supplied but {len(parameters)} expected.")
        for param in parameter_values:
            if param not in self.parameters :
                raise ValueError(f"Parameter '{param}' not defined.")
        self.measurements.append((values, parameter_values))

    def __str__(self):
        return (f"Experiment: {self.name}\nDescription: {self.description}\n"
                f"Parameters: {', '.join([str(p) for p in self.parameters.values()])}\n"
                f"Measurements: {len(self.measurements)}")

    def list_trial(self):
        """Prints out all measurements with their parameters."""
        for values, params in self.measurements:
            params_str = ', '.join([f"{param}={value}" for param, value in params.items()])
            print(f"Values: {values}, Parameters: {params_str}")
