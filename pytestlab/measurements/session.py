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
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Mapping, Sequence, Tuple, Union

import numpy as np
import polars as pl
from tqdm.auto import tqdm

from ..experiments import Experiment
from ..instruments import AutoInstrument

__all__ = ["MeasurementSession", "Measurement"]

T_Value = Union[float, int, str, np.ndarray, Sequence[Any]]
T_ParamIterable = Union[Iterable[T_Value], Callable[[], Iterable[T_Value]]]
T_MeasFunc = Callable[..., Mapping[str, Any]]


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


class MeasurementSession(contextlib.AbstractContextManager):
    """
    Core builder – read the extensive doc-string in earlier assistant response
    for design details.
    """

    # Construction ------------------------------------------------------
    def __init__(self, name: str, description: str = "", tz: str = "UTC") -> None:
        self.name = name
        self.description = description
        self.tz = tz
        self.created_at = datetime.now().astimezone().isoformat()

        self._parameters: Dict[str, _Parameter] = {}
        self._instruments: Dict[str, _InstrumentRecord] = {}
        self._meas_funcs: List[Tuple[str, T_MeasFunc]] = []

        self._data_rows: List[Dict[str, Any]] = []
        self._experiment: Experiment | None = None
        self._has_run = False

    # Context management ------------------------------------------------
    def __enter__(self) -> "MeasurementSession":  # noqa: D401
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: D401
        self._disconnect_all_instruments()
        return False

    # ─── Instruments ───────────────────────────────────────────────────
    def instrument(self, alias: str, config_key: str, /, **kw) -> Any:
        if alias in self._instruments:
            raise ValueError(f"Instrument alias '{alias}' already in use.")
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

    # ─── Execution ────────────────────────────────────────────────────
    def run(self, show_progress: bool = True) -> Experiment:
        if not self._parameters:
            raise RuntimeError("No parameters defined.")
        if not self._meas_funcs:
            raise RuntimeError("No measurement functions registered.")

        names = [p.name for p in self._parameters.values()]
        value_lists = [p.values for p in self._parameters.values()]
        combinations = list(itertools.product(*value_lists))

        self._data_rows = [{}] * len(combinations)  # pre-allocate
        iterator = tqdm(enumerate(combinations), total=len(combinations), desc="Measurement sweep", disable=not show_progress)

        for idx, combo in iterator:
            param_ctx = dict(zip(names, combo, strict=True))
            row: Dict[str, Any] = {**param_ctx, "timestamp": time.time()}

            for meas_name, func in self._meas_funcs:
                sig = inspect.signature(func)
                kwargs = {n: v for n, v in param_ctx.items() if n in sig.parameters}
                if "ctx" in sig.parameters:
                    kwargs["ctx"] = row
                res = func(**kwargs)
                if not isinstance(res, Mapping):
                    raise TypeError(f"Measurement '{meas_name}' returned {type(res)}, expected Mapping.")
                for key, val in res.items():
                    col = key if key not in row else f"{meas_name}.{key}"
                    row[col] = val

            self._data_rows[idx] = row

        self._has_run = True
        self._build_experiment()
        return self._experiment  # type: ignore[return-value]

    # ─── Helpers / properties ─────────────────────────────────────────
    @property
    def data(self) -> pl.DataFrame:
        return pl.DataFrame(self._data_rows) if self._data_rows else pl.DataFrame()

    # ------------------------------------------------------------------
    def _build_experiment(self) -> None:
        exp = Experiment(self.name, self.description)
        for p in self._parameters.values():
            exp.add_parameter(p.name, p.unit or "-", p.notes)
        exp.add_trial(self.data)
        self._experiment = exp

    def _disconnect_all_instruments(self) -> None:
        for rec in self._instruments.values():
            try:
                getattr(rec.instance, "close", lambda: None)()
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
