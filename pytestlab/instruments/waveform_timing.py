"""User-facing timing reductions for :class:`WaveformResult`."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pytestlab.uncertainty.timing import Edge
from pytestlab.uncertainty.timing import TimingEstimator
from pytestlab.uncertainty.timing import TimingMeasurementError
from pytestlab.uncertainty.timing import TimingUncertaintyModel

if TYPE_CHECKING:  # pragma: no cover
    from pytestlab.uncertainty import Quantity

    from .waveform_result import WaveformResult


class WaveformTiming:
    """Low-burden oscilloscope timing API backed by uncertainty propagation."""

    def __init__(self, waveform: WaveformResult) -> None:
        self._waveform = waveform

    def estimator(self) -> TimingEstimator:
        wave = self._waveform
        return TimingEstimator(
            wave.quantity_array(),
            time=wave.time,
            axis=wave.model.axis,
            model=TimingUncertaintyModel.from_axis(
                wave.model.axis,
                traceability=wave.model.traceability,
                source_key=wave.model.source_key,
            ),
            channel=wave.channel,
        )

    def threshold(self, level: float, *, edge: Edge = "rising", occurrence: int = 0) -> Quantity:
        return self.estimator().threshold_crossing_time(
            level,
            edge=edge,
            occurrence=occurrence,
        )

    def period(
        self, *, level: float | None = None, edge: Edge = "rising", cycle: int = 0
    ) -> Quantity:
        return self.estimator().period(level=level, edge=edge, cycle=cycle)

    def frequency(
        self, *, level: float | None = None, edge: Edge = "rising", cycle: int = 0
    ) -> Quantity:
        return self.estimator().frequency(level=level, edge=edge, cycle=cycle)

    def rise_time(self, *, low: float = 0.1, high: float = 0.9, occurrence: int = 0) -> Quantity:
        return self.estimator().rise_time(low=low, high=high, occurrence=occurrence)

    def fall_time(self, *, low: float = 0.1, high: float = 0.9, occurrence: int = 0) -> Quantity:
        return self.estimator().fall_time(low=low, high=high, occurrence=occurrence)

    def duty_cycle(self, *, level: float | None = None, cycle: int = 0) -> Quantity:
        return self.estimator().duty_cycle(level=level, cycle=cycle)

    def delay(
        self, other: WaveformResult, *, level: float | None = None, edge: Edge = "rising"
    ) -> Quantity:
        if self._waveform.time is None or other.time is None:
            raise TimingMeasurementError("Delay requires explicit time axes for both waveforms.")
        return self.estimator().delay(WaveformTiming(other).estimator(), level=level, edge=edge)
