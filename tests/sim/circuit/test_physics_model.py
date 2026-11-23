from __future__ import annotations

import numpy as np

from pytestlab.sim.circuit import LinearModel
from pytestlab.sim.circuit.spice import AcSweepSpec
from pytestlab.sim.circuit.spice import simulate_ac
from pytestlab.sim.circuit.spice import simulate_op


class DummySession:
    physics_models = {"vin->vout": LinearModel(gain=2.0, pole_hz=10_000.0)}

    class Wiring:
        ground_node = "0"

    wiring = Wiring()


def test_linear_model_dc_bypasses_spice() -> None:
    result = simulate_op(DummySession(), ["vout"], params={"vin": 1.5})
    assert float(result.node_voltages["vout"][0]) == 3.0
    assert result.metadata["engine"] == "physics_model"


def test_linear_model_frequency_response() -> None:
    result = simulate_ac(DummySession(), ["vout"], AcSweepSpec(points=3, start_hz=10, stop_hz=1000))
    assert np.iscomplexobj(result.node_voltages["vout"])
    assert result.metadata["engine"] == "physics_model"
