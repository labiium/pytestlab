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
        """Return the timing estimator backing these measurements."""
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
        """Find when the waveform crosses a voltage level.


        Args:
            level: Threshold voltage to detect.
            edge: Which crossing direction to look for.
            occurrence: Which crossing to return, zero-based.

        Returns:
            The crossing time in seconds, with uncertainty.
        """
        return self.estimator().threshold_crossing_time(
            level,
            edge=edge,
            occurrence=occurrence,
        )

    def period(
        self, *, level: float | None = None, edge: Edge = "rising", cycle: int = 0
    ) -> Quantity:
        """Measure the waveform period in seconds, with uncertainty."""
        return self.estimator().period(level=level, edge=edge, cycle=cycle)

    def frequency(
        self, *, level: float | None = None, edge: Edge = "rising", cycle: int = 0
    ) -> Quantity:
        """Measure the waveform frequency in Hz, with uncertainty."""
        return self.estimator().frequency(level=level, edge=edge, cycle=cycle)

    def rise_time(self, *, low: float = 0.1, high: float = 0.9, occurrence: int = 0) -> Quantity:
        """Measure the rising edge transition time in seconds, with uncertainty.


        Args:
            low: Lower threshold as a fraction of amplitude.
            high: Upper threshold as a fraction of amplitude.
            occurrence: Which edge to measure, zero-based.
        """
        return self.estimator().rise_time(low=low, high=high, occurrence=occurrence)

    def fall_time(self, *, low: float = 0.1, high: float = 0.9, occurrence: int = 0) -> Quantity:
        """Measure the falling edge transition time in seconds, with uncertainty.


        Args:
            low: Lower threshold as a fraction of amplitude.
            high: Upper threshold as a fraction of amplitude.
            occurrence: Which edge to measure, zero-based.
        """
        return self.estimator().fall_time(low=low, high=high, occurrence=occurrence)

    def duty_cycle(self, *, level: float | None = None, cycle: int = 0) -> Quantity:
        """Measure the duty cycle as a fraction of the period, with uncertainty."""
        return self.estimator().duty_cycle(level=level, cycle=cycle)

    def delay(
        self, other: WaveformResult, *, level: float | None = None, edge: Edge = "rising"
    ) -> Quantity:
        """Measure the delay between this waveform and another, in seconds.


        Use this to compare the phase or timing of two captured channels.

        Args:
            other: The waveform to compare against.
        """
        if self._waveform.time is None or other.time is None:
            raise TimingMeasurementError("Delay requires explicit time axes for both waveforms.")
        return self.estimator().delay(WaveformTiming(other).estimator(), level=level, edge=edge)
