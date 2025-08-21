"""
pytestlab.plotting
==================

Phase 1 lightweight plotting layer for PyTestLab.

Features:
- Optional matplotlib backend (imported lazily).
- Unified helpers:
    * PlotSpec      – declarative container for simple plots
    * plot_dataframe – line/scatter plotting of polars.DataFrame
    * plot_ndarray   – 1D array plotting (waveform style; time axis if sampling rate provided)

Integrated Convenience:
- Experiment.plot()
- MeasurementSession.plot()
- MeasurementResult.plot()

Installation (to enable plotting):
    pip install 'pytestlab[plot]'

Future extension roadmap (Phase 2+):
- Backend registry (plotly, bokeh)
- Live streaming (LivePlotSession)
- Uncertainty bands (UFloats -> error bars / shaded region)
- Specialized kinds: bode, spectrogram, waterfall
- Compliance serialization: attaching PlotSpec JSON to experiment metadata

This module simply re-exports the public API from simple.py.
"""

from .simple import PlotSpec
from .simple import plot_dataframe
from .simple import plot_ndarray

# Optional: attach monkey-patched .plot conveniences lazily when module is imported.
# We avoid importing heavy modules here; the call-sites import plotting helpers locally.

__all__ = [
    "PlotSpec",
    "plot_dataframe",
    "plot_ndarray",
]
