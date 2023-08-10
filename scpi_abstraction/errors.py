class SCPIConnectionError(Exception):
    """For SCPI instrument connection errors."""

    def __init__(self, message="Failed to connect to the instrument."):
        self.message = message
        super().__init__(self.message)

class SCPICommunicationError(Exception):
    """For SCPI communication errors."""

    def __init__(self, message="Error in SCPI communication."):
        self.message = message
        super().__init__(self.message)

class SCPIValueError(ValueError):
    """For invalid SCPI values or settings."""

    def __init__(self, message="Invalid value for SCPI command."):
        self.message = message
        super().__init__(self.message)

class InstrumentNotFoundError(Exception):
    """For instrument not found errors."""

    def __init__(self, name):
        super().__init__(f"Instrument {name} not found in the manager's collection.")


class IntrumentConfigurationError(Exception):
    """For instrument configuration errors."""

    def __init__(self, message="Invalid Instrument configuration."):
        self.message = message
        super().__init__(self.message)