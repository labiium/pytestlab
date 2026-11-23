"""Conditional manufacturer components for an individual spectrum marker amplitude."""

from dataclasses import dataclass
from math import isfinite
from typing import Literal
from typing import TypeGuard

from ..uncertainty import MeasurementModel
from ..uncertainty import Quantity
from ..uncertainty import ResultProvenance
from ..uncertainty import uq
from ..uncertainty.atoms import AtomRegistry

SpectrumBoundDistribution = Literal["rectangular", "triangular"]

_KEYSIGHT_SPEC = (
    "https://www.keysight.com/us/en/assets/9018-04769/technical-specifications/9018-04769.pdf"
)
_FSW_SPEC = "https://www.rohde-schwarz.com/us/brochure-datasheet/fsw/"
# FSW specifications v15.01, p. 23. Bounds are inclusive at the upper edge.
_FSW_YIG_ON = ((10e6, 0.37), (3.6e9, 0.27), (8e9, 0.37), (22e9, 1.4), (26.5e9, 1.7))
_FSW_YIG_OFF = ((22e9, 1.0), (26.5e9, 1.2))


@dataclass(frozen=True, kw_only=True)
class SpectrumMarkerConditions:
    """Caller-verified conditions for the acquisition behind a held CW marker.

    Supply the live model, a reference to the setup/observation record, and the
    actual settings and input tone conditions. Do not substitute settings read
    after the sweep. Mark prerequisites met only after checking the vendor's
    warm-up, alignment, calibration-cycle and environment requirements and
    verifying that the marker measures the specified uncorrected single tone
    at the analyzer RF input. This evidence is not a calibration certificate.

    For N9000A, also supply actual VBW and whether required auto coupling with
    Accuracy sweep-time rules was in use. For FSW26, supply reference level,
    S/N, auto sweep time, electronic attenuation, YIG and input coupling state.
    """

    model: str
    evidence: str
    temperature_c: float
    tone_frequency_hz: float
    input_power_dbm: float
    span_hz: float
    rbw_hz: float
    attenuation_db: float
    preamp_on: bool
    prerequisites_met: bool = False
    vbw_hz: float | None = None
    accuracy_coupled: bool | None = None
    reference_level_dbm: float | None = None
    snr_db: float | None = None
    sweep_time_auto: bool | None = None
    electronic_attenuator_on: bool | None = None
    yig_preselector_on: bool | None = None
    dc_coupled: bool | None = None


def _finite(value: float | None) -> TypeGuard[float]:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)


def marker_amplitude_uncertainty(
    *,
    model: str | None,
    frequency_hz: float,
    amplitude_dbm: float,
    driver_readout: bool,
    conditions: SpectrumMarkerConditions | None,
    bound_distribution: SpectrumBoundDistribution | None,
) -> dict[str, object]:
    """Build serialized native uncertainty without changing the marker table."""

    def unavailable(reason: str, **details: object) -> dict[str, object]:
        return {
            "uncertainty_status": "unavailable",
            "uncertainty_field": "amplitude_dbm",
            "uncertainty_reason": reason,
            **details,
        }

    if not driver_readout or model not in ("N9000A", "FSW26"):
        return unavailable("Requires a marker readout from a supported analyzer profile.")
    if not isinstance(conditions, SpectrumMarkerConditions):
        return unavailable("Verified conditions for the captured sweep are missing.")
    if (
        conditions.model != model
        or not isinstance(conditions.evidence, str)
        or not conditions.evidence.strip()
        or conditions.prerequisites_met is not True
    ):
        return unavailable(
            "The live model, capture record, or vendor prerequisites are unverified."
        )
    if not all(
        _finite(value)
        for value in (
            amplitude_dbm,
            frequency_hz,
            conditions.tone_frequency_hz,
            conditions.input_power_dbm,
            conditions.temperature_c,
            conditions.span_hz,
            conditions.rbw_hz,
            conditions.attenuation_db,
        )
    ):
        return unavailable("Capture conditions or marker readout are not finite numbers.")
    if (
        conditions.tone_frequency_hz != frequency_hz
        or frequency_hz <= 0
        or not 20 <= conditions.temperature_c <= 30
        or conditions.preamp_on is not False
        or conditions.span_hz <= 0
        or conditions.rbw_hz <= 0
    ):
        return unavailable("Marker, ambient temperature, preamp, span, or RBW is outside scope.")
    exposure: dict[str, object] = {
        "model": conditions.model,
        "source": conditions.evidence.strip(),
        "vendor_prerequisites_met": True,
        "temperature_c": float(conditions.temperature_c),
        "tone_frequency_hz": float(conditions.tone_frequency_hz),
        "input_power_dbm": float(conditions.input_power_dbm),
        "span_hz": float(conditions.span_hz),
        "rbw_hz": float(conditions.rbw_hz),
        "attenuation_db": float(conditions.attenuation_db),
        "preamp_on": False,
    }
    budget: dict[str, object]
    registry = AtomRegistry()
    if model == "N9000A":
        vbw = conditions.vbw_hz
        if (
            frequency_hz != 50e6
            or not 1 <= conditions.rbw_hz <= 1e6
            or conditions.span_hz >= 5e6
            or conditions.attenuation_db != 10
            or not -50 <= conditions.input_power_dbm <= -10
            or conditions.accuracy_coupled is not True
            or not _finite(vbw)
            or not 0 < vbw <= 30e3
        ):
            return unavailable("The N9000A 50 MHz absolute-amplitude conditions are not met.")
        exposure.update(vbw_hz=float(vbw), accuracy_coupled=True)
        budget = {
            "source": _KEYSIGHT_SPEC,
            "specification": "9018-04769 pp. 14, 27–28, absolute amplitude accuracy at 50 MHz",
            "kind": "accuracy_limit",
            "half_width_db": 0.40,
        }
        if bound_distribution is None:
            return unavailable(
                "The vendor accuracy limit has no standard uncertainty without a selected distribution.",
                manufacturer_component=budget,
                condition_evidence=exposure,
            )
        budget["selected_type_b_distribution"] = bound_distribution
        quantity = uq.limit(
            amplitude_dbm,
            0.40,
            "dBm",
            distribution=bound_distribution,
            registry=registry,
            label="N9000A 50 MHz absolute amplitude",
            source=_KEYSIGHT_SPEC,
        )
        method = "caller_selected_type_b_distribution"
    else:
        ref, snr = conditions.reference_level_dbm, conditions.snr_db
        if (
            conditions.attenuation_db not in (10, 20, 30, 40)
            or conditions.electronic_attenuator_on is not False
            or conditions.sweep_time_auto is not True
            or conditions.span_hz / conditions.rbw_hz >= 100
            or not _finite(ref)
            or not 0 <= ref - conditions.input_power_dbm <= 70
            or not _finite(snr)
            or snr <= 20
            or (frequency_hz < 10e6 and conditions.dc_coupled is not True)
        ):
            return unavailable("FSW26 total level uncertainty conditions are not met.")
        if conditions.yig_preselector_on is True and 9e3 <= frequency_hz <= 26.5e9:
            table = _FSW_YIG_ON
        elif conditions.yig_preselector_on is False and 8e9 <= frequency_hz <= 26.5e9:
            table = _FSW_YIG_OFF
        else:
            return unavailable(
                "FSW26 YIG state or marker frequency has no applicable specification."
            )
        expanded = next(db for upper, db in table if frequency_hz <= upper)
        exposure.update(
            reference_level_dbm=float(ref),
            snr_db=float(snr),
            sweep_time_auto=True,
            electronic_attenuator_on=False,
            yig_preselector_on=conditions.yig_preselector_on,
        )
        if frequency_hz < 10e6:
            exposure["dc_coupled"] = True
        budget = {
            "source": _FSW_SPEC,
            "specification": "5215.6749.22 v15.01 pp. 4, 23, total measurement uncertainty",
            "kind": "expanded_uncertainty",
            "expanded_db": expanded,
            "coverage_factor": 2,
            "coverage_probability": 0.95,
        }
        quantity = uq(
            amplitude_dbm,
            expanded / 2,
            "dBm",
            registry=registry,
            label="FSW26 level uncertainty",
            source=_FSW_SPEC,
        )
        method = "published_expanded_uncertainty"
    return _component_result(quantity, method, budget, exposure)


def _component_result(
    quantity: Quantity,
    method: str,
    budget: dict[str, object],
    conditions: dict[str, object],
) -> dict[str, object]:
    detail = "Manufacturer-only contribution; capture conditions were supplied by the caller."
    quantity.measurement_model = MeasurementModel(
        output_name="amplitude_dbm",
        output_unit="dBm",
        function="spectrum_marker_amplitude",
        method="gum_first_order",
        assumptions=[detail, "Cross-reading covariance and external effects were not evaluated."],
        dof_method=method,
    )
    quantity.provenance = ResultProvenance(origin_detail=detail, provenance_complete=False)
    return {
        "uncertainty_status": "manufacturer_component",
        "uncertainty_field": "amplitude_dbm",
        "uncertainty_component_unit": "dB",
        "uncertainty": {"kind": "quantity", "payload": quantity.to_dict()},
        "manufacturer_component": budget,
        "condition_evidence": conditions,
        "correlation_status": "not_evaluated",
    }
