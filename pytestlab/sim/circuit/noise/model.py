from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np


class NoisePreset(str, Enum):  # noqa: UP042 - keep str(Enum) semantics for compatibility.
    NONE = "none"
    IDEAL = "ideal"
    TYPICAL = "typical"
    BAD_GROUND = "bad_ground"


@dataclass(frozen=True)
class NoiseConfig:
    preset: NoisePreset = NoisePreset.NONE
    seed: int | None = None
    accuracy_ppm: float = 0.0
    cable_pickup_vrms: float = 0.0
    mains_hum_vrms: float = 0.0
    mains_freq_hz: float = 50.0
    enable_spice_noise: bool = False

    def __post_init__(self) -> None:
        if self.preset != NoisePreset.NONE and self.seed is None:
            raise ValueError(
                f"NoiseConfig preset={self.preset} requires an explicit seed for CI reproducibility."
            )


def noise_config_from_preset(preset: NoisePreset | str, *, seed: int | None = None) -> NoiseConfig:
    selected = preset if isinstance(preset, NoisePreset) else NoisePreset(str(preset))
    if selected == NoisePreset.NONE:
        return NoiseConfig(preset=selected, seed=seed)
    if seed is None:
        raise ValueError(
            f"NoiseConfig preset={selected} requires an explicit seed for CI reproducibility."
        )
    if selected == NoisePreset.IDEAL:
        return NoiseConfig(preset=selected, seed=seed, enable_spice_noise=True)
    if selected == NoisePreset.TYPICAL:
        return NoiseConfig(
            preset=selected,
            seed=seed,
            accuracy_ppm=50.0,
            cable_pickup_vrms=25e-6,
            enable_spice_noise=True,
        )
    if selected == NoisePreset.BAD_GROUND:
        return NoiseConfig(
            preset=selected,
            seed=seed,
            accuracy_ppm=250.0,
            cable_pickup_vrms=1e-3,
            mains_hum_vrms=10e-3,
            mains_freq_hz=50.0,
            enable_spice_noise=True,
        )
    raise ValueError(f"unsupported noise preset: {preset!r}")


def apply_layer2_noise(
    value,
    *,
    config: NoiseConfig,
    rng: np.random.Generator,
    time_axis=None,
):
    if config.preset == NoisePreset.NONE:
        return value

    arr = np.asarray(value, dtype=float)
    noisy = arr.copy()

    if config.accuracy_ppm:
        gain = 1.0 + rng.normal(0.0, abs(config.accuracy_ppm) * 1e-6)
        noisy = noisy * gain

    if config.cable_pickup_vrms:
        noisy = noisy + rng.normal(0.0, abs(config.cable_pickup_vrms), size=noisy.shape)

    if config.mains_hum_vrms and time_axis is not None:
        t = np.asarray(time_axis, dtype=float)
        phase = rng.uniform(0.0, 2.0 * np.pi)
        hum_amp = abs(config.mains_hum_vrms) * np.sqrt(2.0)
        noisy = noisy + hum_amp * np.sin(2.0 * np.pi * config.mains_freq_hz * t + phase)

    if np.isscalar(value):
        return float(noisy)
    return noisy
