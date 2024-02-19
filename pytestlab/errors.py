import warnings

class InstrumentConnectionError(Exception):
    """For SCPI instrument connection errors."""

    def __init__(self, message="Failed to connect to the instrument."):
        self.message = message
        super().__init__(self.message)

class InstrumentCommunicationError(Exception):
    """For SCPI communication errors."""

    def __init__(self, message="Error in SCPI communication."):
        self.message = message
        super().__init__(self.message)

class FormulationError(Exception):
    """Error has occuered in a computation"""

    def __init__(self, message="Given arguments have resulted in an error in Computation"):
        super().__init__(self.message)

class InstrumentConnectionBusy(Exception):
    """The instrument is in use somewhere else"""

    def __init__(self, message="The instrument has an open connection elsewhere."):
        self.message = message
        super().__init__(self.message)

class InstrumentParameterError(ValueError):
    """Invalid parameters given to instrument."""

    def __init__(self, message="Invalid parameters given to instrument."):
        self.message = message
        super().__init__(self.message)

class InstrumentNotFoundError(Exception):
    """For instrument not found errors."""

    def __init__(self, name):
        super().__init__(f"Instrument {name} not found in the manager's collection.")


class InstrumentConfigurationError(Exception):
    """For instrument configuration errors."""

    def __init__(self, message="Invalid instrument profile configuration. Check conformity to Profile Specification"):
        self.message = message
        super().__init__(self.message)
        

## WARNINGS

class CommunicationError(Warning):
    """For SCPI communication warnings."""
    pass


# Database errors

class DatabaseError(Exception):
    """For database errors."""

    def __init__(self, message="Error in database operation."):
        self.message = message
        super().__init__(self.message)

# Experiment errors
        
class ExperimentError(Exception):
    """For experiment errors."""

    def __init__(self, message="Error in experiment operation."):
        self.message = message
        super().__init__(self.message)