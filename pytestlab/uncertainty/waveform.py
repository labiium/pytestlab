"""Typed waveform uncertainty models for oscilloscope-scale results.

The model in this module is intentionally small and explicit: a waveform is
represented by nominal voltage samples plus a factored covariance model made of
shared systematic atoms and diagonal independent terms.  This keeps JCGM
102-style covariance visible without ever requiring a dense N×N covariance for
ordinary reductions.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from dataclasses import field
from typing import Any

import numpy as np
from numpy.typing import ArrayLike

from . import units
from .atoms import AtomRegistry
from .atoms import Distribution
from .atoms import Kind
from .atoms import divisor_for
from .metrology import DataOrigin
from .metrology import EvidencePurpose
from .metrology import InputQuantityRecord
from .metrology import MeasurementModel
from .metrology import ResultProvenance
from .metrology import TraceabilityRef
from .metrology import traceability_ref_from_any
from .quantity_array import QuantityArray


@dataclass(frozen=True)
class WaveformAxis:
    """Horizontal axis metadata for a waveform capture."""

    sample_interval_s: float | None = None
    origin_s: float = 0.0
    reference: float = 0.0
    sample_rate_sps: float | None = None
    timebase_relative_std: float | None = None
    timebase_reference_s: float = 0.0
    trigger_jitter_std_s: float | None = None
    sample_aperture_s: float | None = None
    interpolation_model: str = "linear"
    channel_skew_std_s: float | None = None

    @property
    def has_horizontal_uncertainty(self) -> bool:
        return bool(self.timebase_relative_std or self.trigger_jitter_std_s)


@dataclass(frozen=True)
class WaveformUncertaintyModel:
    """Vectorized uncertainty model for one oscilloscope waveform channel.

    Parameters are standard uncertainties unless explicitly named as limits.
    Correlation semantics are part of the field name: gain/offset/range terms are
    shared atoms across all samples; quantization/noise terms are independent
    diagonal variance.
    """

    unit: str = "V"
    channel: int | None = None
    source_key: str | None = None
    traceability: TraceabilityRef | None = None
    vertical_gain_std: float = 0.0
    vertical_offset_std: float = 0.0
    vertical_range_std: float = 0.0
    quantization_lsb: float | None = None
    independent_noise_std: float = 0.0
    axis: WaveformAxis = field(default_factory=WaveformAxis)
    preamble: dict[str, Any] = field(default_factory=dict)
    assumptions: tuple[str, ...] = ()
    provenance_complete: bool = False
    data_origin: DataOrigin = DataOrigin.UNKNOWN
    evidence_purpose: EvidencePurpose = EvidencePurpose.MEASUREMENT_RESULT
    origin_detail: str | None = None

    @classmethod
    def from_metadata(
        cls,
        metadata: dict[str, Any] | None,
        *,
        samples: ArrayLike | None = None,
        unit: str = "V",
        channel: int | None = None,
    ) -> WaveformUncertaintyModel:
        """Build a typed model from legacy/result metadata.

        This is the compatibility boundary for existing profile metadata.  It is
        deliberately not used as the internal representation.
        """

        meta = dict(metadata or {})
        resolved_unit = str(meta.get("unit", unit) or unit)
        traceability = traceability_ref_from_any(meta.get("traceability")) or TraceabilityRef(
            source="manufacturer_spec"
        )
        values = None if samples is None else np.asarray(samples, dtype=float)
        range_value = _optional_float(meta.get("range_value"))
        resolution = _optional_float(meta.get("resolution"))
        gain_std = 0.0
        offset_std = 0.0
        range_std = 0.0
        quantization_lsb = resolution
        noise_std = _optional_float(meta.get("independent_noise_std")) or 0.0
        assumptions: list[str] = []

        spec = meta.get("accuracy_spec")
        if spec is not None:
            spec_terms = _accuracy_spec_terms(
                spec,
                values=values,
                unit=resolved_unit,
                range_value=range_value,
                resolution=resolution,
            )
            gain_std += spec_terms["gain_std"]
            offset_std += spec_terms["offset_std"]
            range_std += spec_terms["range_std"]
            if spec_terms["quantization_lsb"] is not None:
                quantization_lsb = spec_terms["quantization_lsb"]
            assumptions.extend(spec_terms["assumptions"])
        elif quantization_lsb is None:
            assumptions.append(
                "no waveform accuracy specification; nominal samples carry no vertical uncertainty"
            )

        preamble = dict(meta.get("preamble") or {})
        axis = WaveformAxis(
            sample_interval_s=_optional_float(preamble.get("xinc"))
            or _sample_interval_from_rate(meta.get("sampling_rate")),
            origin_s=_optional_float(preamble.get("xorg")) or 0.0,
            reference=_optional_float(preamble.get("xref")) or 0.0,
            sample_rate_sps=_optional_float(meta.get("sampling_rate")),
            timebase_relative_std=_optional_float(meta.get("timebase_relative_std")),
            timebase_reference_s=_optional_float(meta.get("timebase_reference_s")) or 0.0,
            trigger_jitter_std_s=_optional_float(meta.get("trigger_jitter_std_s")),
            sample_aperture_s=_optional_float(meta.get("sample_aperture_s")),
            interpolation_model=str(meta.get("interpolation_model") or "linear"),
            channel_skew_std_s=_optional_float(meta.get("channel_skew_std_s")),
        )
        if not axis.has_horizontal_uncertainty:
            assumptions.append(
                "horizontal timebase/trigger uncertainty not applied to voltage-only reductions"
            )

        return cls(
            unit=resolved_unit,
            channel=channel,
            source_key=meta.get("source_key"),
            traceability=traceability,
            vertical_gain_std=gain_std,
            vertical_offset_std=offset_std,
            vertical_range_std=range_std,
            quantization_lsb=quantization_lsb,
            independent_noise_std=noise_std,
            axis=axis,
            preamble=preamble,
            assumptions=tuple(assumptions),
            provenance_complete=bool(meta.get("provenance_complete", False)),
            data_origin=DataOrigin(meta.get("data_origin", DataOrigin.UNKNOWN)),
            evidence_purpose=EvidencePurpose(
                meta.get("evidence_purpose", EvidencePurpose.MEASUREMENT_RESULT)
            ),
            origin_detail=meta.get("origin_detail"),
        )

    def quantity_array(
        self, samples: ArrayLike, *, registry: AtomRegistry | None = None
    ) -> QuantityArray:
        """Return a factored-covariance :class:`QuantityArray` for samples."""

        values = np.asarray(samples, dtype=float)
        if values.ndim != 1:
            raise ValueError("waveform samples must be one-dimensional")
        registry = registry or AtomRegistry()
        sensitivities: dict[str, np.ndarray] = {}
        inputs: list[InputQuantityRecord] = []
        trace = self.traceability or TraceabilityRef(source="manufacturer_spec")

        def add_shared(label: str, std: float, sensitivity: np.ndarray, atom_unit: str) -> None:
            if std <= 0.0:
                return
            key = f"{self.source_key}:{label}" if self.source_key else None
            atom = registry.mint(
                nominal=0.0,
                std_uncertainty=float(std),
                label=label,
                unit=atom_unit,
                distribution=Distribution.STANDARD,
                kind=Kind.TYPE_B,
                source=trace.source,
                traceability=trace,
                key=key,
            )
            sensitivities[atom.uid] = sensitivity.astype(float, copy=False)
            inputs.append(
                InputQuantityRecord(
                    name=label,
                    unit=atom_unit,
                    distribution=Distribution.STANDARD.value,
                    traceability_ref=trace,
                    dof=atom.degrees_of_freedom,
                )
            )

        add_shared("waveform_vertical_gain", self.vertical_gain_std, values, "")
        ones = np.ones_like(values, dtype=float)
        add_shared("waveform_vertical_offset", self.vertical_offset_std, ones, self.unit)
        add_shared("waveform_vertical_range", self.vertical_range_std, ones, self.unit)

        independent_var = np.zeros_like(values, dtype=float)
        if self.quantization_lsb is not None and self.quantization_lsb > 0.0:
            independent_var += (float(self.quantization_lsb) / math.sqrt(12.0)) ** 2
            inputs.append(
                InputQuantityRecord(
                    name="waveform_quantization",
                    unit=self.unit,
                    distribution=Distribution.RECTANGULAR.value,
                    traceability_ref=trace,
                )
            )
        if self.independent_noise_std > 0.0:
            independent_var += float(self.independent_noise_std) ** 2
            inputs.append(
                InputQuantityRecord(
                    name="waveform_independent_noise",
                    unit=self.unit,
                    distribution=Distribution.STANDARD.value,
                    traceability_ref=trace,
                )
            )

        assumptions = list(self.assumptions)
        if self.axis.timebase_relative_std:
            assumptions.append(
                f"timebase_relative_std={self.axis.timebase_relative_std:g} recorded; voltage reductions do not currently use horizontal sensitivity"
            )
        if self.axis.trigger_jitter_std_s:
            assumptions.append(
                f"trigger_jitter_std_s={self.axis.trigger_jitter_std_s:g} recorded; voltage reductions do not currently use horizontal sensitivity"
            )

        return QuantityArray(
            values,
            unit=self.unit,
            diagonal_variance=independent_var,
            atom_sensitivities=sensitivities,
            registry=registry,
            measurement_model=MeasurementModel(
                output_name=_channel_name("waveform", self.channel),
                output_unit=self.unit,
                function="oscilloscope_waveform(samples, uncertainty_model)",
                inputs=inputs,
                method="gum_first_order",
                assumptions=assumptions,
                dof_method="unresolved_until_reduction",
            ),
            provenance=ResultProvenance.current(
                input_data=values.tobytes(),
                data_origin=self.data_origin,
                evidence_purpose=self.evidence_purpose,
                origin_detail=self.origin_detail,
                provenance_complete=self.provenance_complete,
            ),
            dof_method="unresolved_until_reduction",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "pytestlab.waveform_uncertainty_model.v1",
            "unit": self.unit,
            "channel": self.channel,
            "source_key": self.source_key,
            "traceability": self.traceability.model_dump(mode="json")
            if self.traceability
            else None,
            "vertical_gain_std": self.vertical_gain_std,
            "vertical_offset_std": self.vertical_offset_std,
            "vertical_range_std": self.vertical_range_std,
            "quantization_lsb": self.quantization_lsb,
            "independent_noise_std": self.independent_noise_std,
            "axis": self.axis.__dict__,
            "preamble": self.preamble,
            "assumptions": list(self.assumptions),
            "provenance_complete": self.provenance_complete,
            "data_origin": self.data_origin.value,
            "evidence_purpose": self.evidence_purpose.value,
            "origin_detail": self.origin_detail,
        }


def build_waveform_quantity_array(
    samples: ArrayLike,
    metadata: dict[str, Any] | WaveformUncertaintyModel | None = None,
    *,
    unit: str = "V",
    channel: int | None = None,
    registry: AtomRegistry | None = None,
) -> QuantityArray:
    """Build a waveform `QuantityArray` from samples and typed/legacy metadata."""

    if isinstance(metadata, WaveformUncertaintyModel):
        model = metadata
    else:
        model = WaveformUncertaintyModel.from_metadata(
            metadata, samples=samples, unit=unit, channel=channel
        )
    return model.quantity_array(samples, registry=registry)


def _accuracy_spec_terms(
    spec: Any,
    *,
    values: np.ndarray | None,
    unit: str,
    range_value: float | None,
    resolution: float | None,
) -> dict[str, Any]:
    distribution = getattr(spec, "distribution", Distribution.RECTANGULAR)
    if not isinstance(distribution, Distribution):
        distribution = Distribution(str(distribution))
    coverage_factor = float(getattr(spec, "coverage_factor", 1.0) or 1.0)
    divisor = divisor_for(distribution, coverage_factor)
    gain_limit = 0.0
    for attr, scale in (
        ("reading_fraction", 1.0),
        ("reading_percent", 0.01),
        ("reading_ppm", 1e-6),
    ):
        raw = getattr(spec, attr, None)
        if raw is not None:
            gain_limit += float(raw) * scale
    gain_std = abs(gain_limit) / divisor if gain_limit else 0.0

    offset_std = 0.0
    raw_offset = getattr(spec, "offset", None)
    if raw_offset is not None:
        offset = units.convert_units(float(raw_offset), getattr(spec, "offset_unit", None), unit)
        offset_std += abs(offset) / divisor

    range_std = 0.0
    range_fraction = 0.0
    for attr, scale in (("range_fraction", 1.0), ("range_percent", 0.01)):
        raw = getattr(spec, attr, None)
        if raw is not None:
            range_fraction += float(raw) * scale
    if range_fraction:
        if range_value is None:
            raise ValueError("range_value is required for range-based waveform uncertainty")
        range_std += abs(range_fraction * range_value) / divisor

    counts = getattr(spec, "counts", None)
    spec_resolution = getattr(spec, "resolution", None)
    quantization_lsb = _optional_float(spec_resolution) or resolution
    if counts is not None:
        if quantization_lsb is None:
            raise ValueError("resolution is required when counts are used in waveform uncertainty")
        offset_std += abs(float(counts) * quantization_lsb) / divisor

    assumptions = [f"accuracy_spec_distribution={distribution.value}"]
    if values is None:
        assumptions.append("model built without sample values; gain sensitivities resolved later")
    return {
        "gain_std": gain_std,
        "offset_std": offset_std,
        "range_std": range_std,
        "quantization_lsb": quantization_lsb,
        "assumptions": assumptions,
    }


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    return result


def _sample_interval_from_rate(value: Any) -> float | None:
    rate = _optional_float(value)
    if rate is None or rate <= 0.0:
        return None
    return 1.0 / rate


def _channel_name(prefix: str, channel: int | None) -> str:
    return prefix if channel is None else f"{prefix}_ch{channel}"
