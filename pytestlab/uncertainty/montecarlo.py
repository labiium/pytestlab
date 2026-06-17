"""JCGM 101 (GUM Supplement 1) Monte Carlo propagation.

A measurement model ``func`` is evaluated over samples of the input quantities.
Each input :class:`Quantity` is exactly linear in the atom space, so its samples
are drawn from the atoms' distributions (with correlations); ``func`` itself may
be arbitrarily nonlinear and is propagated exactly by the sampling.

Provides: correlated sampling (independent per-distribution draws, or a
multivariate-normal fallback when off-diagonal covariances are present), the
shortest 95 % coverage interval (§7.7), and the adaptive procedure (§7.9.4).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable
from typing import Mapping

import numpy as np

from .atoms import AtomRegistry
from .atoms import Distribution
from .atoms import default_registry
from .quantity import Quantity


@dataclass
class MonteCarloResult:
    """Outcome of a Monte Carlo propagation (JCGM 101 §7.5–7.8)."""

    mean: float
    std: float
    interval: tuple[float, float]
    confidence: float
    draws: int
    samples: np.ndarray | None = None

    @property
    def y(self) -> float:
        return self.mean

    @property
    def u(self) -> float:
        return self.std


def _sample_atom(
    rng: np.random.Generator, mean: float, std: float, distribution: Distribution, n: int
) -> np.ndarray:
    if std == 0:
        return np.full(n, mean)
    if distribution in (Distribution.NORMAL, Distribution.STANDARD, Distribution.STUDENT_T):
        return rng.normal(mean, std, n)
    if distribution == Distribution.RECTANGULAR:
        hw = std * math.sqrt(3.0)
        return rng.uniform(mean - hw, mean + hw, n)
    if distribution == Distribution.TRIANGULAR:
        hw = std * math.sqrt(6.0)
        return rng.triangular(mean - hw, mean, mean + hw, n)
    if distribution == Distribution.ARCSINE:
        hw = std * math.sqrt(2.0)
        return mean + hw * np.sin(2.0 * np.pi * rng.uniform(0.0, 1.0, n))
    if distribution == Distribution.CURVED_TRAPEZOID:
        hw = std * math.sqrt(6.0)
        return rng.triangular(mean - hw, mean, mean + hw, n)
    raise NotImplementedError(distribution)


def shortest_coverage_interval(samples: np.ndarray, confidence: float) -> tuple[float, float]:
    """Shortest interval containing ``confidence`` of the sorted samples (§7.7)."""

    ordered = np.sort(samples)
    n = ordered.size
    q = int(math.floor(confidence * n))
    if q >= n:
        return float(ordered[0]), float(ordered[-1])
    widths = ordered[q:] - ordered[: n - q]
    r = int(np.argmin(widths))
    return float(ordered[r]), float(ordered[r + q])


def _draw_atom_samples(
    registry: AtomRegistry, uids: list[str], rng: np.random.Generator, n: int
) -> dict[str, np.ndarray]:
    """Draw ``n`` samples for each atom, honouring declared correlations."""

    has_corr = any(
        a in uids and b in uids for (a, b) in registry._covariances
    )
    if not has_corr:
        return {
            uid: _sample_atom(
                rng,
                registry.atoms[uid].nominal,
                registry.atoms[uid].std_uncertainty,
                registry.atoms[uid].distribution,
                n,
            )
            for uid in uids
        }
    # Correlated inputs: multivariate normal with the full covariance matrix.
    means = np.array([registry.atoms[u].nominal for u in uids])
    cov = np.empty((len(uids), len(uids)))
    for i, ui in enumerate(uids):
        for j, uj in enumerate(uids):
            cov[i, j] = registry.covariance(ui, uj)
    draws = rng.multivariate_normal(means, cov, size=n, method="cholesky")
    return {uid: draws[:, i] for i, uid in enumerate(uids)}


def _input_samples(quantity: Quantity, atom_samples: Mapping[str, np.ndarray], n: int) -> np.ndarray:
    values = np.full(n, quantity.nominal)
    reg = quantity.registry
    for uid, g in quantity.grad.items():
        values = values + g * (atom_samples[uid] - reg.atoms[uid].nominal)
    return values


def monte_carlo(
    func: Callable[..., np.ndarray],
    inputs: Mapping[str, Quantity],
    *,
    samples: int = 1_000_000,
    seed: int | None = None,
    confidence: float = 0.95,
    registry: AtomRegistry | None = None,
    keep_samples: bool = False,
) -> MonteCarloResult:
    """Propagate ``func(**inputs)`` by Monte Carlo (fixed sample count)."""

    reg = registry or next(iter(inputs.values())).registry if inputs else default_registry()
    rng = np.random.default_rng(seed)
    uids = sorted({uid for q in inputs.values() for uid in q.grad})
    atom_samples = _draw_atom_samples(reg, uids, rng, samples)
    sampled_inputs = {name: _input_samples(q, atom_samples, samples) for name, q in inputs.items()}
    out = np.asarray(func(**sampled_inputs), dtype=float)
    interval = shortest_coverage_interval(out, confidence)
    return MonteCarloResult(
        mean=float(np.mean(out)),
        std=float(np.std(out, ddof=1)),
        interval=interval,
        confidence=confidence,
        draws=samples,
        samples=out if keep_samples else None,
    )


def adaptive_monte_carlo(
    func: Callable[..., np.ndarray],
    inputs: Mapping[str, Quantity],
    *,
    significant_digits: int = 2,
    block: int = 100_000,
    max_blocks: int = 200,
    seed: int | None = None,
    confidence: float = 0.95,
    registry: AtomRegistry | None = None,
) -> MonteCarloResult:
    """Adaptive Monte Carlo (JCGM 101 §7.9.4).

    Runs blocks of trials until the estimates of ``y``, ``u(y)`` and both
    coverage-interval endpoints stabilise to the numerical tolerance ``δ``
    derived from the requested number of significant digits.
    """

    reg = registry or next(iter(inputs.values())).registry if inputs else default_registry()
    uids = sorted({uid for q in inputs.values() for uid in q.grad})
    means_y: list[float] = []
    means_u: list[float] = []
    los: list[float] = []
    his: list[float] = []
    total = 0
    base_seed = seed if seed is not None else np.random.SeedSequence().entropy
    for h in range(1, max_blocks + 1):
        rng = np.random.default_rng((base_seed, h))
        atom_samples = _draw_atom_samples(reg, uids, rng, block)
        sampled_inputs = {n: _input_samples(q, atom_samples, block) for n, q in inputs.items()}
        out = np.asarray(func(**sampled_inputs), dtype=float)
        lo, hi = shortest_coverage_interval(out, confidence)
        means_y.append(float(np.mean(out)))
        means_u.append(float(np.std(out, ddof=1)))
        los.append(lo)
        his.append(hi)
        total += block
        if h < 2:
            continue
        u_overall = float(np.mean(means_u))
        if u_overall == 0:
            break
        digits = math.floor(math.log10(abs(u_overall)))
        delta = 0.5 * 10.0 ** (digits - significant_digits + 1)

        def stable(seq: list[float]) -> bool:
            return 2.0 * float(np.std(seq, ddof=1)) / math.sqrt(len(seq)) <= delta

        if all(stable(seq) for seq in (means_y, means_u, los, his)):
            break
    return MonteCarloResult(
        mean=float(np.mean(means_y)),
        std=float(np.mean(means_u)),
        interval=(float(np.mean(los)), float(np.mean(his))),
        confidence=confidence,
        draws=total,
    )
