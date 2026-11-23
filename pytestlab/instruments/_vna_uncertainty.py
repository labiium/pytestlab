"""Validate a setup-specific VNA uncertainty budget without flattening its covariance."""

from __future__ import annotations

import json
import math

import numpy as np
from numpy.typing import NDArray

from ..uncertainty import QuantityArray

_MAX_EXPLICITLY_CORRELATED_ATOMS = 256


def snapshot_components(components: QuantityArray, nominal: NDArray[np.float64]) -> str:
    """Validate and snapshot the stock QuantityArray representation for persistence."""
    if not isinstance(components, QuantityArray):
        raise TypeError("VNA uncertainty must be a PyTestLab QuantityArray.")
    if components.unit != "1" or not np.array_equal(components.nominal, nominal):
        raise ValueError("VNA uncertainty must match the dimensionless captured RI values exactly.")

    payload = components.to_dict()
    sensitivities = components.atom_sensitivities
    active = set(sensitivities)
    # A default registry can contain unrelated measurements. Store only the
    # influences and mutual covariances that the supplied budget actually uses.
    covariances = [
        (left, right, cov)
        for left, right, cov in payload["correlations"]
        if left in active and right in active
    ]
    payload["correlations"] = covariances
    _validate_budget(components, covariances)
    return json.dumps(payload, allow_nan=False)


def _validate_budget(
    components: QuantityArray,
    covariances: list[tuple[str, str, float]],
) -> None:
    registry = components.registry
    sensitivities = components.atom_sensitivities
    diagonal = np.array(components.diagonal_variance, dtype=float, copy=True)
    if (
        diagonal.shape != components.nominal.shape
        or not np.all(np.isfinite(diagonal))
        or np.any(diagonal < 0)
    ):
        raise ValueError("VNA uncertainty requires finite nonnegative diagonal variances.")

    scaled: dict[str, NDArray[np.float64]] = {}
    for uid, sensitivity in sensitivities.items():
        atom = registry.get(uid)
        std = atom.std_uncertainty
        if (
            not math.isfinite(std)
            or std < 0
            or not math.isfinite(atom.nominal)
            or sensitivity.shape != components.nominal.shape
            or not np.all(np.isfinite(sensitivity))
        ):
            raise ValueError("VNA uncertainty requires finite sensitivities and influence values.")
        with np.errstate(over="ignore", invalid="ignore"):
            scaled[uid] = sensitivity * std
            diagonal += scaled[uid] ** 2

    # The covariance is already factored. Validate correlated influences,
    # never construct a sweep-sized covariance matrix.
    correlated = sorted({uid for a, b, c in covariances if c != 0 for uid in (a, b)})
    if len(correlated) > _MAX_EXPLICITLY_CORRELATED_ATOMS:
        raise ValueError(
            "VNA uncertainty supports at most 256 explicitly correlated influence atoms; "
            "use shared factor sensitivities for larger models."
        )
    indices = {uid: index for index, uid in enumerate(correlated)}
    correlations = np.eye(len(correlated))
    for left, right, cov in covariances:
        if cov == 0:
            continue
        std_left = registry.get(left).std_uncertainty
        std_right = registry.get(right).std_uncertainty
        corr = cov / std_left / std_right if std_left and std_right else math.inf
        if not math.isfinite(corr) or abs(corr) > 1 + 8 * np.finfo(float).eps:
            raise ValueError("VNA uncertainty contains an invalid influence correlation.")
        i, j = indices[left], indices[right]
        correlations[i, j] = correlations[j, i] = corr
        with np.errstate(over="ignore", invalid="ignore"):
            diagonal += 2 * corr * scaled[left] * scaled[right]
    if (
        correlated
        and np.linalg.eigvalsh(correlations)[0] < -16 * len(correlated) * np.finfo(float).eps
    ):
        raise ValueError("VNA uncertainty influence covariance must be positive semi-definite.")
    if not np.all(np.isfinite(diagonal)) or np.any(diagonal <= 0):
        raise ValueError("Every captured VNA RI component needs a finite positive uncertainty.")
