from __future__ import annotations

import numpy as np

from pytestlab.sim.circuit.analysis import bode_from_ac_result
from pytestlab.sim.circuit.analysis import compute_spectrum
from pytestlab.sim.circuit.analysis import phasor_extract
from pytestlab.sim.circuit.analysis import rise_time_10_90
from pytestlab.sim.circuit.analysis import settling_time
from pytestlab.sim.circuit.analysis import thd_n_from_spectrum
from pytestlab.sim.circuit.spice import SpiceResult


def test_rise_time_and_settling_time() -> None:
    time = np.linspace(0.0, 1.0, 101)
    voltage = np.clip((time - 0.1) / 0.4, 0.0, 1.0)

    assert np.isclose(rise_time_10_90(time, voltage), 0.32)
    assert settling_time(time, voltage, threshold=0.02, final=1.0) is not None


def test_phasor_extract_recovers_sine_amplitude() -> None:
    sample_rate = 20_000.0
    time = np.arange(0.0, 0.1, 1.0 / sample_rate)
    voltage = 2.0 * np.sin(2.0 * np.pi * 1_000.0 * time)

    phasor = phasor_extract(time, voltage, 1_000.0)
    assert np.isclose(abs(phasor), 2.0, atol=1e-12)


def test_bode_from_ac_result() -> None:
    result = SpiceResult(
        analysis="ac",
        scale=np.asarray([10.0, 100.0]),
        scale_unit="Hz",
        node_voltages={
            "vin": np.asarray([1.0 + 0.0j, 1.0 + 0.0j]),
            "vout": np.asarray([1.0 + 0.0j, 0.0 - 1.0j]),
        },
        source_currents={},
        sources=(),
    )

    bode = bode_from_ac_result(result, input_node="vin", output_node="vout")
    assert np.isclose(bode.magnitude_db, [0.0, 0.0]).all()
    assert np.isclose(bode.phase_deg, [0.0, -90.0]).all()


def test_compute_spectrum_and_thd() -> None:
    sample_rate = 20_000.0
    time = np.arange(0.0, 1.0, 1.0 / sample_rate)
    voltage = np.sin(2.0 * np.pi * 1_000.0 * time) + 0.1 * np.sin(2.0 * np.pi * 2_000.0 * time)

    spectrum = compute_spectrum(time, voltage, window="rect")
    metrics = thd_n_from_spectrum(spectrum, n_harmonics=3)
    assert np.isclose(metrics["thd"], 0.1, atol=1e-3)

    pure = compute_spectrum(time, np.sin(2.0 * np.pi * 1_000.0 * time), window="rect")
    assert thd_n_from_spectrum(pure, n_harmonics=3)["thd"] < 1e-12
