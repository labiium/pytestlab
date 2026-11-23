from __future__ import annotations

import json
import time
import uuid
from collections import defaultdict
from collections import deque
from collections.abc import Callable
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .spice import AcSweepSpec
from .spice import DcSweepSpec
from .spice import KernelSettings
from .spice import SpiceResult
from .store import ArtifactStore


@dataclass
class MetricSummary:
    """Count, percentile, and range summary for one telemetry metric."""

    count: int
    p50: float
    p95: float
    p99: float
    minimum: float
    maximum: float


class MetricStore:
    """Bounded in-memory duration samples with percentile summaries by metric name."""

    def __init__(self, max_samples: int = 10_000):
        self._samples: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=max_samples))

    def observe(self, name: str, value: float) -> None:
        self._samples[name].append(float(value))

    def summary(self, name: str) -> MetricSummary | None:
        samples = list(self._samples.get(name, []))
        if not samples:
            return None
        samples.sort()
        count = len(samples)
        return MetricSummary(
            count=count,
            p50=_percentile(samples, 50),
            p95=_percentile(samples, 95),
            p99=_percentile(samples, 99),
            minimum=samples[0],
            maximum=samples[-1],
        )


class Telemetry:
    """Persist circuit-simulation lifecycle events and duration metrics.

    OpenTelemetry integration is opt-in through an injected tracer; constructing
    this local recorder never mutates the host application's global tracer provider.
    """

    def __init__(
        self,
        store: ArtifactStore,
        *,
        events_path: Path | None = None,
        tracer: Any | None = None,
    ) -> None:
        self.store = store
        self.metrics = MetricStore()
        self.events_path = events_path or (store.root / "events.jsonl")
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        self._tracer = tracer

    def emit(self, event: str, payload: dict[str, Any]) -> None:
        record = {
            "event": event,
            "timestamp": time.time(),
            "payload": payload,
        }
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")

    def events(self) -> list[dict[str, Any]]:
        """Load all persisted events in emission order."""
        if not self.events_path.exists():
            return []
        text = self.events_path.read_text(encoding="utf-8")
        return [json.loads(line) for line in text.splitlines() if line]

    @contextmanager
    def span(self, name: str, *, attributes: dict[str, Any] | None = None) -> Iterator[None]:
        start = time.perf_counter()
        if self._tracer is None:
            try:
                yield
            finally:
                duration = time.perf_counter() - start
                self.metrics.observe(name, duration)
            return
        with self._tracer.start_as_current_span(name) as span:
            if attributes:
                for key, value in attributes.items():
                    span.set_attribute(key, value)
            try:
                yield
            finally:
                duration = time.perf_counter() - start
                self.metrics.observe(name, duration)
                span.set_attribute("duration_s", duration)


class TelemetryKernel:
    """Kernel adapter that records every circuit analysis at one boundary."""

    def __init__(self, kernel: Any, telemetry: Telemetry) -> None:
        self._kernel = kernel
        self.telemetry = telemetry

    def __getattr__(self, name: str) -> Any:
        return getattr(self._kernel, name)

    def _execute(
        self,
        analysis: str,
        session: Any,
        nodes: list[str],
        operation: Callable[[], SpiceResult],
    ) -> SpiceResult:
        run_id = uuid.uuid4().hex
        started = time.perf_counter()
        payload = _run_context(run_id, analysis, session, nodes, self._kernel)
        self.telemetry.emit("simulation.started", payload)
        try:
            with self.telemetry.span(
                f"simulation.{analysis}",
                attributes={"analysis": analysis, "run_id": run_id},
            ):
                result = operation()
        except Exception as exc:
            self.telemetry.emit(
                "simulation.failed",
                {
                    **payload,
                    "duration_s": time.perf_counter() - started,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )
            raise

        completed = {
            **payload,
            **_result_summary(result, analysis, nodes),
            "duration_s": time.perf_counter() - started,
        }
        self.telemetry.emit("simulation.completed", completed)
        return result

    def op(
        self,
        session: Any,
        nodes: list[str],
        *,
        params: dict[str, float] | None = None,
        settings: KernelSettings | None = None,
        currents: list[str] | None = None,
    ) -> SpiceResult:
        return self._execute(
            "op",
            session,
            nodes,
            lambda: self._kernel.op(
                session, nodes, params=params, settings=settings, currents=currents
            ),
        )

    def dc_sweep(
        self,
        session: Any,
        nodes: list[str],
        sweep: DcSweepSpec,
        *,
        params: dict[str, float] | None = None,
        settings: KernelSettings | None = None,
        currents: list[str] | None = None,
    ) -> SpiceResult:
        return self._execute(
            "dc",
            session,
            nodes,
            lambda: self._kernel.dc_sweep(
                session,
                nodes,
                sweep,
                params=params,
                settings=settings,
                currents=currents,
            ),
        )

    def ac(
        self,
        session: Any,
        nodes: list[str],
        sweep: AcSweepSpec,
        *,
        params: dict[str, float] | None = None,
        settings: KernelSettings | None = None,
        currents: list[str] | None = None,
    ) -> SpiceResult:
        return self._execute(
            "ac",
            session,
            nodes,
            lambda: self._kernel.ac(
                session,
                nodes,
                sweep,
                params=params,
                settings=settings,
                currents=currents,
            ),
        )

    def transient(
        self,
        session: Any,
        nodes: list[str],
        *,
        sample_rate: float,
        record_length: int,
        params: dict[str, float] | None = None,
        settings: KernelSettings | None = None,
        currents: list[str] | None = None,
    ) -> SpiceResult:
        return self._execute(
            "tran",
            session,
            nodes,
            lambda: self._kernel.transient(
                session,
                nodes,
                sample_rate=sample_rate,
                record_length=record_length,
                params=params,
                settings=settings,
                currents=currents,
            ),
        )


def _run_context(
    run_id: str,
    analysis: str,
    session: Any,
    nodes: list[str],
    kernel: Any,
) -> dict[str, Any]:
    metadata = getattr(session, "metadata", None)
    circuit = getattr(session, "circuit", None)
    circuit_hash = circuit.to_content_hash() if hasattr(circuit, "to_content_hash") else None
    return {
        "run_id": run_id,
        "session_id": getattr(metadata, "session_id", None),
        "analysis": analysis,
        "kernel": type(kernel).__name__,
        "circuit_hash": circuit_hash,
        "parameter_hash": getattr(session, "parameter_hash", None),
        "seed": getattr(session, "seed", None),
        "requested_nodes": list(nodes),
    }


def _result_summary(
    result: SpiceResult,
    expected_analysis: str,
    requested_nodes: list[str],
) -> dict[str, Any]:
    scale = np.asarray(result.scale)
    vectors = {
        **result.node_voltages,
        **result.source_currents,
        **result.element_currents,
    }
    shape_mismatches = sorted(
        name
        for name, values in vectors.items()
        if np.asarray(values).ndim != 1 or np.asarray(values).size != scale.size
    )
    missing_nodes = sorted(set(requested_nodes) - set(result.node_voltages))
    arrays = [scale, *(np.asarray(values) for values in vectors.values())]
    nonfinite_count = sum(int(np.count_nonzero(~np.isfinite(values))) for values in arrays)
    issues: list[str] = []
    if result.analysis != expected_analysis:
        issues.append(f"analysis mismatch: {result.analysis}")
    if scale.ndim != 1 or scale.size == 0:
        issues.append("empty or non-vector scale")
    if missing_nodes:
        issues.append("missing requested nodes")
    if shape_mismatches:
        issues.append("vector length mismatch")
    if nonfinite_count:
        issues.append("non-finite output")
    return {
        "engine": result.metadata.get("engine"),
        "sample_count": int(scale.size),
        "returned_nodes": sorted(result.node_voltages),
        "missing_nodes": missing_nodes,
        "shape_mismatches": shape_mismatches,
        "nonfinite_count": nonfinite_count,
        "status": "pass" if not issues else "warning",
        "issues": issues,
        "result_metadata": dict(result.metadata),
    }


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    if pct <= 0:
        return sorted_values[0]
    if pct >= 100:
        return sorted_values[-1]
    rank = (pct / 100) * (len(sorted_values) - 1)
    low = int(rank)
    high = min(low + 1, len(sorted_values) - 1)
    if low == high:
        return sorted_values[low]
    weight = rank - low
    return sorted_values[low] * (1.0 - weight) + sorted_values[high] * weight
