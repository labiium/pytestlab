from __future__ import annotations

import math

import numpy as np
import pytest

from pytestlab.instruments.waveform_result import WaveformResult
from pytestlab.uncertainty import DataOrigin
from pytestlab.uncertainty import EvidencePurpose
from pytestlab.uncertainty import QuantityArray
from pytestlab.uncertainty import ResultProvenance
from pytestlab.uncertainty import TimingMeasurementError
from pytestlab.uncertainty import WaveformAxis
from pytestlab.uncertainty import WaveformUncertaintyModel
from pytestlab.uncertainty import period_from_edges
from pytestlab.uncertainty import threshold_crossing_time


def _measured_model(**axis_kwargs: float | str | None) -> WaveformUncertaintyModel:
    return WaveformUncertaintyModel(
        unit="V",
        traceability=None,
        independent_noise_std=0.0,
        axis=WaveformAxis(**axis_kwargs),
        data_origin=DataOrigin.MEASURED,
        evidence_purpose=EvidencePurpose.MEASUREMENT_RESULT,
        provenance_complete=True,
    )


def test_threshold_crossing_propagates_voltage_noise_to_time() -> None:
    wave = QuantityArray.from_samples([0.0, 1.0], unit="V", independent_std=0.1)
    wave.provenance = ResultProvenance.current(
        data_origin=DataOrigin.MEASURED,
        evidence_purpose=EvidencePurpose.MEASUREMENT_RESULT,
        provenance_complete=True,
    )

    crossing = threshold_crossing_time([0.0, 1.0], wave, 0.5)

    assert crossing.nominal == pytest.approx(0.5)
    assert crossing.unit == "s"
    assert crossing.u == pytest.approx(math.sqrt(0.005))
    assert crossing.measurement_model is not None
    assert "inverse slew rate" in " ".join(crossing.measurement_model.assumptions)


def test_period_cancels_shared_trigger_jitter_but_keeps_timebase_scale() -> None:
    model = _measured_model(
        sample_interval_s=1.0,
        trigger_jitter_std_s=0.1,
        timebase_relative_std=1e-3,
        sample_aperture_s=1e-12,
    )
    wave = WaveformResult([0.0, 1.0, 0.0, 1.0], time=[0.0, 1.0, 2.0, 3.0], model=model)

    period = wave.timing.period()
    frequency = wave.timing.frequency()

    assert period.nominal == pytest.approx(2.0)
    assert period.u == pytest.approx(2e-3)
    assert frequency.nominal == pytest.approx(0.5)
    assert frequency.u == pytest.approx(5e-4)
    assert period.measurement_model is not None
    assert period.measurement_model.output_name == "period"


def test_rise_fall_and_duty_cycle_are_low_burden_waveform_methods() -> None:
    model = _measured_model(sample_interval_s=1.0, timebase_relative_std=0.0)
    wave = WaveformResult(
        [0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 1.0],
        time=np.arange(7, dtype=float),
        model=model,
    )

    assert wave.timing.rise_time().nominal == pytest.approx(0.8)
    assert wave.timing.fall_time().nominal == pytest.approx(0.8)
    assert wave.timing.duty_cycle().nominal == pytest.approx(0.5)


def test_timing_fails_loudly_without_unambiguous_edge() -> None:
    with pytest.raises(TimingMeasurementError, match="No rising threshold crossing"):
        period_from_edges([0.0, 1.0, 2.0], [0.0, 0.1, 0.2], level=0.5)
