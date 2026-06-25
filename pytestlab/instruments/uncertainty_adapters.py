from __future__ import annotations

from typing import Any
from typing import Literal
from typing import Protocol

from ..uncertainty import DataOrigin
from ..uncertainty import EvidencePurpose
from ..uncertainty import MeasurementModel
from ..uncertainty import Quantity
from ..uncertainty import ResultProvenance
from ..uncertainty import resolve_traceability_ref
from ..uncertainty.specs import AccuracyModel
from ..uncertainty.specs import UncertaintyContext
from ..uncertainty.specs import evaluate_quantity


class _Logger(Protocol):
    def debug(self, message: str) -> None: ...

    def warning(self, message: str) -> None: ...

    def info(self, message: str) -> None: ...


def _source_key(instrument_key: str | None, function: Any, range_value: Any) -> str | None:
    """Stable atom-identity prefix so systematic terms correlate across reads.

    Encodes instrument instance + function + range: reads at the same operating
    point share atoms (correlated systematics), different points do not.
    """

    if instrument_key is None:
        return None
    function_value = getattr(function, "value", function)
    return f"{instrument_key}:{function_value}:{range_value}"


def nonzero_uncertainty_quantity(
    spec: AccuracyModel,
    context: UncertaintyContext,
    *,
    logger: _Logger | None = None,
    label: str = "accuracy spec",
    warning_level: Literal["warning", "info"] = "warning",
    strict: bool = False,
) -> Quantity | None:
    """Evaluate an uncertainty model and return a quantity only when u is non-zero."""

    try:
        quantity = evaluate_quantity(spec, context)
    except Exception as exc:
        if strict:
            raise
        message = (
            f"Could not evaluate {label}: {exc}. Leaving caller's nominal-only "
            "non-report-grade Quantity in place."
        )
        if logger is not None:
            log_method = logger.info if warning_level == "info" else logger.warning
            log_method(message)
        return None

    if quantity.u > 0:
        if logger is not None:
            logger.debug(f"Applied {label}, value: {quantity}")
        return quantity

    if logger is not None:
        logger.debug(
            f"{label} resulted in u=0. Leaving caller's nominal-only "
            "non-report-grade Quantity in place."
        )
    return None


def nominal_measurement_quantity(
    reading: float,
    unit: str,
    *,
    function: str,
    reason: str,
    output_name: str | None = None,
) -> Quantity:
    """Return a measured nominal result with explicit non-report-grade provenance.

    This keeps driver return types uniform when profile metadata is incomplete:
    the acquisition succeeded, but the value is deliberately blocked from
    report-grade export until the profile/evidence gap is fixed.
    """

    quantity = Quantity.constant(float(reading), unit)
    quantity.measurement_model = MeasurementModel(
        output_name=output_name or function,
        output_unit=unit,
        function=function,
        method="gum_first_order",
        assumptions=[reason],
        dof_method="uncertainty_metadata_missing",
    )
    quantity.provenance = ResultProvenance.current(
        data_origin=DataOrigin.MEASURED,
        evidence_purpose=EvidencePurpose.MEASUREMENT_RESULT,
        origin_detail=reason,
        provenance_complete=False,
    )
    quantity.dof_method = "uncertainty_metadata_missing"
    return quantity


def dmm_range_value(function: Any, range_spec: Any) -> float | None:
    """Return the range value a DMM accuracy model should use for the selected function."""

    function_value = getattr(function, "value", function)
    field_by_function = {
        "VOLT:DC": "nominal_V",
        "VOLT:AC": "nominal_V",
        "CURR:DC": "nominal_A",
        "CURR:AC": "nominal_A",
        "RES": "nominal_ohm",
        "FRES": "nominal_ohm",
        "CAP": "nominal_F",
    }
    range_field = field_by_function.get(function_value)
    if range_field is not None:
        value = getattr(range_spec, range_field, None)
        if value is not None:
            return value
    return getattr(range_spec, "max", None) or getattr(range_spec, "max_val", None)


def dmm_measurement_context(
    *,
    reading: float,
    unit: str,
    function: Any,
    range_spec: Any,
    measurement_type: str,
    instrument_key: str | None = None,
) -> UncertaintyContext | None:
    range_value = dmm_range_value(function, range_spec)
    if range_value is None:
        return None
    function_value = getattr(function, "value", str(function))
    return UncertaintyContext(
        reading=reading,
        unit=unit,
        function=function_value,
        range_value=range_value,
        range_unit=unit,
        resolution=getattr(range_spec, "resolution", None),
        source_key=_source_key(instrument_key, function, range_value),
        metadata={"measurement_type": measurement_type},
    )


def psu_measurement_context(
    config: Any,
    *,
    channel: int,
    reading: float,
    unit: str,
    function: str,
    instrument_key: str | None = None,
) -> UncertaintyContext:
    channel_spec = config.channels[channel - 1]
    range_spec = channel_spec.voltage_range if unit == "V" else channel_spec.current_limit_range
    return UncertaintyContext(
        reading=reading,
        unit=unit,
        function=function,
        range_value=range_spec.max,
        range_unit=unit,
        resolution=range_spec.resolution,
        channel=channel,
        source_key=_source_key(
            f"{instrument_key}:ch{channel}" if instrument_key else None, function, range_spec.max
        ),
    )


def oscilloscope_measurement_context(
    config: Any,
    *,
    channel: int,
    reading: float,
    unit: str,
    function: str,
    instrument_key: str | None = None,
) -> UncertaintyContext:
    channel_range = config.channels[channel - 1].channel_range
    range_value = getattr(channel_range, "max", None)
    if range_value is None:
        range_value = getattr(channel_range, "max_val", None)
    traceability = resolve_traceability_ref(
        getattr(config, "calibration_certificates", None),
        function=function,
        channel=channel,
        range_value=range_value,
        unit=unit,
    )
    return UncertaintyContext(
        reading=reading,
        unit=unit,
        function=function,
        range_value=range_value,
        range_unit=unit,
        resolution=getattr(channel_range, "resolution", None),
        channel=channel,
        bandwidth=config.bandwidth,
        source_key=_source_key(
            f"{instrument_key}:ch{channel}" if instrument_key else None, function, range_value
        ),
        traceability=traceability,
    )


def dc_load_range_value(range_spec: Any, unit: str) -> float | None:
    if unit == "A":
        return range_spec.max_current_A
    if unit == "V":
        return range_spec.max_voltage_V
    return range_spec.max


def dc_load_readback_accuracy(readback_spec: Any, measurement_type: str) -> AccuracyModel | None:
    if measurement_type == "current":
        return readback_spec.current_accuracy
    if measurement_type == "voltage":
        return readback_spec.voltage_accuracy
    if measurement_type == "power":
        return readback_spec.power_accuracy
    return None


def dc_load_measurement_context(
    *,
    reading: float,
    unit: str,
    function: str,
    range_value: float | None,
    channel: int,
    instrument_key: str | None = None,
) -> UncertaintyContext:
    return UncertaintyContext(
        reading=reading,
        unit=unit,
        function=function,
        range_value=range_value,
        range_unit=unit,
        channel=channel,
        source_key=_source_key(instrument_key, function, range_value),
    )
