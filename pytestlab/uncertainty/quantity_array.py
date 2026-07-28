"""Factored covariance arrays for waveform-scale uncertainty propagation."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import ArrayLike

from .atoms import AtomRegistry
from .atoms import Distribution
from .atoms import Kind
from .atoms import default_registry
from .metrology import CorrectionRecord
from .metrology import InputQuantityRecord
from .metrology import MeasurementModel
from .metrology import ResultProvenance
from .metrology import TraceabilityRef
from .quantity import Quantity
from .units import unit_name


def _as_1d(value: ArrayLike, *, name: str) -> np.ndarray:
    arr = np.asarray(value, dtype=float)
    if arr.ndim != 1:
        raise ValueError(f"{name} must be a 1-D array.")
    return arr


def _effective_sample_count(values: np.ndarray, method: str) -> tuple[float, str]:
    n = values.size
    if n < 2:
        return 1.0, "single_sample_conservative"
    if method == "validated_independent":
        return float(n), "validated_independent"
    if method == "lag1_autocorrelation":
        centered = values - float(np.mean(values))
        denom = float(np.dot(centered, centered))
        if denom <= 0:
            return float(n), "constant_signal_independent"
        rho1 = float(np.dot(centered[:-1], centered[1:]) / denom)
        if rho1 <= 0:
            return float(n), "lag1_nonpositive_independent"
        n_eff = n * (1.0 - rho1) / (1.0 + rho1)
        return float(min(n, max(2.0, n_eff))), "lag1_autocorrelation"
    if method == "unknown_conservative":
        return 2.0, "unknown_conservative"
    raise ValueError(
        "dof_method must be 'validated_independent', 'lag1_autocorrelation', "
        "or 'unknown_conservative'."
    )


def _quantity_array_from_covariance(
    nominal: np.ndarray,
    covariance: np.ndarray,
    *,
    unit: str,
    label: str,
    provenance: ResultProvenance,
    measurement_model: MeasurementModel | None = None,
) -> QuantityArray:
    """Represent a dense covariance matrix as orthogonal unit-variance atoms."""

    reg = AtomRegistry()
    cov = np.asarray(covariance, dtype=float)
    cov = (cov + cov.T) / 2.0
    eigvals, eigvecs = np.linalg.eigh(cov)
    sensitivities: dict[str, np.ndarray] = {}
    diagonal = np.zeros_like(nominal, dtype=float)
    for index, eigval in enumerate(eigvals):
        if eigval <= 1e-15:
            continue
        atom = reg.mint(
            nominal=0.0,
            std_uncertainty=1.0,
            label=f"{label}:mode_{index}",
            unit=unit,
            distribution=Distribution.STANDARD,
            kind=Kind.TYPE_B,
            source="linear_covariance_factorization",
            traceability=TraceabilityRef(source="assumed"),
        )
        sensitivities[atom.uid] = eigvecs[:, index] * math.sqrt(float(eigval))
    return QuantityArray(
        nominal,
        unit=unit,
        diagonal_variance=diagonal,
        atom_sensitivities=sensitivities,
        registry=reg,
        measurement_model=measurement_model,
        provenance=provenance,
    )


class ComplexQuantityArray:
    """Complex waveform/spectral result represented by real and imaginary arrays."""

    def __init__(
        self,
        real: QuantityArray,
        imag: QuantityArray,
        *,
        frequency: ArrayLike | None = None,
        unit: str | None = None,
    ) -> None:
        if len(real) != len(imag):
            raise ValueError("real and imaginary arrays must have the same length.")
        self.real = real
        self.imag = imag
        self.frequency = None if frequency is None else _as_1d(frequency, name="frequency")
        if self.frequency is not None and self.frequency.shape != real.nominal.shape:
            raise ValueError("frequency must match complex array length.")
        self.unit = unit or real.unit

    @property
    def nominal(self) -> np.ndarray:
        return self.real.nominal + 1j * self.imag.nominal

    def magnitude(self) -> QuantityArray:
        mag = np.abs(self.nominal)
        real_cov = self.real.covariance_matrix(max_elements=max(4096, len(self.real)))
        imag_cov = self.imag.covariance_matrix(max_elements=max(4096, len(self.imag)))
        covariance = np.zeros((len(mag), len(mag)), dtype=float)
        for i, m_i in enumerate(mag):
            if m_i == 0:
                continue
            for j, m_j in enumerate(mag):
                if m_j == 0:
                    continue
                covariance[i, j] = (self.real.nominal[i] / m_i) * (
                    self.real.nominal[j] / m_j
                ) * real_cov[i, j] + (self.imag.nominal[i] / m_i) * (
                    self.imag.nominal[j] / m_j
                ) * imag_cov[i, j]
        return _quantity_array_from_covariance(
            mag,
            covariance,
            unit=self.unit,
            label="fft_magnitude",
            provenance=self.real.provenance,
            measurement_model=MeasurementModel(
                output_name="fft_magnitude",
                output_unit=self.unit,
                function="abs(fft(waveform))",
                method="gum_first_order",
                assumptions=["real/imag cross-covariance neglected in first implementation"],
            ),
        )


class QuantityArray:
    """Waveform-sized nominal samples with factored covariance.

    The covariance is represented as ``diag(diagonal_variance) + S Σ_atoms Sᵀ``
    where columns of ``S`` are per-sample sensitivities for shared systematic
    influence quantities in an :class:`AtomRegistry`.
    """

    __slots__ = (
        "nominal",
        "unit",
        "diagonal_variance",
        "atom_sensitivities",
        "registry",
        "measurement_model",
        "provenance",
        "dof_method",
    )

    def __init__(
        self,
        nominal: ArrayLike,
        *,
        unit: str = "",
        diagonal_variance: ArrayLike | None = None,
        atom_sensitivities: dict[str, Any] | None = None,
        registry: AtomRegistry | None = None,
        measurement_model: MeasurementModel | None = None,
        provenance: ResultProvenance | None = None,
        dof_method: str | None = None,
    ) -> None:
        self.nominal = _as_1d(nominal, name="nominal")
        self.unit = unit_name(unit)
        if diagonal_variance is None:
            diag = np.zeros_like(self.nominal, dtype=float)
        else:
            diag = _as_1d(diagonal_variance, name="diagonal_variance")
            if diag.shape != self.nominal.shape:
                raise ValueError("diagonal_variance must match nominal shape.")
            if np.any(diag < 0):
                raise ValueError("diagonal_variance must be non-negative.")
        self.diagonal_variance = diag
        self.registry = registry or default_registry()
        self.atom_sensitivities: dict[str, np.ndarray] = {}
        for uid, sensitivity in (atom_sensitivities or {}).items():
            if uid not in self.registry.atoms:
                raise KeyError(f"Unknown atom uid in sensitivity map: {uid}")
            arr = np.asarray(sensitivity, dtype=float)
            if arr.ndim == 0:
                arr = np.full_like(self.nominal, float(arr), dtype=float)
            elif arr.shape != self.nominal.shape:
                raise ValueError(f"Sensitivity for {uid!r} must be scalar or match nominal shape.")
            self.atom_sensitivities[uid] = arr
        self.measurement_model = measurement_model
        self.provenance = provenance or ResultProvenance.legacy_incomplete()
        self.dof_method = dof_method

    @classmethod
    def constant(cls, values: ArrayLike, unit: str = "") -> QuantityArray:
        return cls(values, unit=unit)

    @classmethod
    def from_samples(
        cls,
        values: ArrayLike,
        *,
        unit: str = "",
        independent_std: ArrayLike | float | None = None,
        registry: AtomRegistry | None = None,
    ) -> QuantityArray:
        nominal = _as_1d(values, name="values")
        if independent_std is None:
            diag = np.zeros_like(nominal, dtype=float)
        else:
            std = np.asarray(independent_std, dtype=float)
            if std.ndim == 0:
                std = np.full_like(nominal, float(std), dtype=float)
            if std.shape != nominal.shape:
                raise ValueError("independent_std must be scalar or match values shape.")
            if not np.all(np.isfinite(std)):
                raise ValueError("independent_std must contain only finite values.")
            if np.any(std < 0.0):
                raise ValueError("independent_std must be non-negative.")
            diag = std**2
        return cls(nominal, unit=unit, diagonal_variance=diag, registry=registry)

    @classmethod
    def from_quantity_samples(
        cls, components: list[Quantity], labels: list[str] | None = None
    ) -> QuantityArray:
        if not components:
            raise ValueError("QuantityArray requires at least one quantity.")
        reg = components[0].registry
        if any(q.registry is not reg for q in components):
            raise ValueError("all quantities must share one atom registry.")
        unit = components[0].unit
        nominal = np.array([q.nominal for q in components], dtype=float)
        sensitivities: dict[str, np.ndarray] = {}
        for idx, q in enumerate(components):
            if q.unit != unit:
                raise ValueError("all quantity samples must use the same unit.")
            for uid, g in q.grad.items():
                sensitivities.setdefault(uid, np.zeros(len(components), dtype=float))[idx] = g
        return cls(
            nominal,
            unit=unit,
            diagonal_variance=np.zeros_like(nominal),
            atom_sensitivities=sensitivities,
            registry=reg,
        )

    def __len__(self) -> int:
        return int(self.nominal.size)

    def __getitem__(self, key: int | slice | np.ndarray) -> Quantity | QuantityArray:
        if isinstance(key, int):
            grad = {uid: float(sens[key]) for uid, sens in self.atom_sensitivities.items()}
            q = Quantity(float(self.nominal[key]), self.unit, grad, self.registry)
            q.provenance = self.provenance
            q.dof_method = self.dof_method
            return q
        nominal = self.nominal[key]
        diag = self.diagonal_variance[key]
        sensitivities = {uid: sens[key] for uid, sens in self.atom_sensitivities.items()}
        return QuantityArray(
            nominal,
            unit=self.unit,
            diagonal_variance=diag,
            atom_sensitivities=sensitivities,
            registry=self.registry,
            measurement_model=self.measurement_model,
            provenance=self.provenance,
            dof_method=self.dof_method,
        )

    def __repr__(self) -> str:
        return f"QuantityArray(shape={self.nominal.shape}, unit={self.unit!r})"

    __str__ = __repr__

    @property
    def variance(self) -> np.ndarray:
        return np.diag(self.covariance_matrix()) if len(self) <= 4096 else self._variance_fast()

    @property
    def u(self) -> np.ndarray:
        return np.sqrt(np.maximum(self.variance, 0.0))

    def _variance_fast(self) -> np.ndarray:
        var = self.diagonal_variance.astype(float).copy()
        for uid, sens in self.atom_sensitivities.items():
            atom = self.registry.atoms[uid]
            var += (sens**2) * atom.variance
        for (a, b), cov in self.registry._covariances.items():
            sa = self.atom_sensitivities.get(a)
            sb = self.atom_sensitivities.get(b)
            if sa is not None and sb is not None:
                var += 2.0 * sa * sb * cov
        if np.any(var < -1e-9 * np.maximum(self.diagonal_variance, 1e-300)):
            raise ValueError("QuantityArray covariance is not positive semi-definite.")
        return np.maximum(var, 0.0)

    def covariance_matrix(self, *, max_elements: int = 4096) -> np.ndarray:
        n = len(self)
        if n > max_elements:
            raise ValueError(
                "Dense covariance would be too large; use reductions or raise max_elements."
            )
        cov = np.diag(self.diagonal_variance.astype(float))
        if not self.atom_sensitivities:
            return cov
        uids = list(self.atom_sensitivities)
        S = np.column_stack([self.atom_sensitivities[uid] for uid in uids])
        sigma = np.empty((len(uids), len(uids)), dtype=float)
        for i, uid_a in enumerate(uids):
            for j, uid_b in enumerate(uids):
                sigma[i, j] = self.registry.covariance(uid_a, uid_b)
        cov = cov + S @ sigma @ S.T
        if np.min(np.linalg.eigvalsh(cov)) < -1e-8:
            raise ValueError("QuantityArray covariance is not positive semi-definite.")
        return cov

    def _quantity_from_weights(
        self,
        weights: np.ndarray,
        nominal: float,
        output_unit: str,
        *,
        output_name: str,
        function: str,
        method: str = "analytic_exact",
        dof_method: str = "validated_independent",
        assumptions: list[str] | None = None,
        linearization_note: str | None = None,
    ) -> Quantity:
        weights = _as_1d(weights, name="weights")
        if weights.shape != self.nominal.shape:
            raise ValueError("weights must match nominal shape.")
        diag_var = float(np.sum((weights**2) * self.diagonal_variance))
        grad = {
            uid: float(np.dot(weights, sensitivity))
            for uid, sensitivity in self.atom_sensitivities.items()
            if float(np.dot(weights, sensitivity)) != 0.0
        }
        reg = self.registry
        if diag_var > 0:
            _, dof_name = _effective_sample_count(self.nominal, dof_method)
            n_eff, _ = _effective_sample_count(self.nominal, dof_method)
            atom = reg.mint(
                nominal=0.0,
                std_uncertainty=math.sqrt(diag_var),
                label=f"{function}:independent_noise",
                unit=output_unit,
                distribution=Distribution.STANDARD,
                degrees_of_freedom=max(1.0, n_eff - 1.0),
                kind=Kind.TYPE_A,
                source="type_a_measurement",
                traceability=TraceabilityRef(source="type_a_measurement"),
            )
            grad[atom.uid] = grad.get(atom.uid, 0.0) + 1.0
            dof_method = dof_name
        q = Quantity(nominal, output_unit, grad, reg)
        inputs = []
        for uid in grad:
            atom = reg.atoms[uid]
            inputs.append(
                InputQuantityRecord(
                    name=atom.label,
                    unit=atom.unit or "",
                    distribution=atom.distribution.value,
                    traceability_ref=atom.traceability,
                    dof=atom.degrees_of_freedom,
                )
            )
        q.measurement_model = MeasurementModel(
            output_name=output_name,
            output_unit=output_unit,
            function=function,
            inputs=inputs,
            corrections=[
                CorrectionRecord(name="zero_correction", value=0.0, u=0.0, basis="explicit")
            ],
            method=method,  # type: ignore[arg-type]
            linearization_note=linearization_note,
            assumptions=assumptions or [],
            dof_method=dof_method,
        )
        q.provenance = self.provenance
        q.dof_method = dof_method
        return q

    def mean(self, *, dof_method: str = "validated_independent") -> Quantity:
        weights = np.full(len(self), 1.0 / len(self), dtype=float)
        return self._quantity_from_weights(
            weights,
            float(np.mean(self.nominal)),
            self.unit,
            output_name="mean",
            function="mean(waveform)",
            method="analytic_exact",
            dof_method=dof_method,
            assumptions=["linear mean reduction"],
        )

    def integrate(self, *, dx: float = 1.0, dof_method: str = "validated_independent") -> Quantity:
        weights = np.full(len(self), dx, dtype=float)
        unit = self.unit if not self.unit else f"{self.unit}*s" if dx != 1.0 else self.unit
        return self._quantity_from_weights(
            weights,
            float(np.sum(self.nominal) * dx),
            unit,
            output_name="integral",
            function="integrate(waveform)",
            method="analytic_exact",
            dof_method=dof_method,
            assumptions=["rectangular integration weights"],
        )

    def rms(self, *, dof_method: str = "lag1_autocorrelation") -> Quantity:
        rms = float(np.sqrt(np.mean(self.nominal**2)))
        if rms == 0.0:
            weights = np.zeros(len(self), dtype=float)
        else:
            weights = self.nominal / (len(self) * rms)
        return self._quantity_from_weights(
            weights,
            rms,
            self.unit,
            output_name="rms",
            function="rms(waveform)",
            method="gum_first_order",
            dof_method=dof_method,
            assumptions=["first-order RMS linearization"],
        )

    def peak_to_peak(self) -> Quantity:
        i_max = int(np.argmax(self.nominal))
        i_min = int(np.argmin(self.nominal))
        weights = np.zeros(len(self), dtype=float)
        weights[i_max] = 1.0
        weights[i_min] = -1.0
        return self._quantity_from_weights(
            weights,
            float(self.nominal[i_max] - self.nominal[i_min]),
            self.unit,
            output_name="peak_to_peak",
            function="vpp(waveform)",
            method="monte_carlo_required",
            dof_method="unknown_conservative",
            assumptions=[
                "non-differentiable peak selection requires Monte Carlo for report-grade use"
            ],
            linearization_note="First-order Vpp is approximate and not report-grade unless MC validation passes.",
        )

    def sample_values(self, *, samples: int = 100_000, seed: int | None = None) -> np.ndarray:
        """Draw Monte Carlo waveform samples from the factored covariance model."""

        if samples < 2:
            raise ValueError("samples must be at least 2.")
        rng = np.random.default_rng(seed)
        draws = np.broadcast_to(self.nominal, (samples, len(self))).astype(float).copy()
        if np.any(self.diagonal_variance):
            draws += rng.normal(0.0, np.sqrt(self.diagonal_variance), size=draws.shape)
        if self.atom_sensitivities:
            uids = list(self.atom_sensitivities)
            sigma = np.empty((len(uids), len(uids)), dtype=float)
            for i, uid_a in enumerate(uids):
                for j, uid_b in enumerate(uids):
                    sigma[i, j] = self.registry.covariance(uid_a, uid_b)
            atom_draws = rng.multivariate_normal(np.zeros(len(uids)), sigma, size=samples)
            sensitivity = np.column_stack([self.atom_sensitivities[uid] for uid in uids])
            draws += atom_draws @ sensitivity.T
        return draws

    def monte_carlo_reduce(
        self,
        reducer: Callable[[np.ndarray], np.ndarray | float],
        *,
        output_name: str,
        function: str,
        samples: int = 100_000,
        seed: int | None = None,
    ) -> Quantity:
        """Evaluate a scalar waveform reduction by Monte Carlo propagation."""

        draws = self.sample_values(samples=samples, seed=seed)
        reduced = np.asarray(reducer(draws), dtype=float)
        if reduced.shape == ():
            reduced = np.full(samples, float(reduced), dtype=float)
        if reduced.shape != (samples,):
            raise ValueError("reducer must return one scalar per Monte Carlo sample.")
        nominal_values = np.asarray(reducer(self.nominal.reshape(1, -1)), dtype=float).reshape(-1)
        nominal = float(nominal_values[0]) if nominal_values.size else float(np.mean(reduced))
        std = float(np.std(reduced, ddof=1))
        reg = self.registry
        grad: dict[str, float] = {}
        if std:
            atom = reg.mint(
                nominal=0.0,
                std_uncertainty=std,
                label=f"{function}:monte_carlo",
                unit=self.unit,
                distribution=Distribution.STANDARD,
                degrees_of_freedom=float(samples - 1),
                kind=Kind.TYPE_A,
                source="monte_carlo_propagation",
                traceability=TraceabilityRef(source="type_a_measurement"),
            )
            grad[atom.uid] = 1.0
        q = Quantity(nominal, self.unit, grad, reg)
        q.measurement_model = MeasurementModel(
            output_name=output_name,
            output_unit=self.unit,
            function=function,
            inputs=[
                InputQuantityRecord(
                    name="waveform_factored_covariance",
                    unit=self.unit,
                    distribution="monte_carlo_samples",
                )
            ],
            method="monte_carlo",
            assumptions=[f"samples={samples}", f"seed={seed}"],
            dof_method="monte_carlo_sample_standard_deviation",
        )
        q.provenance = self.provenance
        q.dof_method = "monte_carlo_sample_standard_deviation"
        return q

    def peak_to_peak_monte_carlo(
        self, *, samples: int = 100_000, seed: int | None = None
    ) -> Quantity:
        """Report-grade-capable Monte Carlo propagation for peak-to-peak voltage."""

        return self.monte_carlo_reduce(
            lambda values: np.max(values, axis=1) - np.min(values, axis=1),
            output_name="peak_to_peak",
            function="vpp(waveform)",
            samples=samples,
            seed=seed,
        )

    def linear_transform(
        self,
        matrix: ArrayLike,
        *,
        output_unit: str | None = None,
        function: str = "linear_transform(waveform)",
    ) -> QuantityArray:
        """Propagate a dense linear transform through the covariance model."""

        mat = np.asarray(matrix, dtype=float)
        if mat.ndim != 2 or mat.shape[1] != len(self):
            raise ValueError("matrix must have shape (outputs, len(quantity_array)).")
        nominal = mat @ self.nominal
        covariance = mat @ self.covariance_matrix(max_elements=max(4096, len(self))) @ mat.T
        return _quantity_array_from_covariance(
            nominal,
            covariance,
            unit=output_unit or self.unit,
            label=function,
            provenance=self.provenance,
            measurement_model=MeasurementModel(
                output_name=function,
                output_unit=output_unit or self.unit,
                function=function,
                method="analytic_exact",
                assumptions=["dense linear covariance propagation"],
            ),
        )

    def fft(self, *, sample_rate: float, window: str | None = "hann") -> ComplexQuantityArray:
        """Propagate a real FFT as an exact linear transform for small/medium arrays."""

        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive.")
        n = len(self)
        if window in {"hann", "hanning"}:
            win = np.hanning(n)
        elif window in {None, "none", "rectangular"}:
            win = np.ones(n)
        else:
            raise ValueError("Only hann/hanning/rectangular FFT windows are supported.")
        transform = np.fft.rfft(np.eye(n), axis=0) * win[np.newaxis, :]
        real = self.linear_transform(transform.real, function="real(fft(waveform))")
        imag = self.linear_transform(transform.imag, function="imag(fft(waveform))")
        freq = np.fft.rfftfreq(n, d=1.0 / sample_rate)
        return ComplexQuantityArray(real, imag, frequency=freq, unit=self.unit)

    def to_dsi(self, *, coverage_factor: float = 2.0) -> dict[str, Any]:
        from .units import to_dsi_unit

        dsi_unit, unit_resolved = to_dsi_unit(self.unit)
        return {
            "value": self.nominal.tolist(),
            "unit": dsi_unit,
            "unit_resolved": unit_resolved,
            "standard_uncertainty": self.u.tolist(),
            "expanded_uncertainty": (self.u * coverage_factor).tolist(),
            "coverageFactor": coverage_factor,
            "coverageProbability": None,
            "distribution": "factored_covariance",
        }

    def to_dict(self) -> dict[str, Any]:
        atoms = []
        for uid, sensitivity in self.atom_sensitivities.items():
            atom = self.registry.atoms[uid]
            atoms.append(
                {
                    "uid": uid,
                    "label": atom.label,
                    "value": atom.nominal,
                    "std_uncertainty": atom.std_uncertainty,
                    "unit": atom.unit,
                    "distribution": atom.distribution.value,
                    "kind": atom.kind.value,
                    "dof": atom.degrees_of_freedom,
                    "source": atom.source,
                    "traceability_ref": atom.traceability.model_dump(mode="json")
                    if atom.traceability
                    else None,
                    "sensitivity": sensitivity.tolist(),
                }
            )
        return {
            "schema_version": "1.0",
            "unit": self.unit,
            "nominal": self.nominal.tolist(),
            "diagonal_variance": self.diagonal_variance.tolist(),
            "atoms": atoms,
            "correlations": [[a, b, c] for (a, b), c in self.registry._covariances.items()],
            "provenance": self.provenance.model_dump(mode="json"),
            "measurement_model": self.measurement_model.model_dump(mode="json")
            if self.measurement_model
            else None,
            "dof_method": self.dof_method,
            "sidecar": None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], registry: AtomRegistry | None = None) -> QuantityArray:
        reg = registry or AtomRegistry()
        sensitivities: dict[str, np.ndarray] = {}
        for item in data.get("atoms", []):
            traceability = (
                TraceabilityRef(**item["traceability_ref"])
                if item.get("traceability_ref")
                else None
            )
            atom = reg.mint(
                nominal=float(item.get("value", 0.0)),
                std_uncertainty=float(item.get("std_uncertainty", 0.0)),
                label=str(item.get("label", item["uid"])),
                unit=item.get("unit"),
                distribution=Distribution(item.get("distribution", "normal")),
                degrees_of_freedom=item.get("dof"),
                kind=Kind(item.get("kind", "type_b")),
                source=item.get("source"),
                traceability=traceability,
                key=item["uid"],
            )
            sensitivities[atom.uid] = np.asarray(item.get("sensitivity", []), dtype=float)
        for a, b, cov in data.get("correlations", []):
            reg.set_covariance(a, b, float(cov))
        model = data.get("measurement_model")
        return cls(
            data.get("nominal", []),
            unit=data.get("unit", ""),
            diagonal_variance=data.get("diagonal_variance"),
            atom_sensitivities=sensitivities,
            registry=reg,
            measurement_model=MeasurementModel(**model) if isinstance(model, dict) else None,
            provenance=ResultProvenance(**data["provenance"])
            if isinstance(data.get("provenance"), dict)
            else ResultProvenance.legacy_incomplete(),
            dof_method=data.get("dof_method"),
        )

    def save_npz_sidecar(self, path: str | Path) -> dict[str, Any]:
        """Write normative NPZ sidecar and return manifest metadata."""

        path = Path(path)
        sidecar_arrays: dict[str, Any] = {
            "nominal": self.nominal,
            "diagonal_variance": self.diagonal_variance,
        }
        sensitivity_keys: dict[str, str] = {}
        for index, (uid, sens) in enumerate(self.atom_sensitivities.items()):
            key = f"sensitivity_{index}"
            sensitivity_keys[key] = uid
            sidecar_arrays[key] = sens
        np.savez_compressed(path, **sidecar_arrays)
        payload = path.read_bytes()
        atom_payload = []
        for uid in self.atom_sensitivities:
            atom = self.registry.atoms[uid]
            traceability = atom.traceability
            atom_payload.append(
                {
                    "uid": uid,
                    "atom": atom.__dict__
                    | {
                        "distribution": atom.distribution.value,
                        "kind": atom.kind.value,
                        "traceability": traceability.model_dump(mode="json")
                        if traceability is not None
                        else None,
                    },
                }
            )
        atom_json = json.dumps(atom_payload, sort_keys=True, default=str).encode()
        covariance_payload = [[a, b, c] for (a, b), c in self.registry._covariances.items()]
        covariance_json = json.dumps(covariance_payload, sort_keys=True).encode()
        manifest = {
            "schema_version": "1.1",
            "format": "npz",
            "manifest_json": True,
            "path": str(path),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "n_samples": len(self),
            "dtype": str(self.nominal.dtype),
            "byteorder": self.nominal.dtype.byteorder,
            "arrays": {
                "nominal": "nominal",
                "diagonal_variance": "diagonal_variance",
                "sensitivities": sensitivity_keys,
            },
            "atom_metadata_sha256": hashlib.sha256(atom_json).hexdigest(),
            "covariance_metadata_sha256": hashlib.sha256(covariance_json).hexdigest(),
        }
        path.with_suffix(path.suffix + ".json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
        return manifest

    @classmethod
    def load_npz_sidecar(
        cls,
        path: str | Path,
        *,
        manifest_path: str | Path | None = None,
        registry: AtomRegistry | None = None,
    ) -> QuantityArray:
        """Load an NPZ sidecar written by :meth:`save_npz_sidecar`.

        Atom metadata is intentionally not reconstructed from the sidecar alone;
        callers pass the authoritative registry or use the JSON `to_dict` payload
        for complete restoration.  The sidecar loader verifies file integrity and
        reconstructs nominal/diagonal/sensitivity arrays.
        """

        path = Path(path)
        manifest_file = (
            Path(manifest_path)
            if manifest_path is not None
            else path.with_suffix(path.suffix + ".json")
        )
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != manifest.get("sha256"):
            raise ValueError("QuantityArray sidecar SHA-256 mismatch.")
        arrays = manifest.get("arrays", {})
        with np.load(path) as data:
            nominal = np.asarray(data[arrays.get("nominal", "nominal")], dtype=float)
            diagonal = np.asarray(
                data[arrays.get("diagonal_variance", "diagonal_variance")], dtype=float
            )
            sensitivities = {
                uid: np.asarray(data[key], dtype=float)
                for key, uid in arrays.get("sensitivities", {}).items()
            }
        return cls(
            nominal,
            diagonal_variance=diagonal,
            atom_sensitivities=sensitivities,
            registry=registry,
        )
