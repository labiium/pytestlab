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
import json
import threading
import time
from collections.abc import Callable
from collections.abc import Iterable
from collections.abc import Mapping
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING
from typing import Any
from typing import Literal
from typing import TypeAlias

import numpy as np
import polars as pl
from tqdm.auto import tqdm

from .._log import get_logger
from ..experiments import Experiment
from ..experiments import MeasurementResult
from ..experiments.uncertainty_serialization import serialize_uncertain_value
from .steps import StepSpec

__all__ = ["MeasurementSession", "Measurement"]

_LOG = get_logger("measurements.session")

if TYPE_CHECKING:
    from ..bench import Bench
    from ..compliance.session import ComplianceConfig
    from ..plotting import PlotSpec


T_Value: TypeAlias = float | int | complex | str | np.ndarray | Sequence[Any]
T_ParamIterable: TypeAlias = Iterable[T_Value] | Callable[[], Iterable[T_Value]] | StepSpec
T_MeasFunc: TypeAlias = Callable[..., Mapping[str, Any] | MeasurementResult]
T_TaskFunc: TypeAlias = Callable[..., None]


@dataclass
class _Parameter:
    name: str
    values: list[T_Value]
    unit: str | None = None
    notes: str = ""


@dataclass
class _DeviceRecord:
    alias: str
    resource: str
    instance: Any
    auto_close: bool = True


class MeasurementSession(contextlib.AbstractContextManager):
    """
    Core builder – read the extensive doc-string in earlier assistant response
    for design details.

    Compliance:
        By default (compliance=None), sessions require cryptographic signing,
        audit trails, and timestamps and fail closed if setup is incomplete.
        Pass False or "disabled" to disable compliance, or "best_effort" to
        continue with whichever components initialize successfully. A custom
        ComplianceConfig remains supported.
    """

    # Construction ------------------------------------------------------
    def __init__(
        self,
        name: str | None = None,
        description: str = "",
        tz: str = "UTC",
        *,
        bench: Bench | None = None,
        compliance: Any | None = None,
    ) -> None:
        self.name = name or "Untitled"
        self.description = description
        self.tz = tz
        self.created_at = datetime.now().astimezone().isoformat()
        self._parameters: dict[str, _Parameter] = {}
        self._devices: dict[str, _DeviceRecord] = {}
        self._meas_funcs: list[tuple[str, T_MeasFunc]] = []
        self._tasks: list[tuple[str, T_TaskFunc]] = []
        self._data_rows: list[dict[str, Any]] = []
        self._experiment: Experiment | None = None
        self._has_run = False
        self._bench = bench

        # Auto-configure compliance (invisible by default)
        self._compliance_config: ComplianceConfig | None = None
        self._compliance_wrapper: Callable[[Callable], Callable] | None = None
        self._compliance_mode: Literal["required", "best_effort", "disabled"] = "required"
        self._setup_compliance(compliance)

        # Inherit experiment data from bench if available
        if bench is not None and bench.experiment is not None:
            # Assign bench experiment properties
            self._experiment = bench.experiment
            self.name = bench.experiment.name
            self.description = bench.experiment.description

        # Set up devices
        if self._bench:
            for alias, inst in self._bench.resources.items():
                self._devices[alias] = _DeviceRecord(
                    alias=alias,
                    resource=f"bench:{alias}",
                    instance=inst,
                    auto_close=False,
                )

    # Context management ------------------------------------------------
    def __enter__(self) -> MeasurementSession:  # noqa: D401
        """Synchronous context manager entry."""
        return self

    def __exit__(self, exc_type, exc, tb) -> Literal[False]:  # noqa: D401
        """Synchronous context manager exit."""
        # Directly call the synchronous disconnect method
        try:
            self._disconnect_all_devices()
        except Exception:  # noqa: BLE001
            pass  # Keep original error handling behavior
        return False

    # ─── Compliance ─────────────────────────────────────────────────────
    def _setup_compliance(self, compliance: Any | None) -> None:
        """Set up compliance features for this session.

        Args:
            compliance: None, True, or "required" (fail-closed auto setup);
                False or "disabled"; "best_effort"; or ComplianceConfig.
        """
        if compliance is False or compliance == "disabled":
            # Explicitly disabled
            self._compliance_mode = "disabled"
            self._compliance_config = None
            self._compliance_wrapper = None
            return

        best_effort = compliance == "best_effort"
        auto_configure = compliance is None or compliance is True or compliance == "required"
        self._compliance_mode = "best_effort" if best_effort else "required"

        if auto_configure or best_effort:
            try:
                from ..compliance.auto_config import ComplianceDisabledError
                from ..compliance.auto_config import ensure_compliance_config
                from ..compliance.session import ComplianceConfig

                config_dict = ensure_compliance_config()
                self._compliance_config = ComplianceConfig(**config_dict)
                if not best_effort:
                    self._validate_compliance_readiness(require_all=True)
                self._compliance_wrapper = self._compliance_config.create_compliance_wrapper()

            except ComplianceDisabledError:
                # Explicitly disabled via environment variable; silent disable.
                self._compliance_config = None
                self._compliance_wrapper = None
            except Exception as e:
                if not best_effort:
                    raise RuntimeError("Required compliance setup failed") from e
                _LOG.warning(
                    "Best-effort compliance setup failed: %s. Running without compliance features.",
                    e,
                )
                self._compliance_config = None
                self._compliance_wrapper = None
        else:
            # Custom compliance configuration provided
            from ..compliance.session import ComplianceConfig

            if not isinstance(compliance, ComplianceConfig):
                raise TypeError(
                    "compliance must be None, a bool, 'required', 'best_effort', "
                    "'disabled', or ComplianceConfig"
                )
            self._compliance_config = compliance
            if not compliance.enabled:
                self._compliance_mode = "disabled"
                self._compliance_wrapper = None
                return
            self._validate_compliance_readiness(require_all=False)
            self._compliance_wrapper = compliance.create_compliance_wrapper()

    def _validate_compliance_readiness(self, *, require_all: bool) -> None:
        """Raise when required or explicitly configured components are unavailable."""
        config = self._compliance_config
        if config is None:  # pragma: no cover - internal invariant
            raise RuntimeError("Compliance configuration is missing")
        readiness = config.readiness()
        required = (
            {"signed", "audited", "timestamped"}
            if require_all
            else {name for name, configured in readiness["configured"].items() if configured}
        )
        unavailable = sorted(name for name in required if not readiness[name])
        if readiness["errors"] or unavailable:
            details = "; ".join(
                [*readiness["errors"], *(f"{name} unavailable" for name in unavailable)]
            )
            raise RuntimeError(f"Compliance components are not ready: {details}")

    def verify_compliance(self) -> dict[str, Any]:
        """Verify compliance status of this session.

        Returns:
            Dictionary with compliance status information
        """
        if self._compliance_config is None:
            return {
                "enabled": False,
                "message": "Compliance not configured or disabled",
                "measurements": [],
            }

        measurements = []
        for name, _func in self._meas_funcs:
            measurements.append(
                {
                    "name": name,
                    # We apply the compliance wrapper at registration time.
                    # Avoid dynamic attributes on function objects.
                    "compliance_applied": self._compliance_wrapper is not None,
                    "config": None,
                }
            )

        return {
            "enabled": bool(self._compliance_config.enabled),
            "mode": self._compliance_mode,
            "config": {
                "signed": self._compliance_config.signer is not None,
                "audited": self._compliance_config.auditor is not None,
                "timestamped": self._compliance_config.timestamper is not None,
            },
            "measurements": measurements,
        }

    # ─── Devices / Instruments ────────────────────────────────────────
    def device(self, alias: str, config_key: str, /, **kw) -> Any:
        if alias in self._devices:
            record = self._devices[alias]
            if not record.resource.startswith("bench:"):
                raise ValueError(f"Device alias '{alias}' already in use.")
            return record.instance
        if self._bench:
            raise ValueError(
                f"Device '{alias}' not found on the bench. "
                "When using a bench, all devices must be defined in the bench configuration."
            )
        from ..devices import AutoDevice as _AutoDevice

        inst = _AutoDevice.from_config(config_key, **kw)
        self._devices[alias] = _DeviceRecord(alias, config_key, inst)
        return inst

    def instrument(self, alias: str, config_key: str, /, **kw) -> Any:
        if alias in self._devices:
            record = self._devices[alias]
            if not record.resource.startswith("bench:"):
                raise ValueError(f"Instrument alias '{alias}' already in use.")
            from ..instruments import Instrument as _Instrument

            is_instrument = getattr(
                record.instance, "is_instrument", isinstance(record.instance, _Instrument)
            )
            if not is_instrument:
                raise TypeError(f"Bench resource '{alias}' is a device, not an Instrument.")
            return record.instance
        if self._bench:
            raise ValueError(
                f"Instrument '{alias}' not found on the bench. "
                "When using a bench, all devices must be defined in the bench configuration."
            )
        from ..instruments import AutoInstrument as _AutoInstrument

        inst = _AutoInstrument.from_config(config_key, **kw)
        self._devices[alias] = _DeviceRecord(alias, config_key, inst)
        return inst

    # ─── Parameters ────────────────────────────────────────────────────
    def parameter(
        self, name: str, values: T_ParamIterable, /, *, unit: str | None = None, notes: str = ""
    ) -> None:
        if name in self._parameters:
            raise ValueError(f"Parameter '{name}' already exists.")
        if isinstance(values, StepSpec):
            resolved = values.values()
        elif callable(values) and not isinstance(values, list | tuple | np.ndarray):
            resolved = list(values())
        else:
            resolved = list(values)
        self._parameters[name] = _Parameter(name, resolved, unit, notes)

    # ─── Measurement registration ─────────────────────────────────────
    def acquire(
        self, func: T_MeasFunc | None = None, /, *, name: str | None = None
    ) -> T_MeasFunc | Callable[[T_MeasFunc], T_MeasFunc]:
        """Register a measurement function.

        If compliance is enabled for this session, the function is automatically
        wrapped with signing, auditing, and timestamping decorators.

        Args:
            func: The measurement function to register
            name: Optional name override for the measurement

        Returns:
            The original function (for introspection), but a wrapped version
            is stored internally if compliance is enabled.
        """
        if func is None:  # decorator usage
            return lambda f: self.acquire(f, name=name)

        func_name = getattr(func, "__name__", func.__class__.__name__)
        reg_name = name or func_name
        if any(n == reg_name for n, _ in self._meas_funcs):
            raise ValueError(f"Measurement '{reg_name}' already registered.")

        # Apply compliance wrapper if configured
        if self._compliance_wrapper:
            wrapped_func = self._compliance_wrapper(func)
        else:
            wrapped_func = func

        self._meas_funcs.append((reg_name, wrapped_func))
        return func  # Return original for introspection

    # Backward-compat / ergonomics alias
    def measure(self, func: T_MeasFunc | None = None, /, *, name: str | None = None):
        """Alias for `acquire`.

        Many examples and users prefer `@session.measure`.
        """
        return self.acquire(func, name=name)

    def task(self, func: T_TaskFunc | None = None, /, *, name: str | None = None):
        """Decorator to register a function as a background task for parallel execution."""
        if func is None:  # decorator usage
            return lambda f: self.task(f, name=name)

        if not callable(func):
            raise TypeError("Only callable functions can be registered as tasks.")
        func_name = getattr(func, "__name__", func.__class__.__name__)
        reg_name = name or func_name
        self._tasks.append((reg_name, func))
        return func

    # ─── Execution ────────────────────────────────────────────────────
    def run(
        self,
        duration: float | None = None,
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

        self._data_rows = [{} for _ in range(len(combinations))]  # pre-allocate with empty dicts
        iterator = tqdm(
            enumerate(combinations),
            total=len(combinations),
            desc="Measurement sweep",
            disable=not show_progress,
        )

        for idx, combo in iterator:
            param_ctx = dict(zip(names, combo, strict=True))
            # Create row with explicit Any typing to allow any measurement values
            row: dict[str, Any] = {}
            row.update(param_ctx)
            row["timestamp"] = time.time()

            for meas_name, func in self._meas_funcs:
                sig = inspect.signature(func)
                kwargs: dict[str, Any] = {n: v for n, v in param_ctx.items() if n in sig.parameters}
                for alias, inst_rec in self._devices.items():
                    if alias in sig.parameters:
                        kwargs[alias] = inst_rec.instance
                if "ctx" in sig.parameters:
                    kwargs["ctx"] = row
                res = self._normalize_measurement_output(meas_name, func(**kwargs))
                for key, val in res.items():
                    if isinstance(key, str) and key.startswith("__compliance_"):
                        continue
                    col = key if key not in row else f"{meas_name}.{key}"
                    self._store_measurement_value(row, col, val)

            self._data_rows[idx] = row  # assign Dict[str, Any] to slot

        self._has_run = True
        self._build_experiment()
        if self._bench and self._bench.db:
            self._bench.save_experiment()
        if self._experiment is None:
            raise RuntimeError("Experiment was not created.")
        return self._experiment

    def _run_parallel(
        self, duration: float | None, interval: float, show_progress: bool
    ) -> Experiment:
        """Executes registered background tasks and acquisition loops concurrently."""
        if not self._meas_funcs:
            raise RuntimeError("Parallel execution mode requires at least one @acquire function.")
        if duration is None or duration <= 0:
            raise ValueError("Parallel execution mode requires a positive 'duration' in seconds.")

        self._data_rows = []
        running_threads = []
        stop_event = threading.Event()

        # 1. Prepare and start background stimulus tasks
        for task_name, task_func in self._tasks:
            sig = inspect.signature(task_func)
            kwargs = {
                alias: rec.instance
                for alias, rec in self._devices.items()
                if alias in sig.parameters
            }
            # Add stop_event to kwargs if the function accepts it
            if "stop_event" in sig.parameters:
                kwargs["stop_event"] = stop_event

            # Create a wrapper that handles the stop_event
            def task_wrapper(func=task_func, kw=kwargs, _task_name=task_name):
                """
                Wrapper to execute a background task, safely binding the loop
                variable 'task_name' via default argument (_task_name) to avoid
                late binding in closures.
                """
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
                        print(f"Background task '{_task_name}' failed: {e}")

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
            row: dict[str, Any] = {"timestamp": time.time()}
            for meas_name, func in self._meas_funcs:
                sig = inspect.signature(func)
                kwargs = {
                    alias: rec.instance
                    for alias, rec in self._devices.items()
                    if alias in sig.parameters
                }
                if "ctx" in sig.parameters:
                    kwargs["ctx"] = row
                res = self._normalize_measurement_output(meas_name, func(**kwargs))
                for key, val in res.items():
                    self._store_measurement_value(row, key, val)
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
    @staticmethod
    def _normalize_measurement_output(
        measurement_name: str, result: Mapping[str, Any] | MeasurementResult
    ) -> Mapping[str, Any]:
        if isinstance(result, MeasurementResult):
            return {measurement_name: result}
        if isinstance(result, Mapping):
            return result
        raise TypeError(
            f"Measurement '{measurement_name}' returned {type(result)}, "
            "expected Mapping or MeasurementResult."
        )

    @staticmethod
    def _store_measurement_value(row: dict[str, Any], column: str, value: Any) -> None:
        """Keep numeric columns usable while retaining full metrology metadata."""

        result_metadata: dict[str, Any] | None = None
        raw_value = value
        if isinstance(value, MeasurementResult):
            raw_value = value.values
            result_metadata = {
                "instrument": value.instrument,
                "units": value.units,
                "measurement_type": value.measurement_type,
                "timestamp": value.timestamp,
                "envelope": value.envelope,
                "sampling_rate": value.sampling_rate,
            }

        serialized, uncertainty_metadata = serialize_uncertain_value(raw_value)
        value_kind = uncertainty_metadata.get("value_kind")
        if value_kind == "quantity":
            row[column] = float(np.asarray(serialized).flat[0])
        elif value_kind == "quantity_array":
            row[column] = np.asarray(serialized).tolist()
        elif value_kind in {"quantity_ndarray", "quantity_list"}:
            row[column] = np.asarray(serialized)[..., 0].tolist()
        else:
            row[column] = serialized

        if uncertainty_metadata or result_metadata is not None:
            row[f"{column}__measurement"] = json.dumps(
                {
                    "schema_version": "1.0",
                    "result": result_metadata,
                    "uncertainty": uncertainty_metadata,
                },
                sort_keys=True,
                default=str,
            )

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

    def _disconnect_all_devices(self) -> None:
        for rec in self._devices.values():
            if not rec.auto_close:
                continue
            try:
                close_method = getattr(rec.instance, "close", None)
                if callable(close_method):
                    close_method()
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

    # Plotting convenience ------------------------------------------------
    def plot(self, spec: PlotSpec | None = None, **kwargs: Any) -> Any:
        """
        Plot the current session data (if any). Typically called after run().

        Args:
            spec: Optional PlotSpec. If not provided, one is created from kwargs.
            **kwargs: Fields for PlotSpec (kind, x, y, title, xlabel, ylabel, legend, grid).

        Returns:
            A matplotlib Figure object.
        """
        from ..plotting import PlotSpec  # local import to keep plotting optional
        from ..plotting import plot_dataframe  # local import to keep plotting optional

        df = self.data
        if df.is_empty():
            raise ValueError(
                "Session has no data yet. Call run() first or ensure measurements produced rows."
            )

        spec_to_use = spec or (PlotSpec(**kwargs) if kwargs else PlotSpec())
        return plot_dataframe(df, spec_to_use)


# Convenience alias – shorter name
Measurement = MeasurementSession
