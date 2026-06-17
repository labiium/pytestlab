from __future__ import annotations

import pytest

from pytestlab.sim.circuit.calibration import transition_boundaries
from pytestlab.sim.circuit.calibration import transition_boundary_error
from pytestlab.sim.circuit.calibration import two_transistor_validation_metrics


def test_transition_boundaries_use_state_changes() -> None:
    boundaries = transition_boundaries(
        [
            (0.0, "PULLED_HIGH"),
            (1.0, "PULLED_HIGH"),
            (2.0, "INVERTING"),
            (3.0, "SATURATED_LOW"),
        ]
    )

    assert boundaries == {
        "PULLED_HIGH->INVERTING": 1.5,
        "INVERTING->SATURATED_LOW": 2.5,
    }


def test_transition_boundary_error_reports_mae_and_max() -> None:
    measured = [(0.0, "PULLED_HIGH"), (1.0, "INVERTING"), (2.0, "SATURATED_LOW")]
    simulated = [(0.0, "PULLED_HIGH"), (1.2, "INVERTING"), (2.4, "SATURATED_LOW")]

    metrics = transition_boundary_error(
        measured,
        simulated,
        mae_threshold_v=0.2,
        max_threshold_v=0.3,
    )

    by_name = {metric.name: metric for metric in metrics}
    assert by_name["transition_boundary_mae_v"].value == pytest.approx(0.2)
    assert by_name["transition_boundary_mae_v"].passed is True
    assert by_name["transition_boundary_max_error_v"].value == pytest.approx(0.3)


def test_transition_boundary_error_fails_on_missing_transition() -> None:
    measured = [(0.0, "PULLED_HIGH"), (1.0, "INVERTING"), (2.0, "SATURATED_LOW")]
    simulated = [(0.0, "PULLED_HIGH"), (1.0, "PULLED_HIGH"), (2.0, "SATURATED_LOW")]

    with pytest.raises(ValueError, match="missing transition boundary"):
        transition_boundary_error(measured, simulated)


def test_two_transistor_validation_metrics_cover_first_scope() -> None:
    metrics = two_transistor_validation_metrics(
        measured_vout_v=[5.0, 2.5, 0.2],
        simulated_vout_v=[4.95, 2.55, 0.25],
        measured_current_ma=[0.5, 2.0, 4.0],
        simulated_current_ma=[0.55, 2.05, 4.05],
        measured_states=["PULLED_HIGH", "INVERTING", "SATURATED_LOW"],
        simulated_states=["PULLED_HIGH", "INVERTING", "SATURATED_LOW"],
        measured_bias_states=[
            (0.0, "PULLED_HIGH"),
            (1.0, "INVERTING"),
            (2.0, "SATURATED_LOW"),
        ],
        simulated_bias_states=[
            (0.0, "PULLED_HIGH"),
            (1.1, "INVERTING"),
            (2.2, "SATURATED_LOW"),
        ],
        thresholds={
            "vout_mae_v": 0.1,
            "supply_current_mae_ma": 0.1,
            "state_classification_accuracy": 1.0,
            "transition_boundary_mae_v": 0.11,
            "transition_boundary_max_error_v": 0.2,
        },
    )

    by_name = {metric.name: metric for metric in metrics}
    assert set(by_name) == {
        "vout_mae_v",
        "supply_current_mae_ma",
        "state_classification_accuracy",
        "transition_boundary_mae_v",
        "transition_boundary_max_error_v",
    }
    assert all(metric.passed for metric in metrics)
