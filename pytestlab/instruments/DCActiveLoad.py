"""
Instrument driver for a DC Active Load. Provides methods to set the operating mode,
program the load value, enable/disable the output, and query measurements (current, voltage, power)
from the Keysight EL30000 Series bench DC electronic loads.
"""

from __future__ import annotations

from typing import Any
from typing import Literal

import numpy as np
from uncertainties.core import UFloat

from ..common.health import HealthReport
from ..common.health import HealthStatus
from ..config.dc_active_load_config import DCActiveLoadConfig
from ..config.dc_active_load_config import ModeSpec
from ..config.dc_active_load_config import ReadbackAccuracySpec
from ..config.instrument_config import InstrumentConfig
from ..errors import InstrumentCommunicationError
from ..errors import InstrumentParameterError
from ..experiments import MeasurementResult
from ..uncertainty import Quantity as MeasurementQuantity
from .instrument import Instrument
from .instrument import InstrumentIO
from .uncertainty_adapters import dc_load_measurement_context
from .uncertainty_adapters import dc_load_range_value
from .uncertainty_adapters import dc_load_readback_accuracy
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
        mode_upper = mode.upper()
        valid_modes = ["CC", "CV", "CP", "CR"]
        if mode_upper not in valid_modes:
            raise InstrumentParameterError(
                parameter="mode",
                value=mode,
                valid_range=valid_modes,
                message=f"Unsupported mode '{mode}'. Valid modes are: {', '.join(valid_modes)}.",
            )
        for cmd in self.scpi_engine.build("set_mode", mode=mode_upper):
            self._send_command(cmd)
        self.current_mode = mode_upper
        self._logger.info(f"Operating mode set to {mode_upper} via SCPIEngine.")

    def set_load(self, value: float) -> None:
        """Programs the load's setpoint for the current operating mode.

        This method sets the target value that the load will maintain. The unit
        of the `value` argument depends on the currently active mode:
        - "CC" mode: `value` is in Amperes (A).
        - "CV" mode: `value` is in Volts (V).
        - "CP" mode: `value` is in Watts (W).
        - "CR" mode: `value` is in Ohms (Ω).

        Args:
            value: The target value for the load.

        Raises:
            InstrumentParameterError: If the operating mode has not been set first
                                      by calling `set_mode()`.
        """
        if self.current_mode is None:
            raise InstrumentParameterError("Load mode has not been set. Call set_mode() first.")

        command_map = {
            "CC": ("set_current_level", "CURRent"),
            "CV": ("set_voltage_level", "VOLTage"),
            "CP": ("set_power_level", "POWer"),
            "CR": ("set_resistance_level", "RESistance"),
        }
        mapping = command_map.get(self.current_mode)

        if mapping:
            cmd_name, _legacy_prefix = mapping
            for cmd in self.scpi_engine.build(cmd_name, value=value):
                self._send_command(cmd)
            self._logger.info(
                f"Load value set to {value} in mode {self.current_mode} via SCPIEngine."
            )
        else:
            raise InstrumentParameterError(
                f"Internal error: Unknown current_mode '{self.current_mode}'."
            )

    def enable_input(self, state: bool, channel: int = 1) -> None:
        """Enables or disables the load's input.

        Args:
            state: True to enable the input, False to disable.
            channel: The channel to control (default is 1).
        """
        for cmd in self.scpi_engine.build("set_input_state", state=state, channel=channel):
            self._send_command(cmd)
        self._logger.info(f"Input on channel {channel} turned {'ON' if state else 'OFF'}.")

    def is_input_enabled(self, channel: int = 1) -> bool:
        """Queries the state of the load's input.

        Returns:
            True if the input is enabled, False otherwise.
        """
        q = self.scpi_engine.build("get_input_state", channel=channel)[0]
        response = self._query(q)
        s = response.strip().upper()
        return s in ("1", "ON", "TRUE")

    def short_input(self, state: bool, channel: int = 1) -> None:
        """Enables or disables a short circuit on the input.

        Args:
            state: True to enable the short, False to disable.
            channel: The channel to control (default is 1).
        """
        for cmd in self.scpi_engine.build("input_short_state", state=state, channel=channel):
            self._send_command(cmd)
        self._logger.info(f"Input short on channel {channel} turned {'ON' if state else 'OFF'}.")

    def set_slew_rate(self, rate: float | str, channel: int = 1) -> None:
        """Sets the slew rate for the current operating mode.

        Args:
            rate: The desired slew rate. Units depend on the mode (A/s, V/s, etc.).
                  Can also be "MIN", "MAX", or "INF".
            channel: The channel to configure (default is 1).
        """
        if self.current_mode is None:
            raise InstrumentParameterError("Mode must be set before setting slew rate.")

        for cmd in self.scpi_engine.build(
            "mode_set_slew", mode=self.current_mode, rate=rate, channel=channel
        ):
            self._send_command(cmd)
        self._logger.info(
            f"Slew rate for mode {self.current_mode} on channel {channel} set to {rate}."
        )

    def set_range(self, value: float | str, channel: int = 1) -> None:
        """Sets the operating range for the current mode.

        Args:
            value: The maximum expected value to set the range. Can also be "MIN" or "MAX".
            channel: The channel to configure (default is 1).
        """
        if self.current_mode is None:
            raise InstrumentParameterError("Mode must be set before setting range.")
        for cmd in self.scpi_engine.build(
            "mode_set_range", mode=self.current_mode, value=value, channel=channel
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
            q = self.scpi_engine.build("mode_get_range", quantity=unit)[0]
            instrument_max_range = float(self.scpi_engine.parse("mode_get_range", self._query(q)))
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
        scpi_map = {
            "current": ("CURRent", "A"),
            "voltage": ("VOLTage", "V"),
            "power": ("POWer", "W"),
        }
        _scpi_cmd, unit = scpi_map[measurement_type]

        # Use SCPI engine to measure atomically
        q = self.scpi_engine.build("measure", quantity=measurement_type, channel=channel)[0]
        reading = float(self.scpi_engine.parse("measure", self._query(q)))

        value_to_return: float | MeasurementQuantity = reading

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
                        instrument_key=f"{self.config.model}:{id(self)}",
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
                    self._logger.info(
                        f"Warning: No accuracy spec available for {measurement_type}. Returning float."
                    )
            else:
                self._logger.info(
                    f"Warning: No matching readback spec found for {measurement_type}. Returning float."
                )
        else:
            self._logger.info("Warning: Mode not set, cannot determine measurement uncertainty.")

        # Ensure value_to_return is a float or UFloat, not Variable
        try:
            from uncertainties import Variable

            if isinstance(value_to_return, Variable):
                # If not already a UFloat, cast to float
                if not isinstance(value_to_return, UFloat):
                    value_to_return = float(value_to_return.nominal_value)
        except ImportError:
            pass
        if not isinstance(value_to_return, float | UFloat | MeasurementQuantity):
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
        for cmd in self.scpi_engine.build("transient_set_mode", mode=mode.upper(), channel=channel):
            self._send_command(cmd)

    def set_transient_level(self, value: float, channel: int = 1) -> None:
        """Sets the secondary (transient) level for the current operating mode."""
        if self.current_mode is None:
            raise InstrumentParameterError("Mode must be set before setting transient level.")
        for cmd in self.scpi_engine.build(
            "transient_set_level", mode=self.current_mode, value=value, channel=channel
        ):
            self._send_command(cmd)

    def start_transient(self, continuous: bool = False, channel: int = 1) -> None:
        """Initiates the transient trigger system."""
        for cmd in self.scpi_engine.build(
            "transient_start", continuous=continuous, channel=channel
        ):
            self._send_command(cmd)

    def stop_transient(self, channel: int = 1) -> None:
        """Aborts any pending or in-progress transient operations."""
        for cmd in self.scpi_engine.build("transient_abort", channel=channel):
            self._send_command(cmd)

    # --- Battery Test Methods ---
    def enable_battery_test(self, state: bool, channel: int = 1) -> None:
        """Enables or disables the battery test operation."""
        for cmd in self.scpi_engine.build("battery_enable", state=state, channel=channel):
            self._send_command(cmd)

    def set_battery_cutoff_voltage(
        self, voltage: float, state: bool = True, channel: int = 1
    ) -> None:
        """Configures the voltage cutoff condition for the battery test."""
        for cmd in self.scpi_engine.build(
            "battery_cutoff_voltage_state", state=state, channel=channel
        ):
            self._send_command(cmd)
        if state:
            for cmd in self.scpi_engine.build(
                "battery_cutoff_voltage", voltage=voltage, channel=channel
            ):
                self._send_command(cmd)

    def set_battery_cutoff_capacity(
        self, capacity: float, state: bool = True, channel: int = 1
    ) -> None:
        """Configures the capacity (Ah) cutoff condition for the battery test."""
        for cmd in self.scpi_engine.build(
            "battery_cutoff_capacity_state", state=state, channel=channel
        ):
            self._send_command(cmd)
        if state:
            for cmd in self.scpi_engine.build(
                "battery_cutoff_capacity", capacity=capacity, channel=channel
            ):
                self._send_command(cmd)

    def set_battery_cutoff_timer(self, time_s: float, state: bool = True, channel: int = 1) -> None:
        """Configures the timer (seconds) cutoff condition for the battery test."""
        for cmd in self.scpi_engine.build(
            "battery_cutoff_timer_state", state=state, channel=channel
        ):
            self._send_command(cmd)
        if state:
            for cmd in self.scpi_engine.build(
                "battery_cutoff_timer", time_s=time_s, channel=channel
            ):
                self._send_command(cmd)

    def get_battery_test_measurement(
        self, metric: Literal["capacity", "power", "time"], channel: int = 1
    ) -> float:
        """Queries a measurement from the ongoing battery test."""
        q = self.scpi_engine.build("battery_measure", metric=metric, channel=channel)[0]
        return float(self.scpi_engine.parse("battery_measure", self._query(q)))

    # --- Data Acquisition Methods ---
    def fetch_scope_data(
        self, measurement: Literal["current", "voltage", "power"], channel: int = 1
    ) -> np.ndarray:
        """Fetches the captured waveform (scope) data as a NumPy array."""
        # Removed unused scpi_map (mapping was unused).
        raw_block = self._query_raw(
            self.scpi_engine.build("fetch_array", quantity=measurement, channel=channel)[0]
        )
        data_bytes = self.scpi_engine.parse("fetch_array", raw_block)
        return np.frombuffer(data_bytes, dtype=np.float32)

    def fetch_datalogger_data(self, num_points: int, channel: int = 1) -> list[float]:
        """Fetches the specified number of logged data points."""
        q = self.scpi_engine.build("fetch_datalogger", points=num_points, channel=channel)[0]
        resp = self._query(q)
        return list(self.scpi_engine.parse("fetch_datalogger", resp))

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
