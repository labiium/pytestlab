"""
DCActiveLoad.py

Instrument driver for a DC Active Load. Provides methods to set the operating mode,
program the load value, enable/disable the output, and query measurements (current, voltage, power)
from the Keysight EL30000 Series bench DC electronic loads.
"""

import numpy as np
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
    def __init__(self, config=None, debug_mode=False):
        if not isinstance(config, DCActiveLoadConfig):
            raise InstrumentConfigurationError("DCActiveLoadConfig required to initialize DCActiveLoad")
        super().__init__(config=config, debug_mode=debug_mode)
        self.current_mode = None

    @classmethod
    def from_config(cls, config, debug_mode=False):
        """
        Create a DCActiveLoad instance from a configuration dictionary or DCActiveLoadConfig.
        
        Args:
            config (dict or DCActiveLoadConfig): Configuration data.
            debug_mode (bool): If True, enable debug logging.
            
        Returns:
            DCActiveLoad: An instance of the DC active load driver.
        """
        if isinstance(config, dict):
            config = DCActiveLoadConfig(**config)
        return cls(config=config, debug_mode=debug_mode)

    def set_mode(self, mode: str):
        """
        Set the operating mode of the load.

        Supported modes (abbreviations):
            "CC": Constant Current
            "CV": Constant Voltage
            "CP": Constant Power
            "CR": Constant Resistance

        Args:
            mode (str): One of "CC", "CV", "CP", "CR".

        Raises:
            ValueError: If mode is not supported.
        """
        mode_map = {
            "CC": "CURR",
            "CV": "VOLT",
            "CP": "POW",
            "CR": "RES"
        }
        if mode not in mode_map:
            raise ValueError("Unsupported mode. Use 'CC', 'CV', 'CP', or 'CR'.")
        # Send the SCPI command to select the function mode.
        self._send_command(f"FUNC {mode_map[mode]}")
        self.current_mode = mode
        # Log using the full description from the config supported_modes mapping.
        full_mode = self.config.supported_modes.get(mode, mode)
        self._log(f"Operating mode set to {full_mode}.")

    def set_load(self, value: float):
        """
        Program the load value (in A, V, W, or Ω) according to the selected operating mode.

        Args:
            value (float): The value to program.

        Raises:
            InstrumentParameterError: If the operating mode has not been set.
        """
        if self.current_mode is None:
            raise InstrumentParameterError("Load mode not set. Call set_mode() first.")
        if self.current_mode == "CC":
            self._send_command(f"CURR {value}")
        elif self.current_mode == "CV":
            self._send_command(f"VOLT {value}")
        elif self.current_mode == "CP":
            self._send_command(f"POW {value}")
        elif self.current_mode == "CR":
            self._send_command(f"RES {value}")
        self._log(f"Load value set to {value} in mode {self.current_mode}.")

    def output(self, state: bool):
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
