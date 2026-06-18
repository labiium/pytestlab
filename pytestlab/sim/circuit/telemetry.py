from __future__ import annotations

import json
import time
from collections import defaultdict
from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from typing import cast

try:  # optional OpenTelemetry integration
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.trace.export import ConsoleSpanExporter

    _OTEL_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    _OTEL_AVAILABLE = False
    trace = None

from .store import ArtifactStore


@dataclass
class MetricSummary:
    count: int
    p50: float
    p95: float
    p99: float
    minimum: float
    maximum: float


class MetricStore:
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
    def __init__(self, store: ArtifactStore, *, events_path: Path | None = None) -> None:
        self.store = store
        self.metrics = MetricStore()
        self.events_path = events_path or (store.root / "events.jsonl")
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        self._tracer = None
        if _OTEL_AVAILABLE:
            provider = TracerProvider(resource=Resource.create({"service.name": "simbench"}))
            provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
            otel_trace = cast(Any, trace)
            otel_trace.set_tracer_provider(provider)
            self._tracer = otel_trace.get_tracer("simbench")

    def emit(self, event: str, payload: dict[str, Any]) -> None:
        record = {
            "event": event,
            "timestamp": time.time(),
            "payload": payload,
        }
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")

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
        with cast(Any, self._tracer).start_as_current_span(name) as span:
            if attributes:
                for key, value in attributes.items():
                    span.set_attribute(key, value)
            try:
                yield
            finally:
                duration = time.perf_counter() - start
                self.metrics.observe(name, duration)
                span.set_attribute("duration_s", duration)


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
