"""
pytestlab – scientific measurement toolbox
=========================================

This file now **re-exports** the new high-level measurement builder so that
users can simply write

>>> from pytestlab import Measurement

or

>>> from pytestlab.measurements import Measurement
"""

__version__ = "0.1.5"  # Update this line to change the version

from importlib import metadata as _metadata
import logging # Required for set_log_level
from ._log import get_logger

# ─── Public re-exports from existing sub-packages ──────────────────────────
from .config import *
from .experiments import *
from .instruments import *
from .errors import *

# ─── New high-level builder ────────────────────────────────────────────────
from .measurements.session import Measurement, MeasurementSession  # noqa: E402  pylint: disable=wrong-import-position

def set_log_level(level: str) -> None:
    """
    Sets the logging level for the 'pytestlab' root logger.
    Example: set_log_level("DEBUG")
    """
    # Ensure level is a string and uppercase, as logging levels are typically uppercase strings
    level_upper = str(level).upper()
    logger_instance = get_logger("") # Gets the "pytestlab" root logger
    
    # getattr is safer to get the log level attribute
    log_level_int = getattr(logging, level_upper, None)
    if log_level_int is not None:
        logger_instance.setLevel(log_level_int)
    else:
        # Optionally, log a warning or raise an error for invalid level
        # For now, let's print a warning to stderr if level is invalid
        # This uses the base logger to avoid issues if pytestlab logger is not yet fully set up
        logging.warning(f"Invalid log level: {level}. Not changed.")

__all__ = [
    # Config
    "OscilloscopeConfig",
    "MultimeterConfig", 
    "PowerSupplyConfig",
    "WaveformGeneratorConfig",
    # Instruments
    "Oscilloscope",
    "Multimeter",
    "PowerSupply", 
    "WaveformGenerator",
    "AutoInstrument",
    "InstrumentManager",
    # Experiments
    "Experiment",
    "MeasurementResult",
    # Errors
    "InstrumentError",
    "InstrumentConfigurationError",
    "InstrumentParameterError",
    # New measurement system
    "Measurement",
    "MeasurementSession",
    "set_log_level",
]

# Version is defined statically above, but we can still try to get it from metadata
# try:  # pragma: no cover
#     __version__ = _metadata.version(__name__)
# except _metadata.PackageNotFoundError:  # pragma: no cover
#     __version__ = "0.1.0"