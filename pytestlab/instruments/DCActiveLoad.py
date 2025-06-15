from __future__ import annotations

"""
DCActiveLoad.py

Instrument driver for a DC Active Load. Provides methods to set the operating mode,
program the load value, enable/disable the output, and query measurements (current, voltage, power)
from the Keysight EL30000 Series bench DC electronic loads.
"""

import numpy as np
import warnings
from typing import Optional, Union, Dict, Type, Any # Added Type, Any
from .instrument import Instrument
from ..errors import InstrumentConfigurationError, InstrumentParameterError
from ..config import DCActiveLoadConfig
from ..experiments import MeasurementResult


class DCActiveLoad(Instrument):
    """Represents a DC Electronic Load instrument.

    This class provides a driver for controlling a DC Active Load, enabling
    programmatic control over its operating modes and settings. It is designed
    to work with SCPI-compliant instruments, with commands based on the
    Keysight EL30000 Series.

    The driver supports the following primary operations:
    - Setting the operating mode (Constant Current, Voltage, Power, Resistance).
    - Programming the load value for the current mode.
    - Enabling or disabling the load's input.
    - Measuring voltage, current, and power.

    Attributes:
        config: The configuration object for the instrument.
        current_mode: The currently active operating mode (e.g., "CC", "CV").
    """
    def __init__(self, config: Optional[DCActiveLoadConfig] = None, debug_mode: bool = False, simulate: bool = False) -> None:
        if not isinstance(config, DCActiveLoadConfig):
            raise InstrumentConfigurationError(
                "DCActiveLoad", "DCActiveLoadConfig is required for initialization."
            )
        super().__init__(config=config, debug_mode=debug_mode, simulate=simulate)
        self.current_mode: Optional[str] = None
        self.config: DCActiveLoadConfig # Ensure self.config is correctly typed

    @classmethod
    def from_config(cls: Type[DCActiveLoad], config: Union[Dict[str, Any], DCActiveLoadConfig], debug_mode: bool = False, simulate: bool = False) -> DCActiveLoad:
        """Creates a DCActiveLoad instance from a configuration.

        This factory method allows for the creation of a DCActiveLoad driver from
        either a raw dictionary or a `DCActiveLoadConfig` object. It simplifies
        the instantiation process by handling the configuration object creation
        internally.

        Args:
            config: A dictionary or a `DCActiveLoadConfig` object containing the
                    instrument's settings.
            debug_mode: If True, enables detailed logging for debugging purposes.
            simulate: If True, initializes the instrument in simulation mode.

        Returns:
            An initialized DCActiveLoad object.

        Raises:
            InstrumentConfigurationError: If the provided config is not a dict or
                                          a `DCActiveLoadConfig` instance.
        """
        conf_obj: DCActiveLoadConfig
        if isinstance(config, dict):
            conf_obj = DCActiveLoadConfig(**config)
        elif isinstance(config, DCActiveLoadConfig):
            conf_obj = config
        else:
            raise InstrumentConfigurationError(
                "DCActiveLoad", "Configuration must be a dict or DCActiveLoadConfig instance."
            )
        return cls(config=conf_obj, debug_mode=debug_mode, simulate=simulate)

    async def set_mode(self, mode: str) -> None:
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
            "CV": "VOLT",
            "CP": "POW",
            "CR": "RES"
        }
        # Validate the requested mode against the supported modes
        if mode_upper not in mode_map:
            raise InstrumentParameterError(
                parameter="mode",
                value=mode,
                valid_range=list(mode_map.keys()),
                message=f"Unsupported mode '{mode}'.",
            )

        # Send the corresponding SCPI command to the instrument
        await self._send_command(f"FUNC {mode_map[mode_upper]}")
        self.current_mode = mode_upper

        # Log a human-readable description of the new mode
        full_mode_description = mode_upper
        if hasattr(self.config, 'supported_modes') and isinstance(self.config.supported_modes, dict):
            full_mode_description = self.config.supported_modes.get(mode_upper, mode_upper)

        self._log(f"Operating mode set to {full_mode_description}.")

    async def set_load(self, value: float) -> None:
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
        # Ensure that an operating mode has been selected before setting a value
        if self.current_mode is None:
            raise InstrumentParameterError(
                message="Load mode has not been set. Please call set_mode() before setting the load."
            )

        # Map the operating mode to the corresponding SCPI command keyword
        command_map: Dict[str, str] = {
            "CC": "CURR",
            "CV": "VOLT",
            "CP": "POW",
            "CR": "RES"
        }
        scpi_param = command_map.get(self.current_mode)

        # Send the command to the instrument
        if scpi_param:
            # Future enhancement: Add validation against config ranges if available
            # e.g., if self.current_mode == "CC" and hasattr(self.config, 'current_set_range'):
            #   self.config.current_set_range.in_range(value)
            await self._send_command(f"{scpi_param} {value}")
            self._log(f"Load value set to {value} in mode {self.current_mode}.")
        else:
            # This case should ideally not be reached if `current_mode` is managed correctly
            raise InstrumentParameterError(
                message=f"Internal error: Unknown current_mode '{self.current_mode}' for set_load."
            )


    async def output(self, state: bool) -> None:
        """
        Enable or disable the active load output.

        Args:
            state (bool): True to enable (ON), False to disable (OFF).
        """
        await self._send_command(f"OUTP {'ON' if state else 'OFF'}")
        self._log(f"Output turned {'ON' if state else 'OFF'}.")

    async def measure_current(self) -> MeasurementResult:
        """
        Query the instrument for the sinking current.

        Returns:
            MeasurementResult: Measured current in amperes.
        """
        response = await self._query("MEAS:CURR?")
        value = np.float64(response)
        self._log(f"Measured current: {value} A")
        return MeasurementResult(
            values=value,
            instrument=self.config.model,
            units="A",
            measurement_type="Current"
        )

    async def measure_voltage(self) -> MeasurementResult:
        """
        Query the instrument for the voltage across the load.

        Returns:
            MeasurementResult: Measured voltage in volts.
        """
        response = await self._query("MEAS:VOLT?")
        value = np.float64(response)
        self._log(f"Measured voltage: {value} V")
        return MeasurementResult(
            values=value,
            instrument=self.config.model,
            units="V",
            measurement_type="Voltage"
        )

    async def measure_power(self) -> MeasurementResult:
        """
        Query the instrument for the power being dissipated.

        Returns:
            MeasurementResult: Measured power in watts.
        """
        response = await self._query("MEAS:POW?")
        value = np.float64(response)
        self._log(f"Measured power: {value} W")
        return MeasurementResult(
            values=value,
            instrument=self.config.model,
            units="W",
            measurement_type="Power"
        )

    def set_mode_sync(self, mode: str) -> None:
        """
        Set the operating mode of the load.
        """
        warnings.warn(
            "The 'set_mode_sync' method is deprecated and will be removed in a future version. "
            "Please use the asynchronous 'set_mode' method instead.",
            DeprecationWarning,
            stacklevel=2
        )
        self.set_mode(mode)

    def set_load_sync(self, value: float) -> None:
        """
        Program the load value (in A, V, W, or Ω) according to the selected operating mode.
        """
        warnings.warn(
            "The 'set_load_sync' method is deprecated and will be removed in a future version. "
            "Please use the asynchronous 'set_load' method instead.",
            DeprecationWarning,
            stacklevel=2
        )
        self.set_load(value)

    def output_sync(self, state: bool) -> None:
        """
        Enable or disable the active load output.
        """
        warnings.warn(
            "The 'output_sync' method is deprecated and will be removed in a future version. "
            "Please use the asynchronous 'output' method instead.",
            DeprecationWarning,
            stacklevel=2
        )
        self.output(state)

    def measure_current_sync(self) -> MeasurementResult:
        """
        Query the instrument for the sinking current.
        """
        warnings.warn(
            "The 'measure_current_sync' method is deprecated and will be removed in a future version. "
            "Please use the asynchronous 'measure_current' method instead.",
            DeprecationWarning,
            stacklevel=2
        )
        return self.measure_current()

    def measure_voltage_sync(self) -> MeasurementResult:
        """
        Query the instrument for the voltage across the load.
        """
        warnings.warn(
            "The 'measure_voltage_sync' method is deprecated and will be removed in a future version. "
            "Please use the asynchronous 'measure_voltage' method instead.",
            DeprecationWarning,
            stacklevel=2
        )
        return self.measure_voltage()

    def measure_power_sync(self) -> MeasurementResult:
        """
        Query the instrument for the power being dissipated.
        """
        warnings.warn(
            "The 'measure_power_sync' method is deprecated and will be removed in a future version. "
            "Please use the asynchronous 'measure_power' method instead.",
            DeprecationWarning,
            stacklevel=2
        )
        return self.measure_power()
