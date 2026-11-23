"""Conditional, sensor-only RF power datasheet terms, not total DUT uncertainties."""

from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from math import isfinite
from math import log
from math import log10
from typing import TYPE_CHECKING
from typing import Any
from typing import Literal

from ..uncertainty import DataOrigin
from ..uncertainty import EvidencePurpose
from ..uncertainty import MeasurementModel
from ..uncertainty import Quantity
from ..uncertainty import ResultProvenance
from ..uncertainty import uq

if TYPE_CHECKING:
    from .PowerMeter import PowerAcquisition
    from .PowerMeter import PowerInputReflection

_KEYSIGHT_SOURCE = "https://www.keysight.com.cn/cn/zh/assets/7018-01515/data-sheets/5989-6278.pdf"
_RS_SOURCE = "https://www.rohde-schwarz.com/us/brochure-datasheet/nrp-a-an/"
_W_SCALE = {"W": 1.0, "mW": 1e-3, "uW": 1e-6}
_EXCLUSIONS = [
    "zero offset and drift",
    "measurement noise",
    "source mismatch and connections",
    "external path, attenuation, or correction uncertainty",
]


@dataclass(frozen=True)
class PowerCWConditions:
    """Known conditions at the sensor for a CW average-power reading.

    Supply the actual signal frequency and ambient temperature, not inferred
    values. Use only for a calibrated sensor at its native input plane without
    additional user corrections, after the manufacturer's required adjustments.
    These conditions are caller-supplied, not verified by the sensor driver.
    """

    frequency_hz: float
    ambient_temperature_c: float
    warmup_s: float
    zero_age_s: float | None = None
    temperature_storage_s: float | None = None
    path_selection: Literal["automatic", "fixed"] | None = None
    transition_offset_db: float | None = None
    accuracy_limit_distribution: Literal["rectangular", "triangular"] | None = None

    def __post_init__(self) -> None:
        for name in (
            "frequency_hz",
            "ambient_temperature_c",
            "warmup_s",
            "zero_age_s",
            "temperature_storage_s",
            "transition_offset_db",
        ):
            value = getattr(self, name)
            optional = name in {"zero_age_s", "temperature_storage_s", "transition_offset_db"}
            if value is None and optional:
                continue
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not isfinite(value)
            ):
                raise ValueError(f"{name} must be finite.")
            if name in {"warmup_s", "zero_age_s", "temperature_storage_s"} and value < 0:
                raise ValueError(f"{name} must be nonnegative.")
        if self.frequency_hz <= 0:
            raise ValueError("frequency_hz must be positive.")
        if self.path_selection not in (None, "automatic", "fixed"):
            raise ValueError("path_selection must be automatic or fixed.")
        if self.accuracy_limit_distribution not in (None, "rectangular", "triangular"):
            raise ValueError("accuracy_limit_distribution must be rectangular or triangular.")


def _attached_quantity(quantity: Quantity, assumption: str) -> dict[str, Any]:
    detail = (
        "Conditional datasheet sensor component only. Physical conditions and "
        "calibration are not verified by this software; no complete DUT uncertainty."
    )
    quantity.measurement_model = MeasurementModel(
        output_name="sensor_input_power",
        output_unit="W",
        function="rf_power",
        method="gum_first_order",
        assumptions=[detail, assumption],
    )
    quantity.provenance = ResultProvenance.current(
        data_origin=DataOrigin.MEASURED,
        evidence_purpose=EvidencePurpose.MEASUREMENT_RESULT,
        origin_detail=detail,
        provenance_complete=False,
    )
    return {
        "uncertainty_status": "datasheet_component",
        "uncertainty": {"kind": "quantity", "payload": quantity.to_dict()},
    }


def cw_accuracy(reading: PowerAcquisition, conditions: PowerCWConditions) -> dict[str, Any]:
    """Apply only explicitly modelled parts of the applicable published specification."""
    metadata = {
        "cw_conditions": asdict(conditions),
        "conditions_source": "caller_supplied_sensor_input",
    }

    def unavailable(reason: str) -> dict[str, Any]:
        return {**metadata, "uncertainty_status": "not_applicable", "uncertainty_reason": reason}

    settings = reading.settings
    if settings.mode != "average" or settings.trigger_source != "immediate":
        return unavailable("The datasheet model covers immediate scalar average power only.")
    if (
        conditions.frequency_hz != settings.correction_frequency_hz
        or conditions.frequency_hz != reading.correction_frequency_hz
    ):
        return unavailable("The signal and sensor compensation frequencies must match.")
    if conditions.warmup_s < 1800:
        return unavailable("The datasheet requires at least 30 minutes of sensor warm-up.")
    watts = (
        10 ** ((reading.value - 30) / 10)
        if reading.unit == "dBm" and -70 <= reading.value <= 23
        else reading.value * _W_SCALE.get(reading.unit, 0.0)
    )
    if not isfinite(watts) or watts <= 0:
        return unavailable("The reading is not a positive in-range absolute power.")
    dbm = reading.value if reading.unit == "dBm" else 10 * (log10(watts) + 3)
    temperature = conditions.ambient_temperature_c

    if settings.model == "U2000A":
        if not (
            1e7 <= conditions.frequency_hz <= 18e9 and -60 <= dbm <= 20 and 0 <= temperature <= 55
        ):
            return unavailable("The reading is outside the Keysight datasheet range.")
        if (
            settings.detector not in {"AVER", "AVERAGE"}
            or settings.averaging_mode != "manual"
            or settings.averaging_count != 1024
            or conditions.zero_age_s is None
        ):
            return unavailable(
                "Keysight requires Average-only detection, 1024 averages, and prior zeroing."
            )
        half_width_percent = 3.0 if 15 <= temperature <= 35 else 3.5
        output = {
            **metadata,
            "uncertainty_status": "accuracy_limit_only",
            "accuracy_limit": {
                "kind": "relative_limit",
                "half_width_percent": half_width_percent,
                "scope": "Average-only sensor accuracy (linearity, instrumentation and 50 MHz/0 dBm reference traceability)",
                "source": _KEYSIGHT_SOURCE,
                "source_location": "5989-6278EN, Average only mode power accuracy, notes 7–8",
                "excludes": [*_EXCLUSIONS, "frequency-dependent calibration factor uncertainty"],
            },
        }
        if (distribution := conditions.accuracy_limit_distribution) is not None:
            half_width_w = watts * half_width_percent / 100
            quantity = uq.limit(
                watts,
                half_width_w,
                unit="W",
                label="Keysight Average-only accuracy limit",
                source=_KEYSIGHT_SOURCE,
                distribution=distribution,
            )
            output.update(
                _attached_quantity(
                    quantity,
                    f"Caller selected a {distribution} Type B distribution for the hard limit.",
                )
            )
        return output

    if settings.model == "NRP18AN":
        if conditions.accuracy_limit_distribution is not None:
            return unavailable(
                "The R&S expanded uncertainty already specifies k=2, not a hard-limit distribution."
            )
        if not (
            8e3 <= conditions.frequency_hz <= 18e9 and -40 < dbm <= 23 and 20 <= temperature <= 25
        ):
            return unavailable(
                "The R&S sensor-only component is supported above −40 dBm, through +23 dBm, at +20 to +25 °C."
            )
        if (
            conditions.temperature_storage_s is None
            or conditions.temperature_storage_s < 10800
            or conditions.path_selection != "automatic"
            or conditions.transition_offset_db != 0.0
        ):
            return unavailable(
                "R&S requires three hours at operating temperature, automatic path selection, and a 0 dB transition offset."
            )
        # Datasheet p. 6 upper endpoint for the expanded absolute component
        # over the supported temperature band. Endnote 8 states k=2.
        expanded_db = 0.094
        standard_w = watts * log(10) / 10 * (expanded_db / 2)
        quantity = uq(
            watts, standard_w, unit="W", label="R&S datasheet sensor component", source=_RS_SOURCE
        )
        return {
            **metadata,
            **_attached_quantity(
                quantity, "First-order conversion from logarithmic power in dB to W."
            ),
            "accuracy_component": {
                "expanded_db": expanded_db,
                "coverage_factor": 2,
                "scope": "sensor calibration, linearity and temperature effect",
                "source": _RS_SOURCE,
                "source_location": "3607.0852.22 v15, pp. 3, 6, 26–29 and footnote 8",
                "excludes": _EXCLUSIONS.copy(),
            },
        }

    return unavailable("No CW power datasheet model is implemented for this sensor.")


def reported_reflection_uncertainty(reading: PowerInputReflection) -> dict[str, Any]:
    """Attach only the standard uncertainty of the reported reflection magnitude."""
    quantity = uq(
        reading.magnitude,
        reading.expanded_magnitude_uncertainty / reading.uncertainty_coverage_factor,
        unit="1",
        label="Sensor-reported input reflection magnitude",
        source="Native sensor reflection uncertainty readback (expanded, k=2)",
    )
    detail = (
        f"Native reflection magnitude at {reading.frequency_hz:g} Hz and "
        f"reference plane '{reading.reference_plane}'; not power or phase uncertainty."
    )
    quantity.provenance = ResultProvenance.current(
        data_origin=DataOrigin.MEASURED,
        evidence_purpose=EvidencePurpose.MEASUREMENT_RESULT,
        origin_detail=detail,
        provenance_complete=False,
    )
    return {"kind": "quantity", "payload": quantity.to_dict()}
