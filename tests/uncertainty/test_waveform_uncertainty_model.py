from __future__ import annotations

import math

import numpy as np
import pytest

from pytestlab.uncertainty import WaveformUncertaintyModel
from pytestlab.uncertainty import build_waveform_quantity_array
from pytestlab.uncertainty.metrology import report_grade_blockers
from pytestlab.uncertainty.specs import AccuracySpec


def test_waveform_model_vectorizes_shared_gain_offset_and_quantization() -> None:
    samples = np.array([1.0, 2.0, 3.0])
    model = WaveformUncertaintyModel.from_metadata(
        {
            "unit": "V",
            "resolution": 0.001,
            "source_key": "scope:ch1",
            "accuracy_spec": AccuracySpec(
                reading_fraction=0.01,
                offset=0.02,
                distribution="standard",
            ),
        },
        samples=samples,
        unit="V",
        channel=1,
    )

    arr = model.quantity_array(samples)

    expected_u0 = math.sqrt(0.01**2 + 0.02**2 + (0.001 / math.sqrt(12.0)) ** 2)
    expected_u2 = math.sqrt(0.03**2 + 0.02**2 + (0.001 / math.sqrt(12.0)) ** 2)
    assert arr.u[0] == pytest.approx(expected_u0)
    assert arr.u[2] == pytest.approx(expected_u2)
    assert len(arr.atom_sensitivities) == 2
    assert arr.measurement_model.function == "oscilloscope_waveform(samples, uncertainty_model)"

    mean = arr.mean()
    expected_mean_u = math.sqrt(
        (np.mean(samples) * 0.01) ** 2 + 0.02**2 + ((0.001 / math.sqrt(12.0)) ** 2) / len(samples)
    )
    assert mean.u == pytest.approx(expected_mean_u)


def test_waveform_model_scales_without_dense_covariance() -> None:
    samples = np.linspace(-1.0, 1.0, 1_000_000)
    arr = build_waveform_quantity_array(
        samples,
        {
            "unit": "V",
            "resolution": 0.001,
            "accuracy_spec": AccuracySpec(reading_fraction=0.005, offset=0.001),
        },
    )

    assert arr.mean().u > 0.0
    assert arr.rms().u > 0.0
    with pytest.raises(ValueError, match="Dense covariance"):
        arr.covariance_matrix()


def test_unresolved_dof_is_report_grade_blocker() -> None:
    arr = build_waveform_quantity_array([1.0, 2.0], {"unit": "V", "resolution": 0.1})

    blockers = report_grade_blockers(arr)

    assert any("degrees-of-freedom method is unresolved" in blocker for blocker in blockers)
