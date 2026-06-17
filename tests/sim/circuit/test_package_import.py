from __future__ import annotations

import importlib


def test_package_import_smoke() -> None:
    package = importlib.import_module("pytestlab.sim.circuit")

    assert package.__doc__
    assert "SimSession" in package.__all__


def test_circuit_lane_lives_under_pytestlab_sim_namespace() -> None:
    # The circuit simulator is a lane of the PyTestLab simulators feature, not a
    # standalone package; importing it brings in the pytestlab namespace.
    circuit = importlib.import_module("pytestlab.sim.circuit")
    sim = importlib.import_module("pytestlab.sim")

    assert circuit.__name__ == "pytestlab.sim.circuit"
    assert sim.__doc__  # the simulators feature namespace is documented
