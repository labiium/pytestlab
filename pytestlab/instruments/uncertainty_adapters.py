from __future__ import annotations

from typing import Any
from typing import Literal
from typing import Protocol

from ..config.accuracy import AccuracyModel
from ..config.accuracy import MeasurementQuantity
from ..config.accuracy import UncertaintyContext
from ..config.accuracy import quantity_from_uncertainty_model


class _Logger(Protocol):
    def debug(self, message: str) -> None: ...

    def warning(self, message: str) -> None: ...

    def info(self, message: str) -> None: ...


def nonzero_uncertainty_quantity(
    spec: AccuracyModel,
    context: UncertaintyContext,
    *,
    logger: _Logger | None = None,
    label: str = "accuracy spec",
    warning_level: Literal["warning", "info"] = "warning",
    strict: bool = False,
) -> MeasurementQuantity | None:
    """Evaluate an uncertainty model and return a quantity only when sigma is non-zero."""

    try:
        quantity = quantity_from_uncertainty_model(spec, context)
    except Exception as exc:
        if strict:
            raise
        message = f"Could not evaluate {label}: {exc}. Returning float."
        if logger is not None:
            log_method = logger.info if warning_level == "info" else logger.warning
            log_method(message)
        return None

    if quantity.u > 0:
        if logger is not None:
            logger.debug(f"Applied {label}, value: {quantity}")
        return quantity

    if logger is not None:
        logger.debug(f"{label} resulted in sigma=0. Returning float.")
    return None


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
        metadata={"measurement_type": measurement_type},
    )


def psu_measurement_context(
    config: Any,
    *,
    channel: int,
    reading: float,
    unit: str,
    function: str,
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
    )


def oscilloscope_measurement_context(
    config: Any,
    *,
    channel: int,
    reading: float,
    unit: str,
    function: str,
) -> UncertaintyContext:
    channel_range = config.channels[channel - 1].channel_range
    range_value = getattr(channel_range, "max", None)
    if range_value is None:
        range_value = getattr(channel_range, "max_val", None)
    return UncertaintyContext(
        reading=reading,
        unit=unit,
        function=function,
        range_value=range_value,
        range_unit=unit,
        resolution=getattr(channel_range, "resolution", None),
        channel=channel,
        bandwidth=config.bandwidth,
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
) -> UncertaintyContext:
    return UncertaintyContext(
        reading=reading,
        unit=unit,
        function=function,
        range_value=range_value,
        range_unit=unit,
        channel=channel,
    )
