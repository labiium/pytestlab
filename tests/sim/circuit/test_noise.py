from __future__ import annotations

import numpy as np
import pytest

from pytestlab.sim.circuit.determinism import make_rng
from pytestlab.sim.circuit.noise import NoiseConfig
from pytestlab.sim.circuit.noise import NoisePreset
from pytestlab.sim.circuit.noise import apply_layer2_noise
from pytestlab.sim.circuit.noise import noise_config_from_preset


def test_noise_seed_required() -> None:
    with pytest.raises(ValueError):
        NoiseConfig(preset=NoisePreset.TYPICAL)


def test_noise_reproducible_with_seed() -> None:
    cfg = noise_config_from_preset(NoisePreset.TYPICAL, seed=123)
    first = apply_layer2_noise(np.ones(8), config=cfg, rng=make_rng(123))
    second = apply_layer2_noise(np.ones(8), config=cfg, rng=make_rng(123))
    np.testing.assert_allclose(first, second)


def test_bad_ground_includes_hum() -> None:
    cfg = noise_config_from_preset(NoisePreset.BAD_GROUND, seed=123)
    t = np.arange(1000) / 1000.0
    noisy = apply_layer2_noise(np.zeros_like(t), config=cfg, rng=make_rng(123), time_axis=t)
    assert float(np.ptp(noisy)) > 0.01
