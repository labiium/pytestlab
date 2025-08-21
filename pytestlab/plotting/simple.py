"""
Simple plotting utilities (Phase 1) for PyTestLab.

Goals:
- Provide a lightweight, optional plotting layer (matplotlib-based).
- Offer consistent .plot() convenience for Experiment, MeasurementSession, MeasurementResult.
- Gracefully degrade if matplotlib is not installed.
- Keep API surface small so future phases (registry, interactive backends, live updates) can extend.

Future Enhancements (Phase 2+ ideas):
- Plot registry for custom kinds (bode, waterfall, spectrogram).
- LivePlotSession for streaming updates during parallel acquisition.
- Uncertainty visualization (UFloats -> error bars / bands).
- Interactive backends (plotly, bokeh) via plugin mechanism.
- PlotSpec serialization (JSON/YAML) tied to compliance/audit layer.

This module intentionally avoids any heavy abstraction—just enough structure
(PlotSpec + helper functions) to unify basic plotting logic.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import polars as pl

# Optional backend import -----------------------------------------------------
try:
    import matplotlib.pyplot as _plt  # type: ignore
except Exception:  # pragma: no cover
    _plt = None  # Will trigger graceful failure in _require_backend()


# Public Types ----------------------------------------------------------------
Number = int | float


@dataclass
class PlotSpec:
    """
    Declarative parameters for a single static plot.

    Attributes:
        kind: 'line' or 'scatter'
        title: Optional title
        x: Column name for x-axis (auto-detected if None)
        y: Column(s) for y-axis. If None -> auto pick all numeric except x.
        xlabel/ylabel: Axis labels (optional)
        legend: Show legend if multiple y-series
        grid: Enable background grid
    """
    kind: str = "line"
    title: str | None = None
    x: str | None = None
    y: str | Sequence[str] | None = None
    xlabel: str | None = None
    ylabel: str | None = None
    legend: bool = True
    grid: bool = True
    preserve_points: bool = True


# Internal Helpers ------------------------------------------------------------
def _require_backend():
    """
    Ensures matplotlib is available. Raises a user-friendly error otherwise.
    """
    if _plt is None:
        raise RuntimeError(
            "matplotlib not available. Install extras: pip install 'pytestlab[plot]'"
        )
    return _plt


def _auto_numeric_columns(df: pl.DataFrame) -> list[str]:
    """
    Return a list of numeric column names in the given Polars DataFrame.
    """
    cols: list[str] = []
    for name, dtype in zip(df.columns, df.dtypes, strict=True):
        # Polars dtypes have predicate helpers (is_numeric) - fallback safe check.
        is_num = getattr(dtype, "is_numeric", lambda: False)()
        if is_num:
            cols.append(name)
    return cols


def _select_x_column(df: pl.DataFrame, explicit: str | None) -> str:
    """
    Choose an x column: explicit if provided, else time-like, else the first column.
    """
    if explicit is not None:
        if explicit not in df.columns:
            raise ValueError(f"x column '{explicit}' not in DataFrame.")
        return explicit

    for candidate in ("Time (s)", "timestamp", "time", "Time"):
        if candidate in df.columns:
            return candidate

    return df.columns[0]


def _select_y_columns(df: pl.DataFrame, x_col: str, y_spec: str | Sequence[str] | None) -> list[str]:
    """
    Determine y-series list based on user spec or auto numeric selection.
    """
    if y_spec is None:
        numeric_cols = [c for c in _auto_numeric_columns(df) if c != x_col]
        if not numeric_cols:
            raise ValueError("No numeric columns available to plot as y-series.")
        return numeric_cols
    if isinstance(y_spec, str):
        if y_spec not in df.columns:
            raise ValueError(f"y column '{y_spec}' not present.")
        return [y_spec]
    ys = list(y_spec)
    for col in ys:
        if col not in df.columns:
            raise ValueError(f"y column '{col}' not present.")
    return ys


# Public Plot Functions -------------------------------------------------------
def plot_dataframe(df: pl.DataFrame, spec: PlotSpec):
    """
    Plot a Polars DataFrame using a PlotSpec.

    Complexity: O(N * M)
      N: number of rows
      M: number of y-series

    Returns:
        matplotlib Figure instance.

    Raises:
        ValueError if DataFrame empty or columns invalid.
        RuntimeError if backend missing.
    """
    if df.is_empty():
        raise ValueError("Cannot plot an empty DataFrame.")

    plt = _require_backend()
    if spec.preserve_points:
        try:
            # Avoid aggressive vertex simplification and chunking that can hide dense features
            plt.rcParams["path.simplify"] = False
            plt.rcParams["agg.path.chunksize"] = 0
        except Exception:
            pass

    x_col = _select_x_column(df, spec.x)
    y_cols = _select_y_columns(df, x_col, spec.y)

    x_vals = df[x_col].to_numpy()
    fig, ax = plt.subplots()

    for y in y_cols:
        y_vals = df[y].to_numpy()
        if spec.kind == "scatter":
            ax.scatter(x_vals, y_vals, label=y)
        else:  # default 'line'
            ax.plot(x_vals, y_vals, label=y)

    # Labels & styling
    ax.set_xlabel(spec.xlabel or x_col)
    if spec.ylabel:
        ax.set_ylabel(spec.ylabel)
    elif len(y_cols) == 1:
        ax.set_ylabel(y_cols[0])
    if spec.title:
        ax.set_title(spec.title)
    if spec.grid:
        ax.grid(True, which="both", linestyle="--", alpha=0.4)
    if spec.legend and len(y_cols) > 1:
        ax.legend()

    fig.tight_layout()
    return fig


def plot_ndarray(
    arr,
    spec: PlotSpec,
    *,
    sampling_rate: float | None = None,
    units: str | None = None,
):
    """
    Plot a 1D numpy array. If sampling_rate supplied, derive a time axis.

    Complexity: O(N)

    Args:
        arr: 1D array-like
        spec: PlotSpec (kind/title/grid used)
        sampling_rate: (Hz) if provided, x-axis = time
        units: optional y-axis units label

    Returns:
        matplotlib Figure.

    Raises:
        ValueError for unsupported dimensions.
    """
    import numpy as np  # Local import avoids unconditional dependency
    plt = _require_backend()
    if spec.preserve_points:
        try:
            plt.rcParams["path.simplify"] = False
            plt.rcParams["agg.path.chunksize"] = 0
        except Exception:
            pass

    a = np.asarray(arr)
    if a.ndim != 1:
        raise ValueError("plot_ndarray only supports 1D arrays in Phase 1.")

    if sampling_rate and sampling_rate > 0:
        x = np.arange(a.size) / sampling_rate
        x_label = "Time (s)"
    else:
        x = np.arange(a.size)
        x_label = "Index"

    fig, ax = plt.subplots()
    if spec.kind == "scatter":
        ax.scatter(x, a, s=10)
    else:
        ax.plot(x, a)

    ax.set_xlabel(x_label)
    y_lab = "Value"
    if units:
        y_lab += f" ({units})"
    ax.set_ylabel(y_lab)

    if spec.title:
        ax.set_title(spec.title)
    if spec.grid:
        ax.grid(True, linestyle="--", alpha=0.4)

    fig.tight_layout()
    return fig


# Re-export / Public API ------------------------------------------------------
__all__ = [
    "PlotSpec",
    "plot_dataframe",
    "plot_ndarray",
]
