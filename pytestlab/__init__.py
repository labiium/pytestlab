"""
pytestlab – scientific measurement toolbox
=========================================

This file now **re-exports** the new high-level measurement builder so that
users can simply write

>>> from pytestlab import Measurement

or

>>> from pytestlab.measurements import Measurement
"""

__version__ = "0.2.3"  # Update this line to change the version

# (logging import removed; no longer needed after cleanup)

from ._log import get_logger
from ._log import reinitialize_logging
from ._log import set_log_level
from .bench import Bench
from .errors import InstrumentConfigurationError
from .errors import InstrumentParameterError
from .experiments import Experiment
from .experiments import MeasurementResult
from .instruments import AutoInstrument
from .measurements.session import Measurement  # noqa: E402
from .measurements.session import MeasurementSession  # noqa: E402

# (Removed unused module-level logger; logging handled via set_log_level/get_logger)

__all__ = [
    "AutoInstrument",
    # Experiments
    "Experiment",
    "MeasurementResult",
    # Errors
    "InstrumentConfigurationError",
    "InstrumentParameterError",
    # Bench System
    "Bench",
    # New measurement system
    "Measurement",
    "MeasurementSession",
    # Logging helpers
    "set_log_level",
    "get_logger",
    "reinitialize_logging",
]

# Version is defined statically above, but we can still try to get it from metadata
# try:  # pragma: no cover
#     __version__ = _metadata.version(__name__)
# except _metadata.PackageNotFoundError:  # pragma: no cover
#     __version__ = "0.1.0"

# needs to be imported after the MeasurementResult class is defined
from . import compliance

compliance.initialize()
