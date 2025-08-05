import warnings

class InstrumentConnectionError(Exception):
    """Exception raised for SCPI instrument connection errors."""

    def __init__(self, instrument=None, message=""):
        self.instrument = instrument
        self.message = message
        if instrument:
            super().__init__(f"Failed to connect to instrument '{instrument}'. {message}")
        else:
            super().__init__(f"Failed to connect to instrument. {message}")


class InstrumentCommunicationError(Exception):
    """Exception raised for SCPI communication errors."""

    def __init__(self, instrument=None, command=None, message=""):
        self.instrument = instrument
        self.command = command
        self.message = message
        full_message = f"Error in SCPI communication with instrument '{instrument}'"
        if command:
            full_message += f" while sending command '{command}'"
        full_message += f". {message}"
        super().__init__(full_message)


class FormulationError(Exception):
    """Exception raised when a computation error occurs."""

    def __init__(self, message="An error occurred in a computation."):
        self.message = message
        super().__init__(self.message)


class InstrumentConnectionBusy(Exception):
    """Exception raised when the instrument is in use somewhere else."""

    def __init__(self, instrument=None):
        self.instrument = instrument
        if instrument:
            super().__init__(f"The instrument '{instrument}' has an open connection elsewhere.")
        else:
            super().__init__("The instrument has an open connection elsewhere.")


class InstrumentParameterError(ValueError):
    """Exception raised for invalid parameters given to an instrument."""

    def __init__(self, parameter=None, value=None, valid_range=None, message=""):
        self.parameter = parameter
        self.value = value
        self.valid_range = valid_range
        self.message = message
        full_message = "Invalid parameter value for instrument"
        if parameter:
            full_message += f" for parameter '{parameter}'"
        if value is not None:
            full_message += f": received '{value}'"
        if valid_range:
            full_message += f", but expected a value in the range {valid_range}"
        full_message += f". {message}"
        super().__init__(full_message)

class InstrumentNotFoundError(Exception):
    """For instrument not found errors."""

    def __init__(self, name):
        super().__init__(f"Instrument {name} not found in the manager's collection.")


class InstrumentConfigurationError(Exception):
    """Exception raised for instrument configuration errors."""

    def __init__(self, instrument=None, message=""):
        self.instrument = instrument
        self.message = message
        if instrument:
            super().__init__(f"Invalid configuration for instrument '{instrument}'. {message}")
        else:
            super().__init__(f"Invalid instrument configuration. {message}")


## WARNINGS

class CommunicationError(Warning):
    """For SCPI communication warnings."""
    pass


# Database errors

class DatabaseError(Exception):
    """Exception raised for database errors."""

    def __init__(self, operation=None, message=""):
        self.operation = operation
        self.message = message
        if operation:
            super().__init__(f"Error in database operation '{operation}'. {message}")
        else:
            super().__init__(f"Error in database operation. {message}")


# Experiment errors


class ExperimentError(Exception):
    """Exception raised for experiment errors."""

    def __init__(self, experiment=None, message=""):
        self.experiment = experiment
        self.message = message
        if experiment:
            super().__init__(f"Error in experiment '{experiment}'. {message}")
        else:
            super().__init__(f"Error in experiment. {message}")


class InstrumentDataError(Exception):
    """Exception raised for errors in instrument data acquisition or parsing."""

    def __init__(self, instrument=None, message=""):
        self.instrument = instrument
        self.message = message
        if instrument:
            super().__init__(f"Instrument data error for '{instrument}'. {message}")
        else:
            super().__init__(f"Instrument data error. {message}")


class ReplayMismatchError(Exception):
    """Raised when a command during replay does not match the recorded log."""

    def __init__(self, message, instrument=None, command=None, expected_command=None, actual_command=None, log_index=None):
        # Store additional attributes
        self.instrument = instrument
        self.command = command
        self.expected_command = expected_command
        self.actual_command = actual_command
        self.log_index = log_index

        # Use the message directly without parent class formatting
        super().__init__(message)
