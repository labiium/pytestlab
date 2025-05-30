from __future__ import annotations

"""
DCActiveLoad.py

Instrument driver for a DC Active Load. Provides methods to set the operating mode,
program the load value, enable/disable the output, and query measurements (current, voltage, power)
from the Keysight EL30000 Series bench DC electronic loads.
"""

import numpy as np
from typing import Optional, Union, Dict, Type, Any # Added Type, Any
from .instrument import Instrument
from ..errors import InstrumentConfigurationError, InstrumentParameterError
from ..config import DCActiveLoadConfig
from ..experiments import MeasurementResult


class DCActiveLoad(Instrument):
    """
    Provides an interface for controlling a DC active load via SCPI commands.

    Supported functions include:
      - Setting the operating mode (Constant Current, Constant Voltage, Constant Power, Constant Resistance)
      - Programming the load value (current, voltage, power or resistance depending on the mode)
      - Enabling/disabling the output
      - Querying measurements (voltage, current, power)
    
    The SCPI commands are based on the Keysight EL30000 Series.
    """
    def __init__(self, config: Optional[DCActiveLoadConfig] = None, debug_mode: bool = False) -> None:
        if not isinstance(config, DCActiveLoadConfig):
            raise InstrumentConfigurationError("DCActiveLoadConfig required to initialize DCActiveLoad")
        super().__init__(config=config, debug_mode=debug_mode)
        self.current_mode: Optional[str] = None
        self.config: DCActiveLoadConfig # Ensure self.config is correctly typed

    @classmethod
    def from_config(cls: Type[DCActiveLoad], config: Union[Dict[str, Any], DCActiveLoadConfig], debug_mode: bool = False) -> DCActiveLoad:
        """
        Create a DCActiveLoad instance from a configuration dictionary or DCActiveLoadConfig.
        
        Args:
            config (Union[Dict[str, Any], DCActiveLoadConfig]): Configuration data.
            debug_mode (bool): If True, enable debug logging.
            
        Returns:
            DCActiveLoad: An instance of the DC active load driver.
        """
        conf_obj: DCActiveLoadConfig
        if isinstance(config, dict):
            conf_obj = DCActiveLoadConfig(**config)
        elif isinstance(config, DCActiveLoadConfig):
            conf_obj = config
        else:
            raise InstrumentConfigurationError("config must be a dict or DCActiveLoadConfig instance.")
        return cls(config=conf_obj, debug_mode=debug_mode)

    def set_mode(self, mode: str) -> None:
        """
        Set the operating mode of the load.

        Supported modes (abbreviations):
            "CC": Constant Current
            "CV": Constant Voltage
            "CP": Constant Power
            "CR": Constant Resistance

        Args:
            mode (str): One of "CC", "CV", "CP", "CR". Case-insensitive.

        Raises:
            ValueError: If mode is not supported.
        """
        mode_upper = mode.upper()
        mode_map: Dict[str, str] = {
            "CC": "CURR",
            "CV": "VOLT",
            "CP": "POW",
            "CR": "RES"
        }
        if mode_upper not in mode_map:
            raise ValueError(f"Unsupported mode '{mode}'. Use 'CC', 'CV', 'CP', or 'CR'.")
        
        self._send_command(f"FUNC {mode_map[mode_upper]}")
        self.current_mode = mode_upper 
        
        full_mode_description = mode_upper 
        if hasattr(self.config, 'supported_modes') and isinstance(self.config.supported_modes, dict):
            full_mode_description = self.config.supported_modes.get(mode_upper, mode_upper)
        
        self._log(f"Operating mode set to {full_mode_description}.")

    def set_load(self, value: float) -> None:
        """
        Program the load value (in A, V, W, or Ω) according to the selected operating mode.

        Args:
            value (float): The value to program.

        Raises:
            InstrumentParameterError: If the operating mode has not been set or is unknown.
        """
        if self.current_mode is None:
            raise InstrumentParameterError("Load mode not set. Call set_mode() first.")
        
        command_map: Dict[str, str] = {
            "CC": "CURR",
            "CV": "VOLT",
            "CP": "POW",
            "CR": "RES"
        }
        scpi_param = command_map.get(self.current_mode)
        if scpi_param:
            # Add validation against config ranges if available
            # e.g., if self.current_mode == "CC" and hasattr(self.config, 'current_set_range'):
            #   self.config.current_set_range.in_range(value)
            self._send_command(f"{scpi_param} {value}")
            self._log(f"Load value set to {value} in mode {self.current_mode}.")
        else:
            raise InstrumentParameterError(f"Internal error: Unknown current_mode '{self.current_mode}' for set_load.")


    def output(self, state: bool) -> None:
        """
        Enable or disable the active load output.

        Args:
            state (bool): True to enable (ON), False to disable (OFF).
        """
        self._send_command(f"OUTP {'ON' if state else 'OFF'}")
        self._log(f"Output turned {'ON' if state else 'OFF'}.")

    def measure_current(self) -> MeasurementResult:
        """
        Query the instrument for the sinking current.

        Returns:
            MeasurementResult: Measured current in amperes.
        """
        response = self._query("MEAS:CURR?")
        value = np.float64(response)
        self._log(f"Measured current: {value} A")
        return MeasurementResult(
            values=value,
            instrument=self.config.model,
            units="A",
            measurement_type="Current"
        )

    def measure_voltage(self) -> MeasurementResult:
        """
        Query the instrument for the voltage across the load.

        Returns:
            MeasurementResult: Measured voltage in volts.
        """
        response = self._query("MEAS:VOLT?")
        value = np.float64(response)
        self._log(f"Measured voltage: {value} V")
        return MeasurementResult(
            values=value,
            instrument=self.config.model,
            units="V",
            measurement_type="Voltage"
        )

    def measure_power(self) -> MeasurementResult:
        """
        Query the instrument for the power being dissipated.

        Returns:
            MeasurementResult: Measured power in watts.
        """
        response = self._query("MEAS:POW?")
        value = np.float64(response)
        self._log(f"Measured power: {value} W")
        return MeasurementResult(
            values=value,
            instrument=self.config.model,
            units="W",
            measurement_type="Power"
        )
