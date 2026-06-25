"""User-facing oscilloscope waveform result primitives."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import ArrayLike

from pytestlab.instruments.waveform_timing import WaveformTiming
from pytestlab.uncertainty import Quantity
from pytestlab.uncertainty import QuantityArray
from pytestlab.uncertainty import waveform_reductions_to_digital_exports
from pytestlab.uncertainty.metrology import ResultProvenance
from pytestlab.uncertainty.waveform import WaveformUncertaintyModel
from pytestlab.uncertainty.waveform import build_waveform_quantity_array


@dataclass(frozen=True)
class ScopeStateSnapshot:
    """Minimal state snapshot for controlled acquisitions."""

    mode: str
    values: dict[str, Any]


@dataclass(frozen=True)
class AcquisitionTrace:
    """Machine-readable acquisition provenance for waveform captures."""

    mode: str
    commands: tuple[str, ...] = ()
    state_before: ScopeStateSnapshot | None = None
    state_after: ScopeStateSnapshot | None = None
    restored: bool | None = None
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class WaveformResult:
    """One channel waveform with lazy covariance-aware reductions."""

    def __init__(
        self,
        values: ArrayLike,
        *,
        time: ArrayLike | None = None,
        unit: str = "V",
        channel: int | None = None,
        instrument: str | None = None,
        model: WaveformUncertaintyModel | dict[str, Any] | None = None,
        acquisition: AcquisitionTrace | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.values = np.asarray(values, dtype=float)
        if self.values.ndim != 1:
            raise ValueError("WaveformResult values must be one-dimensional")
        self.time = None if time is None else np.asarray(time, dtype=float)
        if self.time is not None and self.time.shape != self.values.shape:
            raise ValueError("time axis must match waveform values")
        self.unit = unit
        self.channel = channel
        self.instrument = instrument
        self.metadata = dict(metadata or {})
        if isinstance(model, WaveformUncertaintyModel):
            self.model = model
        else:
            model_metadata = (
                model if model is not None else self.metadata.get("waveform_uncertainty")
            )
            self.model = WaveformUncertaintyModel.from_metadata(
                model_metadata,
                samples=self.values,
                unit=unit,
                channel=channel,
            )
        self.acquisition = acquisition or AcquisitionTrace(mode="read_only")
        self._quantity: QuantityArray | None = None

    @property
    def point_count(self) -> int:
        return int(self.values.size)

    def quantity_array(self) -> QuantityArray:
        if self._quantity is None:
            self._quantity = build_waveform_quantity_array(
                self.values, self.model, unit=self.unit, channel=self.channel
            )
        return self._quantity

    # Short alias for interactive ergonomics.
    quantity = quantity_array

    def mean(self, *, dof_method: str = "validated_independent") -> Quantity:
        return self.quantity_array().mean(dof_method=dof_method)

    def rms(self, *, dof_method: str = "lag1_autocorrelation") -> Quantity:
        return self.quantity_array().rms(dof_method=dof_method)

    def integrate(
        self, *, dx: float | None = None, dof_method: str = "validated_independent"
    ) -> Quantity:
        if dx is None:
            if self.time is not None and self.time.size > 1:
                dx = float(np.median(np.diff(self.time)))
            else:
                dx = 1.0
        return self.quantity_array().integrate(dx=dx, dof_method=dof_method)

    def peak_to_peak(self) -> Quantity:
        return self.quantity_array().peak_to_peak()

    def peak_to_peak_monte_carlo(
        self, *, samples: int = 100_000, seed: int | None = None
    ) -> Quantity:
        return self.quantity_array().peak_to_peak_monte_carlo(samples=samples, seed=seed)

    @property
    def timing(self) -> WaveformTiming:
        """Timing/frequency reductions with horizontal uncertainty propagation."""

        return WaveformTiming(self)

    def reductions(
        self, *, monte_carlo_samples: int = 3000, seed: int | None = 20_260_618
    ) -> dict[str, Quantity]:
        return {
            "mean": self.mean(),
            "rms": self.rms(),
            "peak_to_peak": self.peak_to_peak_monte_carlo(samples=monte_carlo_samples, seed=seed)
            if self.point_count <= 4096
            else self.peak_to_peak(),
        }

    def to_evidence_bundle(
        self, output_dir: str | Path, *, identifier_prefix: str | None = None
    ) -> Path:
        """Write a compact software-validation evidence bundle for this waveform."""

        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        quantity_array = self.quantity_array()
        provenance = quantity_array.provenance
        origin_payload = (
            {
                "data_origin": provenance.data_origin.value,
                "evidence_purpose": provenance.evidence_purpose.value,
                "origin_detail": provenance.origin_detail,
            }
            if isinstance(provenance, ResultProvenance)
            else {
                "data_origin": "unknown",
                "evidence_purpose": "measurement_result",
                "origin_detail": None,
            }
        )
        reductions = self.reductions()
        exports = waveform_reductions_to_digital_exports(
            reductions,
            identifier_prefix=identifier_prefix or f"waveform-ch{self.channel or 'x'}",
            allow_incomplete=True,
        )
        payload = {
            "schema": "pytestlab.waveform_result_evidence.v1",
            "generated_utc": datetime.now(UTC).isoformat(),
            "instrument": self.instrument,
            "channel": self.channel,
            "point_count": self.point_count,
            "unit": self.unit,
            **origin_payload,
            "waveform_sha256": hashlib.sha256(self.values.tobytes()).hexdigest(),
            "time_sha256": hashlib.sha256(self.time.tobytes()).hexdigest()
            if self.time is not None
            else None,
            "acquisition": self.acquisition.to_dict(),
            "uncertainty_model": self.model.to_dict(),
            "metrics": {
                name: {
                    "nominal": q.nominal,
                    "standard_uncertainty": q.u,
                    "unit": q.unit,
                    "data_origin": q.provenance.data_origin.value
                    if isinstance(q.provenance, ResultProvenance)
                    else "unknown",
                    "evidence_purpose": q.provenance.evidence_purpose.value
                    if isinstance(q.provenance, ResultProvenance)
                    else "measurement_result",
                    "method": getattr(q.measurement_model, "method", None),
                    "budget": q.budget().to_dicts(),
                }
                for name, q in reductions.items()
            },
            "digital_exports": _hash_export_xml(exports),
            "non_accreditation_notice": (
                "PyTestLab waveform evidence is software-validation evidence, not accreditation, "
                "not a signed DCC, and not a calibration certificate."
            ),
        }
        payload["payload_sha256"] = hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        path = out / "waveform_evidence.json"
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8"
        )
        return path


def _hash_export_xml(exports: dict[str, Any]) -> dict[str, Any]:
    copied = {k: v for k, v in exports.items() if k != "reductions"}
    copied["reductions"] = {}
    for name, item in exports.get("reductions", {}).items():
        copied["reductions"][name] = {
            "identifier": item.get("identifier"),
            "dsi": item.get("dsi"),
            "dcc_xml_sha256": hashlib.sha256(str(item.get("dcc_xml", "")).encode()).hexdigest(),
            "measurement_model_method": item.get("measurement_model_method"),
            "data_origin": item.get("data_origin"),
            "evidence_purpose": item.get("evidence_purpose"),
        }
    return copied
