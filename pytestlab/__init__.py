"""
pytestlab – scientific measurement toolbox
=========================================

This file now **re-exports** the new high-level measurement builder so that
users can simply write

>>> from pytestlab import Measurement

or

>>> from pytestlab.measurements import Measurement
"""
from importlib import metadata as _metadata

# ─── Public re-exports from existing sub-packages ──────────────────────────
from .config import *
from .experiments import *
from .instruments import *
from .errors import *

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
    # New measurement system
    "Measurement",
    "MeasurementSession",
]

try:  # pragma: no cover
    __version__ = _metadata.version(__name__)
except _metadata.PackageNotFoundError:  # pragma: no cover
    __version__ = "0.0.0+unknown"