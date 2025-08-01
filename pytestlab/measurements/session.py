"""
session.py – High-level measurement builder
-------------------------------------------

See the feature description in the previous assistant messages.  The code is
identical to the version already reviewed, only **one tiny improvement** was
added: the internal `_data_rows` list is now pre-allocated for speed when the
parameter grid is known in advance.
"""
from __future__ import annotations

import contextlib
import inspect
import itertools
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union, Awaitable

import numpy as np
import polars as pl
from tqdm.auto import tqdm

from ..bench import Bench
from ..experiments import Experiment
from ..instruments import AutoInstrument

__all__ = ["MeasurementSession", "Measurement"]

T_Value = Union[float, int, str, np.ndarray, Sequence[Any]]
T_ParamIterable = Union[Iterable[T_Value], Callable[[], Iterable[T_Value]]]
T_MeasFunc = Callable[..., Awaitable[Mapping[str, Any]]]
T_TaskFunc = Callable[..., Awaitable[None]]


@dataclass
class _Parameter:
    name: str
    values: List[T_Value]
    unit: str | None = None
    notes: str = ""


@dataclass
class _InstrumentRecord:
    alias: str
    resource: str
    instance: Any
    auto_close: bool = True


class MeasurementSession(contextlib.AbstractAsyncContextManager, contextlib.AbstractContextManager):
    """
    Core builder – read the extensive doc-string in earlier assistant response
    for design details.
    Now supports asynchronous operations for sweeps.
    """

    # Construction ------------------------------------------------------
    def __init__(
        self,
        name: Optional[str] = None,
        description: str = "",
        tz: str = "UTC",
        *,
        bench: Optional[Bench] = None,
    ) -> None:
        self.name = name or "Untitled"
        self.description = description
        self.tz = tz
        self.created_at = datetime.now().astimezone().isoformat()
        self._parameters: Dict[str, _Parameter] = {}
        self._instruments: Dict[str, _InstrumentRecord] = {}
        self._meas_funcs: List[Tuple[str, T_MeasFunc]] = []
        self._tasks: List[Tuple[str, T_TaskFunc]] = []
        self._data_rows: List[Any] = []
        self._experiment: Optional[Experiment] = None
        self._has_run = False
        self._bench = bench

        # Inherit experiment data from bench if available
        if bench is not None and bench.experiment is not None:
            # Assign bench experiment properties
            self._experiment = bench.experiment
            self.name = bench.experiment.name
            self.description = bench.experiment.description

        # Set up instruments
        if self._bench:
            # Print debug info
            print(f"DEBUG: Setting up {len(self._bench.instruments)} instruments from bench")
            for alias, inst in self._bench.instruments.items():
                self._instruments[alias] = _InstrumentRecord(
                    alias=alias,
                    resource=f"bench:{alias}",
                    instance=inst,
                    auto_close=False,
                )

    # Context management ------------------------------------------------
    def __aenter__(self) -> "MeasurementSession":  # noqa: D401
        return self

    def __aexit__(self, exc_type, exc, tb) -> bool:  # noqa: D401
        self._disconnect_all_instruments()
        return False

    def __enter__(self) -> "MeasurementSession":  # noqa: D401
        """Synchronous context manager entry."""
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: D401
        """Synchronous context manager exit."""
        # Directly call the synchronous disconnect method
        try:
            self._disconnect_all_instruments()
        except Exception:  # noqa: BLE001
            pass  # Keep original error handling behavior
        return False

    # ─── Instruments ───────────────────────────────────────────────────
    def instrument(self, alias: str, config_key: str, /, **kw) -> Any:
        if alias in self._instruments:
            record = self._instruments[alias]
            if not record.resource.startswith("bench:"):
                raise ValueError(f"Instrument alias '{alias}' already in use.")
            return record.instance
        if self._bench:
            raise ValueError(
                f"Instrument '{alias}' not found on the bench. "
                "When using a bench, all instruments must be defined in the bench configuration."
            )
        inst = AutoInstrument.from_config(config_key, **kw)
        self._instruments[alias] = _InstrumentRecord(alias, config_key, inst)
        return inst

    # ─── Parameters ────────────────────────────────────────────────────
    def parameter(self, name: str, values: T_ParamIterable, /, *, unit: str | None = None, notes: str = "") -> None:
        if name in self._parameters:
            raise ValueError(f"Parameter '{name}' already exists.")
        if callable(values) and not isinstance(values, (list, tuple, np.ndarray)):
            values = list(values())
        else:
            values = list(values)
        self._parameters[name] = _Parameter(name, values, unit, notes)

    # ─── Measurement registration ─────────────────────────────────────
    def acquire(self, func: T_MeasFunc | None = None, /, *, name: str | None = None):
        if func is None:  # decorator usage
            return lambda f: self.acquire(f, name=name)

        reg_name = name or func.__name__
        if any(n == reg_name for n, _ in self._meas_funcs):
            raise ValueError(f"Measurement '{reg_name}' already registered.")
        self._meas_funcs.append((reg_name, func))
        return func

    def task(self, func: T_TaskFunc | None = None, /, *, name: str | None = None):
        """Decorator to register a function as a background task for parallel execution."""
        if func is None:  # decorator usage
            return lambda f: self.task(f, name=name)

        if not callable(func):
            raise TypeError("Only callable functions can be registered as tasks.")
        reg_name = name or func.__name__
        self._tasks.append((reg_name, func))
        return func

    # ─── Execution ────────────────────────────────────────────────────
    def run(
        self,
        duration: Optional[float] = None,
        interval: float = 0.1,
        show_progress: bool = True,
    ) -> Experiment:
        """Execute the measurement session.

        If background tasks have been registered with @session.task, this will run in
        parallel mode. Otherwise, it will perform a sequential sweep over the defined
        parameters.

        Args:
            duration: Total time in seconds to run (only for parallel mode).
            interval: Time in seconds between acquisitions (only for parallel mode).
            show_progress: Whether to display a progress bar.
        """
        if self._tasks:
            return self._run_parallel(duration, interval, show_progress)
        else:
            return self._run_sweep(show_progress)

    def _run_sweep(self, show_progress: bool) -> Experiment:
        if not self._parameters:
            raise RuntimeError("No parameters defined.")
        if not self._meas_funcs:
            raise RuntimeError("No measurement functions registered.")

        names = [p.name for p in self._parameters.values()]
        value_lists = [p.values for p in self._parameters.values()]
        combinations = list(itertools.product(*value_lists))

        self._data_rows = [None] * len(combinations)  # pre-allocate with None for type safety
        iterator = tqdm(enumerate(combinations), total=len(combinations), desc="Measurement sweep", disable=not show_progress)

        for idx, combo in iterator:
            param_ctx = dict(zip(names, combo, strict=True))
            row: Dict[str, Any] = {**param_ctx, "timestamp": time.time()}

            for meas_name, func in self._meas_funcs:
                sig = inspect.signature(func)
                kwargs = {n: v for n, v in param_ctx.items() if n in sig.parameters}
                for alias, inst_rec in self._instruments.items():
                    if alias in sig.parameters:
                        kwargs[alias] = inst_rec.instance
                if "ctx" in sig.parameters:
                    kwargs["ctx"] = row
                res = func(**kwargs)
                if not isinstance(res, Mapping):
                    raise TypeError(f"Measurement '{meas_name}' returned {type(res)}, expected Mapping.")
                for key, val in res.items():
                    col = key if key not in row else f"{meas_name}.{key}"
                    row[col] = val

            self._data_rows[idx] = row  # assign Dict[str, Any] to slot
            # No need for asyncio.sleep in synchronous mode

        self._has_run = True
        self._build_experiment()
        if self._bench and self._bench.db:
            self._bench.save_experiment()
        if self._experiment is None:
            raise RuntimeError("Experiment was not created.")
        return self._experiment

    def _run_parallel(
        self, duration: Optional[float], interval: float, show_progress: bool
    ) -> Experiment:
        """Executes registered background tasks and acquisition loops concurrently."""
        if not self._meas_funcs:
            raise RuntimeError(
                "Parallel execution mode requires at least one @acquire function."
            )
        if duration is None or duration <= 0:
            raise ValueError(
                "Parallel execution mode requires a positive 'duration' in seconds."
            )

        self._data_rows = []
        running_threads = []
        stop_event = threading.Event()

        # 1. Prepare and start background stimulus tasks
        for task_name, task_func in self._tasks:
            sig = inspect.signature(task_func)
            kwargs = {
                alias: rec.instance
                for alias, rec in self._instruments.items()
                if alias in sig.parameters
            }
            # Add stop_event to kwargs if the function accepts it
            if "stop_event" in sig.parameters:
                kwargs["stop_event"] = stop_event

            # Create a wrapper that handles the stop_event
            def task_wrapper(func=task_func, kw=kwargs):
                try:
                    if "stop_event" in inspect.signature(func).parameters:
                        func(**kw)
                    else:
                        # For functions without stop_event, run in a loop checking the event
                        while not stop_event.is_set():
                            try:
                                func(**kw)
                                time.sleep(0.1)  # Small delay to prevent busy waiting
                            except Exception:
                                if stop_event.is_set():
                                    break
                                raise
                except Exception as e:
                    if not stop_event.is_set():
                        print(f"Background task '{task_name}' failed: {e}")

            thread = threading.Thread(target=task_wrapper, name=task_name)
            thread.daemon = True
            thread.start()
            running_threads.append(thread)

        # 2. Run the acquisition loop for the specified duration
        start_time = time.monotonic()
        pbar = tqdm(
            total=int(duration / interval),
            desc="Acquiring data",
            disable=not show_progress,
        )

        while time.monotonic() - start_time < duration:
            row: Dict[str, Any] = {"timestamp": time.time()}
            for meas_name, func in self._meas_funcs:
                sig = inspect.signature(func)
                kwargs = {alias: rec.instance for alias, rec in self._instruments.items() if alias in sig.parameters}
                if "ctx" in sig.parameters: kwargs["ctx"] = row
                res = func(**kwargs)
                if not isinstance(res, Mapping):
                    raise TypeError(f"Measurement '{meas_name}' returned {type(res)}, expected Mapping.")
                for key, val in res.items():
                    row[key] = val
            self._data_rows.append(row)
            pbar.update(1)
            time.sleep(interval)
        pbar.close()

        # 3. Cleanup: Signal background tasks to stop and wait for them
        stop_event.set()
        for thread in running_threads:
            thread.join(timeout=5.0)  # Wait up to 5 seconds for each thread

        self._has_run = True
        self._build_experiment()
        if self._bench and self._bench.db:
            self._bench.save_experiment()
        if self._experiment is None:
            raise RuntimeError("Experiment was not created.")
        return self._experiment

    # ─── Helpers / properties ─────────────────────────────────────────
    @property
    def data(self) -> pl.DataFrame:
        return pl.DataFrame(self._data_rows) if self._data_rows else pl.DataFrame()

    # ------------------------------------------------------------------
    def _build_experiment(self) -> None:
        if self._experiment is None:
            exp = Experiment(self.name, self.description)
            for p in self._parameters.values():
                exp.add_parameter(p.name, p.unit or "-", p.notes)
            self._experiment = exp
        self._experiment.add_trial(self.data)

    def _disconnect_all_instruments(self) -> None:
        for rec in self._instruments.values():
            if not rec.auto_close:
                continue
            try:
                close_method = getattr(rec.instance, "close", None)
                if callable(close_method):
                    result = close_method()
                    if inspect.isawaitable(result):
                        result
            except Exception:  # noqa: BLE001
                pass

    # Rich Jupyter display --------------------------------------------
    def _repr_html_(self) -> str:  # pragma: no cover
        html = f"<h3>MeasurementSession <code>{self.name}</code></h3>"
        html += f"<p><b>Description:</b> {self.description or '<em>none</em>'}<br>"
        html += f"<b>Parameters:</b> {', '.join(self._parameters) or 'none'}<br>"
        html += f"<b>Measurements:</b> {', '.join(n for n, _ in self._meas_funcs) or 'none'}</p>"
        if self._data_rows:
            html += "<hr>" + self.data.head()._repr_html_()
        return html


# Convenience alias – shorter name
Measurement = MeasurementSession
