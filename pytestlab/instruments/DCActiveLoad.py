from __future__ import annotations

"""
Instrument driver for a DC Active Load. Provides methods to set the operating mode,
program the load value, enable/disable the output, and query measurements (current, voltage, power)
from the Keysight EL30000 Series bench DC electronic loads.
"""

import numpy as np
from typing import Optional, Union, Dict, Any, Literal, List
from uncertainties import ufloat
from uncertainties.core import UFloat


from .instrument import Instrument, AsyncInstrumentIO
from ..errors import InstrumentParameterError, InstrumentCommunicationError
from ..config.dc_active_load_config import DCActiveLoadConfig, ModeSpec, ReadbackAccuracySpec
from ..config.instrument_config import InstrumentConfig
from ..experiments import MeasurementResult
from ..common.health import HealthReport, HealthStatus


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
    current_mode: Optional[str] = None

    def __init__(self, config: DCActiveLoadConfig, backend: AsyncInstrumentIO, **kwargs: Any) -> None:
        super().__init__(config, backend, **kwargs)
        self.current_mode = None

    @classmethod
    def from_config(
        cls,
        config: "InstrumentConfig",
        backend: AsyncInstrumentIO,
        **kwargs: Any
    ) -> "DCActiveLoad":  # type: ignore[override]
        """
        Factory method for DCActiveLoad that requires a backend argument.
        Ensures config is a DCActiveLoadConfig.
        """
        if not isinstance(config, DCActiveLoadConfig):
            config = DCActiveLoadConfig(**dict(config))
        return cls(config=config, backend=backend, **kwargs)



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
        mode_map: Dict[str, str] = {
            "CC": "CURR",
            "CV": "VOLTage",
            "CP": "POWer",
            "CR": "RESistance"
        }
        if mode_upper not in mode_map:
            raise InstrumentParameterError(
                parameter="mode", value=mode, valid_range=list(mode_map.keys()),
                message=f"Unsupported mode '{mode}'. Valid modes are: {', '.join(mode_map.keys())}."
            )
        self._send_command(f"FUNC {mode_map[mode_upper]}")
        self.current_mode = mode_upper
        self._logger.info(f"Operating mode set to {mode_upper}.")

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

        command_map = {"CC": "CURRent", "CV": "VOLTage", "CP": "POWer", "CR": "RESistance"}
        scpi_param = command_map.get(self.current_mode)

        if scpi_param:
            self._send_command(f"{scpi_param}:LEVel:IMMediate:AMPLitude {value}")
            self._logger.info(f"Load value set to {value} in mode {self.current_mode}.")
        else:
            raise InstrumentParameterError(f"Internal error: Unknown current_mode '{self.current_mode}'.")

    def enable_input(self, state: bool, channel: int = 1) -> None:
        """Enables or disables the load's input.

        Args:
            state: True to enable the input, False to disable.
            channel: The channel to control (default is 1).
        """
        self._send_command(f"INPut:STATe {'ON' if state else 'OFF'}, (@{channel})")
        self._logger.info(f"Input on channel {channel} turned {'ON' if state else 'OFF'}.")

    def is_input_enabled(self, channel: int = 1) -> bool:
        """Queries the state of the load's input.

        Returns:
            True if the input is enabled, False otherwise.
        """
        response = self._query(f"INPut:STATe? (@{channel})")
        return response.strip() == '1'

    def short_input(self, state: bool, channel: int = 1) -> None:
        """Enables or disables a short circuit on the input.

        Args:
            state: True to enable the short, False to disable.
            channel: The channel to control (default is 1).
        """
        self._send_command(f"INPut:SHORt:STATe {'ON' if state else 'OFF'}, (@{channel})")
        self._logger.info(f"Input short on channel {channel} turned {'ON' if state else 'OFF'}.")

    def set_slew_rate(self, rate: Union[float, str], channel: int = 1) -> None:
        """Sets the slew rate for the current operating mode.

        Args:
            rate: The desired slew rate. Units depend on the mode (A/s, V/s, etc.).
                  Can also be "MIN", "MAX", or "INF".
            channel: The channel to configure (default is 1).
        """
        if self.current_mode is None:
            raise InstrumentParameterError("Mode must be set before setting slew rate.")

        command_map = {"CC": "CURRent", "CV": "VOLTage", "CP": "POWer", "CR": "RESistance"}
        scpi_param = command_map.get(self.current_mode)
        self._send_command(f"{scpi_param}:SLEW {rate}, (@{channel})")
        self._logger.info(f"Slew rate for mode {self.current_mode} on channel {channel} set to {rate}.")

    def set_range(self, value: Union[float, str], channel: int = 1) -> None:
        """Sets the operating range for the current mode.

        Args:
            value: The maximum expected value to set the range. Can also be "MIN" or "MAX".
            channel: The channel to configure (default is 1).
        """
        if self.current_mode is None:
            raise InstrumentParameterError("Mode must be set before setting range.")
        command_map = {"CC": "CURRent", "CV": "VOLTage", "CP": "POWer", "CR": "RESistance"}
        scpi_param = command_map.get(self.current_mode)
        self._send_command(f"{scpi_param}:RANGe {value}, (@{channel})")
        self._logger.info(f"Range for mode {self.current_mode} on channel {channel} set for value {value}.")

    def _get_readback_spec(self, mode: str, unit: str) -> Optional[ReadbackAccuracySpec]:
        """Helper to find the correct readback accuracy spec from the config."""
        mode_map_to_config: Dict[str, ModeSpec] = {
            "CC": self.config.operating_modes.constant_current_CC,
            "CV": self.config.operating_modes.constant_voltage_CV,
            "CP": self.config.operating_modes.constant_power_CP,
            "CR": self.config.operating_modes.constant_resistance_CR,
        }
        scpi_param_map = {"A": "CURRent", "V": "VOLTage", "W": "POWer", "Ohm": "RESistance"}

        mode_spec = mode_map_to_config.get(mode)
        if not mode_spec:
            return None

        # Query the instrument's current range maximum
        range_query_cmd = f"{scpi_param_map[unit]}:RANGe?"
        try:
            instrument_max_range = float(self._query(range_query_cmd))
        except (InstrumentCommunicationError, ValueError):
            self._logger.info(f"Could not query range for {unit}; cannot determine uncertainty.")
            return None

        # Find the best matching range spec from the config
        best_match_spec = None
        min_delta = float('inf')

        for r_spec in mode_spec.ranges:
            spec_max_val = 0.0
            if unit == 'A' and r_spec.max_current_A is not None:
                spec_max_val = r_spec.max_current_A
            elif unit == 'V' and r_spec.max_voltage_V is not None:
                spec_max_val = r_spec.max_voltage_V

            if spec_max_val > 0 and abs(spec_max_val * 1.02 - instrument_max_range) < min_delta:
                min_delta = abs(spec_max_val - instrument_max_range)
                best_match_spec = r_spec

        return best_match_spec.readback_accuracy if best_match_spec else None

    def _measure_with_uncertainty(
        self, measurement_type: Literal["current", "voltage", "power"], channel: int = 1
    ) -> MeasurementResult:
        """Internal helper to perform a measurement and calculate uncertainty."""
        scpi_map = {"current": ("CURR", "A"), "voltage": ("VOLT", "V"), "power": ("POW", "W")}
        scpi_cmd, unit = scpi_map[measurement_type]

        # A single MEASure command is atomic and prevents race conditions.
        response = self._query(f"MEASure:{scpi_cmd}? (@{channel})")
        reading = float(response)

        value_to_return: Union[float, UFloat] = reading

        # Find and apply accuracy spec if mode is set
        if self.current_mode:
            accuracy_spec = self._get_readback_spec(self.current_mode, unit)
            if accuracy_spec:
                std_dev = accuracy_spec.calculate_uncertainty(reading, unit)
                if std_dev > 0:
                    value_to_return = ufloat(reading, std_dev)
                    self._logger.info(f"Measured {measurement_type}: {value_to_return} {unit}")
            else:
                self._logger.info(f"Warning: No matching accuracy spec found for {measurement_type}. Returning float.")
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
        if not isinstance(value_to_return, (float, UFloat)):
            value_to_return = float(value_to_return)

        return MeasurementResult(
            values=value_to_return,
            instrument=self.config.model,
            units=unit,
            measurement_type=measurement_type.capitalize()
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
    def configure_transient_mode(self, mode: Literal['CONTinuous', 'PULSe', 'TOGGle', 'LIST'], channel: int = 1) -> None:
        """Sets the operating mode of the transient generator."""
        self._send_command(f"TRANsient:MODE {mode.upper()}, (@{channel})")

    def set_transient_level(self, value: float, channel: int = 1) -> None:
        """Sets the secondary (transient) level for the current operating mode."""
        if self.current_mode is None:
            raise InstrumentParameterError("Mode must be set before setting transient level.")
        command_map = {"CC": "CURRent", "CV": "VOLTage", "CP": "POWer", "CR": "RESistance"}
        scpi_param = command_map.get(self.current_mode)
        self._send_command(f"{scpi_param}:TLEVel {value}, (@{channel})")

    def start_transient(self, continuous: bool = False, channel: int = 1) -> None:
        """Initiates the transient trigger system."""
        self._send_command(f"INITiate:CONTinuous:TRANsient {'ON' if continuous else 'OFF'}, (@{channel})")
        if not continuous:
            self._send_command(f"INITiate:TRANsient (@{channel})")

    def stop_transient(self, channel: int = 1) -> None:
        """Aborts any pending or in-progress transient operations."""
        self._send_command(f"ABORt:TRANsient (@{channel})")

    # --- Battery Test Methods ---
    def enable_battery_test(self, state: bool, channel: int = 1) -> None:
        """Enables or disables the battery test operation."""
        self._send_command(f"BATTery:ENABle {'ON' if state else 'OFF'}, (@{channel})")

    def set_battery_cutoff_voltage(self, voltage: float, state: bool = True, channel: int = 1) -> None:
        """Configures the voltage cutoff condition for the battery test."""
        self._send_command(f"BATTery:CUTOff:VOLTage:STATe {'ON' if state else 'OFF'}, (@{channel})")
        if state:
            self._send_command(f"BATTery:CUTOff:VOLTage {voltage}, (@{channel})")

    def set_battery_cutoff_capacity(self, capacity: float, state: bool = True, channel: int = 1) -> None:
        """Configures the capacity (Ah) cutoff condition for the battery test."""
        self._send_command(f"BATTery:CUTOff:CAPacity:STATe {'ON' if state else 'OFF'}, (@{channel})")
        if state:
            self._send_command(f"BATTery:CUTOff:CAPacity {capacity}, (@{channel})")

    def set_battery_cutoff_timer(self, time_s: float, state: bool = True, channel: int = 1) -> None:
        """Configures the timer (seconds) cutoff condition for the battery test."""
        self._send_command(f"BATTery:CUTOff:TIMer:STATe {'ON' if state else 'OFF'}, (@{channel})")
        if state:
            self._send_command(f"BATTery:CUTOff:TIMer {time_s}, (@{channel})")

    def get_battery_test_measurement(self, metric: Literal["capacity", "power", "time"], channel: int = 1) -> float:
        """Queries a measurement from the ongoing battery test."""
        scpi_map = {"capacity": "CAPacity", "power": "POWer", "time": "TIMe"}
        response = self._query(f"BATTery:MEASure:{scpi_map[metric]}? (@{channel})")
        return float(response)

    # --- Data Acquisition Methods ---
    def fetch_scope_data(self, measurement: Literal["current", "voltage", "power"], channel: int = 1) -> np.ndarray:
        """Fetches the captured waveform (scope) data as a NumPy array."""
        scpi_map = {"current": "CURRent", "voltage": "VOLTage", "power": "POWer"}
        raw_data = self._query_raw(f"FETCh:ARRay:{scpi_map[measurement]}? (@{channel})")
        # Assumes the backend handles binary block data parsing; if not, call self._read_to_np
        return np.frombuffer(raw_data, dtype=np.float32) # Assuming float data

    def fetch_datalogger_data(self, num_points: int, channel: int = 1) -> List[float]:
        """Fetches the specified number of logged data points."""
        response = self._query(f"FETCh:SCALar:DLOG? {num_points}, (@{channel})")
        return [float(x) for x in response.split(',')]

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
