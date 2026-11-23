"""
Instrument driver for a DC Active Load. Provides methods to set the operating mode,
program the load value, enable/disable the output, and query measurements (current, voltage, power)
from the Keysight EL30000 Series bench DC electronic loads.
"""

from __future__ import annotations

from typing import Any
from typing import Literal

import numpy as np

from ..common.health import HealthReport
from ..common.health import HealthStatus
from ..config.dc_active_load_config import DCActiveLoadConfig
from ..config.dc_active_load_config import ModeSpec
from ..config.dc_active_load_config import ReadbackAccuracySpec
from ..config.instrument_config import InstrumentConfig
from ..errors import InstrumentCommunicationError
from ..errors import InstrumentConfigurationError
from ..errors import InstrumentParameterError
from ..experiments import MeasurementResult
from ..uncertainty import Quantity as MeasurementQuantity
from .instrument import Instrument
from .instrument import InstrumentIO
from .operation_contract import OperationDescriptor
from .uncertainty_adapters import dc_load_measurement_context
from .uncertainty_adapters import dc_load_range_value
from .uncertainty_adapters import dc_load_readback_accuracy
from .uncertainty_adapters import nominal_measurement_quantity
from .uncertainty_adapters import nonzero_uncertainty_quantity


class DCActiveLoad(Instrument):
    """Drives a DC Electronic Load instrument, such as the Keysight EL30000 series.

    This class provides a driver for controlling a DC Active Load, enabling
    programmatic control over its operating modes and settings. It is designed
    to work with SCPI-compliant instruments and leverages a detailed Pydantic
    configuration model to provide uncertainty-aware measurements and feature-rich
    control.

    The driver supports the following primary operations:
    - Setting the operating mode (Constant Current, Voltage, Power, Resistance).
    - Programming the load value for the current mode.
    - Enabling or disabling the load's input.
    - Measuring voltage, current, and power with uncertainty.
    - Configuring and controlling transient and battery test modes.
    """

    config: DCActiveLoadConfig  # Type hint for the specific config
    current_mode: str | None = None

    OPERATION_CONTRACT: tuple[OperationDescriptor, ...] = (
        OperationDescriptor("set_mode", public_method="set_mode"),
        OperationDescriptor("set_load", public_method="set_load"),
        OperationDescriptor("enable_input", public_method="enable_input"),
        OperationDescriptor(
            "is_input_enabled", public_method="is_input_enabled", safety_class="read"
        ),
        OperationDescriptor("short_input", public_method="short_input"),
        OperationDescriptor(
            "measure_current", public_method="measure_current", safety_class="read"
        ),
        OperationDescriptor(
            "measure_voltage", public_method="measure_voltage", safety_class="read"
        ),
        OperationDescriptor("measure_power", public_method="measure_power", safety_class="read"),
        OperationDescriptor("set_range", public_method="set_range"),
        OperationDescriptor("set_slew_rate", public_method="set_slew_rate", required=False),
        OperationDescriptor(
            "configure_transient_mode",
            public_method="configure_transient_mode",
            capability="transient",
            required=False,
        ),
        OperationDescriptor(
            "set_transient_level",
            public_method="set_transient_level",
            capability="transient",
            required=False,
        ),
        OperationDescriptor(
            "start_transient",
            public_method="start_transient",
            capability="transient",
            required=False,
        ),
        OperationDescriptor(
            "stop_transient", public_method="stop_transient", capability="transient", required=False
        ),
        OperationDescriptor(
            "enable_battery_test",
            public_method="enable_battery_test",
            capability="battery_test",
            required=False,
        ),
        OperationDescriptor(
            "get_battery_test_measurement",
            public_method="get_battery_test_measurement",
            capability="battery_test",
            safety_class="read",
            required=False,
        ),
        OperationDescriptor(
            "fetch_scope_data",
            public_method="fetch_scope_data",
            capability="data_acquisition",
            safety_class="read",
            required=False,
        ),
        OperationDescriptor(
            "fetch_datalogger_data",
            public_method="fetch_datalogger_data",
            capability="data_acquisition",
            safety_class="read",
            required=False,
        ),
        OperationDescriptor(
            "set_battery_cutoff_voltage",
            public_method="set_battery_cutoff_voltage",
            capability="battery_test",
            required=False,
        ),
        OperationDescriptor(
            "set_battery_cutoff_capacity",
            public_method="set_battery_cutoff_capacity",
            capability="battery_test",
            required=False,
        ),
        OperationDescriptor(
            "set_battery_cutoff_timer",
            public_method="set_battery_cutoff_timer",
            capability="battery_test",
            required=False,
        ),
    )

    def __init__(self, config: DCActiveLoadConfig, backend: InstrumentIO, **kwargs: Any) -> None:
        super().__init__(config, backend, **kwargs)
        self.current_mode = None

    @classmethod
    def from_config(
        cls: type[DCActiveLoad], config: InstrumentConfig, debug_mode: bool = False
    ) -> DCActiveLoad:
        """
        Direct construction is disabled because backend selection is handled by AutoInstrument.
        """
        raise NotImplementedError(
            "DCActiveLoad.from_config() does not select communication backends. "
            "Use AutoInstrument.from_config() or instantiate DCActiveLoad with an explicit backend."
        )

    def set_mode(self, mode: str) -> None:
        """Sets the operating mode of the electronic load.

        This method configures the load to operate in one of the supported modes.
        The mode determines what physical quantity the load will attempt to keep
        constant.

        The supported modes are:
        - "CC": Constant Current
        - "CV": Constant Voltage
        - "CP": Constant Power
        - "CR": Constant Resistance

        Args:
            mode: The desired operating mode. The input is case-insensitive.

        Raises:
            InstrumentParameterError: If the specified mode is not supported.
        """
        resolved = self._resolve_operation_parameter("set_mode", "mode", mode)
        for cmd in self._scpi_engine.build("set_mode", mode=resolved.transport_value):
            self._send_command(cmd)
        # Keep the driver's state in the semantic form used by dependent
        # operation resolution and by the legacy mode-specific aliases.
        self.current_mode = str(resolved.value).upper()
        self._logger.info(f"Operating mode set to {self.current_mode} via SCPIEngine.")

    def _select_mode(self, operation_id: str, mode: str | None = None) -> tuple[str, Any]:
        """Resolve an operation mode and activate it when explicitly selected."""
        selected = mode if mode is not None else self.current_mode
        if selected is None:
            message = {
                "set_load": "Load mode has not been set. Call set_mode() first.",
                "set_slew_rate": "Mode must be set before setting slew rate.",
                "set_range": "Mode must be set before setting range.",
                "set_transient_level": "Mode must be set before setting transient level.",
            }.get(operation_id, "Mode must be set before this operation.")
            raise InstrumentParameterError(message)
        resolved = self._resolve_operation_parameter(operation_id, "mode", selected)
        canonical = str(resolved.value).upper()
        if mode is not None and self.current_mode != canonical:
            self.set_mode(canonical)
        return canonical, resolved.transport_value

    def set_load(self, value: float, mode: str | None = None) -> None:
        """Programs the load's setpoint for the current operating mode.

        This method sets the target value that the load will maintain. The unit
        of the `value` argument depends on the currently active mode:
        - "CC" mode: `value` is in Amperes (A).
        - "CV" mode: `value` is in Volts (V).
        - "CP" mode: `value` is in Watts (W).
        - "CR" mode: `value` is in Ohms (Ω).

        Args:
            value: The target value for the load.
            mode: Optional semantic mode to activate before setting the value.
                   When omitted, the previously selected mode is used.

        Raises:
            InstrumentParameterError: If the operating mode has not been set first
                                      by calling `set_mode()`.
        """
        selected_mode, _mode_transport = self._select_mode("set_load", mode)
        resolved = self._resolve_operation_parameter(
            "set_load", "value", value, context={"mode": selected_mode}
        )
        value = resolved.transport_value

        cmd_name = self.config.mode_load_aliases.get(selected_mode)
        if cmd_name:
            for cmd in self._scpi_engine.build(cmd_name, value=value):
                self._send_command(cmd)
            self._logger.info(f"Load value set to {value} in mode {selected_mode}.")
        else:
            raise InstrumentParameterError(
                f"Profile does not declare a load-value operation for mode '{selected_mode}'."
            )

    def enable_input(self, state: bool, channel: int = 1) -> None:
        """Enables or disables the load's input.

        Args:
            state: True to enable the input, False to disable.
            channel: The channel to control (default is 1).
        """
        resolved = self._resolve_operation_arguments(
            "enable_input", {"state": state, "channel": channel}
        ).get("enable_input", {})
        for cmd in self._scpi_engine.build(
            "set_input_state",
            state=resolved.get("state", state),
            channel=resolved.get("channel", channel),
        ):
            self._send_command(cmd)
        self._logger.info(f"Input on channel {channel} turned {'ON' if state else 'OFF'}.")

    def is_input_enabled(self, channel: int = 1) -> bool:
        """Queries the state of the load's input.

        Returns:
            True if the input is enabled, False otherwise.
        """
        channel = int(
            self._resolve_operation_parameter("is_input_enabled", "channel", channel).value
        )
        q = self._scpi_engine.build("get_input_state", channel=channel)[0]
        response = self._query(q)
        s = response.strip().upper()
        return s in ("1", "ON", "TRUE")

    def short_input(self, state: bool, channel: int = 1) -> None:
        """Enables or disables a short circuit on the input.

        Args:
            state: True to enable the short, False to disable.
            channel: The channel to control (default is 1).
        """
        resolved = self._resolve_operation_arguments(
            "short_input", {"state": state, "channel": channel}
        ).get("short_input", {})
        for cmd in self._scpi_engine.build(
            "input_short_state",
            state=resolved.get("state", state),
            channel=resolved.get("channel", channel),
        ):
            self._send_command(cmd)
        self._logger.info(f"Input short on channel {channel} turned {'ON' if state else 'OFF'}.")

    def set_slew_rate(self, rate: float | str, channel: int = 1, mode: str | None = None) -> None:
        """Sets the slew rate for the current operating mode.

        Args:
            rate: The desired slew rate. Units depend on the mode (A/s, V/s, etc.).
                  Can also be "MIN", "MAX", or "INF".
            channel: The channel to configure (default is 1).
            mode: Optional semantic mode to activate before setting the slew rate.
        """
        selected_mode, mode_transport = self._select_mode("set_slew_rate", mode)
        resolved = self._resolve_operation_arguments(
            "set_slew_rate",
            {"rate": rate, "channel": channel},
            context={"mode": selected_mode},
        ).get("set_slew_rate", {})
        for cmd in self._scpi_engine.build(
            "mode_set_slew",
            mode=mode_transport,
            rate=resolved.get("rate", rate),
            channel=resolved.get("channel", channel),
        ):
            self._send_command(cmd)
        self._logger.info(
            f"Slew rate for mode {self.current_mode} on channel {channel} set to {rate}."
        )

    def set_range(self, value: float | str, channel: int = 1, mode: str | None = None) -> None:
        """Sets the operating range for the current mode.

        Args:
            value: The maximum expected value to set the range. Can also be "MIN" or "MAX".
            channel: The channel to configure (default is 1).
            mode: Optional semantic mode to activate before setting the range.
        """
        selected_mode, mode_transport = self._select_mode("set_range", mode)
        resolved = self._resolve_operation_arguments(
            "set_range",
            {"value": value, "channel": channel},
            context={"mode": selected_mode},
        ).get("set_range", {})
        for cmd in self._scpi_engine.build(
            "mode_set_range",
            mode=mode_transport,
            value=resolved.get("value", value),
            channel=resolved.get("channel", channel),
        ):
            self._send_command(cmd)
        self._logger.info(
            f"Range for mode {self.current_mode} on channel {channel} set for value {value}."
        )

    def _get_readback_spec(
        self, mode: str, unit: str
    ) -> tuple[ReadbackAccuracySpec, float | None] | None:
        """Helper to find the correct readback accuracy spec from the config."""
        mode_map_to_config: dict[str, ModeSpec | None] = {
            "CC": self.config.operating_modes.constant_current_CC,
            "CV": self.config.operating_modes.constant_voltage_CV,
            "CP": self.config.operating_modes.constant_power_CP,
            "CR": self.config.operating_modes.constant_resistance_CR,
        }
        mode_spec = mode_map_to_config.get(mode)
        if not mode_spec:
            return None

        # Query the instrument's current range maximum via SCPI engine
        try:
            q = self._scpi_engine.build("mode_get_range", quantity=unit)[0]
            instrument_max_range = float(self._scpi_engine.parse("mode_get_range", self._query(q)))
        except (InstrumentCommunicationError, ValueError):
            self._logger.info(f"Could not query range for {unit}; cannot determine uncertainty.")
            return None

        # Find the best matching range spec from the config
        best_match_spec = None
        min_delta = float("inf")

        for r_spec in mode_spec.ranges:
            spec_max_val = 0.0
            if unit == "A" and r_spec.max_current_A is not None:
                spec_max_val = r_spec.max_current_A
            elif unit == "V" and r_spec.max_voltage_V is not None:
                spec_max_val = r_spec.max_voltage_V

            if spec_max_val > 0:
                delta = abs(spec_max_val * 1.02 - instrument_max_range)
                if delta < min_delta:
                    min_delta = delta
                    best_match_spec = r_spec

        if best_match_spec and best_match_spec.readback_accuracy:
            range_value = dc_load_range_value(best_match_spec, unit)
            return best_match_spec.readback_accuracy, range_value
        return None

    def _measure_with_uncertainty(
        self, measurement_type: Literal["current", "voltage", "power"], channel: int = 1
    ) -> MeasurementResult:
        """Internal helper to perform a measurement and calculate uncertainty."""
        operation_id = f"measure_{measurement_type}"
        resolved = self._resolve_operation_parameter(operation_id, "quantity", measurement_type)
        unit = resolved.option.unit if resolved.option and resolved.option.unit else ""
        if not unit:
            raise InstrumentConfigurationError(
                self.config.model,
                f"Profile does not declare a unit for '{operation_id}'.",
            )
        # Use the private profile mapping to build the measurement query.
        q = self._scpi_engine.build("measure", quantity=resolved.transport_value, channel=channel)[
            0
        ]
        reading = float(self._scpi_engine.parse("measure", self._query(q)))

        value_to_return: float | MeasurementQuantity = nominal_measurement_quantity(
            reading,
            unit,
            function=measurement_type,
            output_name=f"{measurement_type}_ch{channel}",
            reason=(
                f"{self.config.model} {measurement_type} channel {channel}: no applied "
                "uncertainty metadata yet; result is nominal-only and non-report-grade."
            ),
        )

        # Find and apply accuracy spec if mode is set
        if self.current_mode:
            readback_match = self._get_readback_spec(self.current_mode, unit)
            if readback_match:
                readback_spec, range_value = readback_match
                accuracy_spec = dc_load_readback_accuracy(readback_spec, measurement_type)

                if accuracy_spec:
                    context = dc_load_measurement_context(
                        reading=reading,
                        unit=unit,
                        function=measurement_type,
                        range_value=range_value,
                        channel=channel,
                        instrument_key=self._uncertainty_source_key(),
                    )
                    quantity = nonzero_uncertainty_quantity(
                        accuracy_spec,
                        context,
                        logger=self._logger,
                        label=f"accuracy spec for {measurement_type}",
                        warning_level="info",
                        strict=self.config.uncertainty_strict,
                    )
                    if quantity is not None:
                        value_to_return = quantity
                        self._logger.info(f"Measured {measurement_type}: {value_to_return} {unit}")
                else:
                    value_to_return = nominal_measurement_quantity(
                        reading,
                        unit,
                        function=measurement_type,
                        output_name=f"{measurement_type}_ch{channel}",
                        reason=(
                            f"{self.config.model} {measurement_type} channel {channel}: "
                            "no readback accuracy spec available; add readback_accuracy."
                        ),
                    )
                    self._logger.info(
                        "Warning: No accuracy spec available for %s. Returning nominal-only "
                        "non-report-grade Quantity.",
                        measurement_type,
                    )
            else:
                value_to_return = nominal_measurement_quantity(
                    reading,
                    unit,
                    function=measurement_type,
                    output_name=f"{measurement_type}_ch{channel}",
                    reason=(
                        f"{self.config.model} {measurement_type} channel {channel}: no matching "
                        "readback spec found for the current mode."
                    ),
                )
                self._logger.info(
                    "Warning: No matching readback spec found for %s. Returning nominal-only "
                    "non-report-grade Quantity.",
                    measurement_type,
                )
        else:
            self._logger.info(
                "Warning: Mode not set, cannot determine measurement uncertainty. Returning "
                "nominal-only non-report-grade Quantity."
            )

        if not isinstance(value_to_return, float | MeasurementQuantity):
            value_to_return = float(value_to_return)

        return MeasurementResult(
            values=value_to_return,
            instrument=self.config.model,
            units=unit,
            measurement_type=measurement_type.capitalize(),
        )

    def measure_current(self) -> MeasurementResult:
        """Measures the sinking current, including uncertainty if available."""
        return self._measure_with_uncertainty("current")

    def measure_voltage(self) -> MeasurementResult:
        """Measures the voltage across the load, including uncertainty if available."""
        return self._measure_with_uncertainty("voltage")

    def measure_power(self) -> MeasurementResult:
        """Measures the power being dissipated, including uncertainty if available."""
        return self._measure_with_uncertainty("power")

    # --- Transient System Methods ---
    def configure_transient_mode(
        self, mode: Literal["CONTinuous", "PULSe", "TOGGle", "LIST"], channel: int = 1
    ) -> None:
        """Sets the operating mode of the transient generator."""
        resolved = self._resolve_operation_arguments(
            "configure_transient_mode", {"mode": mode, "channel": channel}
        ).get("configure_transient_mode", {})
        for cmd in self._scpi_engine.build(
            "transient_set_mode",
            mode=resolved.get("mode", mode),
            channel=resolved.get("channel", channel),
        ):
            self._send_command(cmd)

    def set_transient_level(self, value: float, channel: int = 1, mode: str | None = None) -> None:
        """Sets the secondary transient level for the selected operating mode."""
        selected_mode, mode_transport = self._select_mode("set_transient_level", mode)
        resolved = self._resolve_operation_arguments(
            "set_transient_level",
            {"value": value, "channel": channel},
            context={"mode": selected_mode},
        ).get("set_transient_level", {})
        for cmd in self._scpi_engine.build(
            "transient_set_level",
            mode=mode_transport,
            value=resolved.get("value", value),
            channel=resolved.get("channel", channel),
        ):
            self._send_command(cmd)

    def start_transient(self, continuous: bool = False, channel: int = 1) -> None:
        """Initiates the transient trigger system."""
        resolved = self._resolve_operation_arguments(
            "start_transient", {"continuous": continuous, "channel": channel}
        ).get("start_transient", {})
        for cmd in self._scpi_engine.build(
            "transient_start",
            state=resolved.get("state", continuous),
            channel=resolved.get("channel", channel),
        ):
            self._send_command(cmd)

    def stop_transient(self, channel: int = 1) -> None:
        """Aborts any pending or in-progress transient operations."""
        channel = int(self._resolve_operation_parameter("stop_transient", "channel", channel).value)
        for cmd in self._scpi_engine.build("transient_abort", channel=channel):
            self._send_command(cmd)

    # --- Battery Test Methods ---
    def enable_battery_test(self, state: bool, channel: int = 1) -> None:
        """Enables or disables the battery test operation."""
        resolved = self._resolve_operation_arguments(
            "enable_battery_test", {"state": state, "channel": channel}
        ).get("enable_battery_test", {})
        for cmd in self._scpi_engine.build(
            "battery_enable",
            state=resolved.get("state", state),
            channel=resolved.get("channel", channel),
        ):
            self._send_command(cmd)

    def set_battery_cutoff_voltage(
        self, voltage: float, state: bool = True, channel: int = 1
    ) -> None:
        """Configures the voltage cutoff condition for the battery test."""
        resolved = self._resolve_operation_arguments(
            "set_battery_cutoff_voltage", {"state": state, "channel": channel}
        ).get("set_battery_cutoff_voltage", {})
        voltage = self._resolve_operation_parameter(
            "set_battery_cutoff_voltage", "voltage", voltage
        ).transport_value
        for cmd in self._scpi_engine.build(
            "battery_cutoff_voltage_state",
            state=resolved.get("state", state),
            channel=resolved.get("channel", channel),
        ):
            self._send_command(cmd)
        for cmd in self._scpi_engine.build(
            "battery_cutoff_voltage", voltage=voltage, channel=resolved.get("channel", channel)
        ):
            self._send_command(cmd)

    def set_battery_cutoff_capacity(
        self, capacity: float, state: bool = True, channel: int = 1
    ) -> None:
        """Configures the capacity (Ah) cutoff condition for the battery test."""
        resolved = self._resolve_operation_arguments(
            "set_battery_cutoff_capacity", {"state": state, "channel": channel}
        ).get("set_battery_cutoff_capacity", {})
        capacity = self._resolve_operation_parameter(
            "set_battery_cutoff_capacity", "capacity", capacity
        ).transport_value
        for cmd in self._scpi_engine.build(
            "battery_cutoff_capacity_state",
            state=resolved.get("state", state),
            channel=resolved.get("channel", channel),
        ):
            self._send_command(cmd)
        for cmd in self._scpi_engine.build(
            "battery_cutoff_capacity", capacity=capacity, channel=resolved.get("channel", channel)
        ):
            self._send_command(cmd)

    def set_battery_cutoff_timer(self, time_s: float, state: bool = True, channel: int = 1) -> None:
        """Configures the timer (seconds) cutoff condition for the battery test."""
        resolved = self._resolve_operation_arguments(
            "set_battery_cutoff_timer", {"state": state, "channel": channel}
        ).get("set_battery_cutoff_timer", {})
        time_s = self._resolve_operation_parameter(
            "set_battery_cutoff_timer", "time_s", time_s
        ).transport_value
        for cmd in self._scpi_engine.build(
            "battery_cutoff_timer_state",
            state=resolved.get("state", state),
            channel=resolved.get("channel", channel),
        ):
            self._send_command(cmd)
        for cmd in self._scpi_engine.build(
            "battery_cutoff_timer", time_s=time_s, channel=resolved.get("channel", channel)
        ):
            self._send_command(cmd)

    def get_battery_test_measurement(
        self, metric: Literal["capacity", "power", "time"], channel: int = 1
    ) -> float:
        """Queries a measurement from the ongoing battery test."""
        resolved = self._resolve_operation_arguments(
            "get_battery_test_measurement", {"metric": metric, "channel": channel}
        ).get("get_battery_test_measurement", {})
        q = self._scpi_engine.build(
            "battery_measure",
            metric=resolved.get("metric", metric),
            channel=resolved.get("channel", channel),
        )[0]
        return float(self._scpi_engine.parse("battery_measure", self._query(q)))

    # --- Data Acquisition Methods ---
    def fetch_scope_data(
        self, measurement: Literal["current", "voltage", "power"], channel: int = 1
    ) -> np.ndarray:
        """Fetches the captured waveform (scope) data as a NumPy array."""
        # Removed unused scpi_map (mapping was unused).
        resolved = self._resolve_operation_arguments(
            "fetch_scope_data", {"measurement": measurement, "channel": channel}
        ).get("fetch_scope_data", {})
        raw_block = self._query_raw(
            self._scpi_engine.build(
                "fetch_array",
                quantity=resolved.get("quantity", measurement),
                channel=resolved.get("channel", channel),
            )[0]
        )
        data_bytes = self._scpi_engine.parse("fetch_array", raw_block)
        return np.frombuffer(data_bytes, dtype=np.float32)

    def fetch_datalogger_data(self, num_points: int, channel: int = 1) -> list[float]:
        """Fetches the specified number of logged data points."""
        resolved = self._resolve_operation_arguments(
            "fetch_datalogger_data", {"num_points": num_points, "channel": channel}
        ).get("fetch_datalogger_data", {})
        q = self._scpi_engine.build(
            "fetch_datalogger",
            points=resolved.get("num_points", num_points),
            channel=resolved.get("channel", channel),
        )[0]
        resp = self._query(q)
        return list(self._scpi_engine.parse("fetch_datalogger", resp))

    def health_check(self) -> HealthReport:
        """Performs a health check on the DC Electronic Load."""
        report = HealthReport()
        try:
            report.instrument_idn = self.id()
            errors = self.get_all_errors()
            if errors:
                report.status = HealthStatus.WARNING
                report.warnings.extend([f"Stored Error: {code} - {msg}" for code, msg in errors])
            else:
                report.status = HealthStatus.OK
        except Exception as e:
            report.status = HealthStatus.ERROR
            report.errors.append(f"Health check failed: {e}")
        return report
