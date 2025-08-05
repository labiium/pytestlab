"""
pytestlab – scientific measurement toolbox
=========================================

This file now **re-exports** the new high-level measurement builder so that
users can simply write

>>> from pytestlab import Measurement

or

>>> from pytestlab.measurements import Measurement
"""

__version__ = "0.2.1"  # Update this line to change the version

from importlib import metadata as _metadata
import logging # Required for set_log_level
from ._log import get_logger, set_log_level, reinitialize_logging



# ─── Public re-exports from existing sub-packages ──────────────────────────
from .config import *
from .experiments import *
from .instruments import *
from .errors import *
from .bench import Bench

# ─── New high-level builder ────────────────────────────────────────────────
from .measurements.session import Measurement, MeasurementSession  # noqa: E402  pylint: disable=wrong-import-position

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
    # Bench System
    "Bench",
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

# needs to be imported after the MeasurementResult class is defined
from . import compliance
compliance.initialize()
