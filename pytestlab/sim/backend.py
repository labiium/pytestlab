from __future__ import annotations
import logging # For logging within the sim backend
import re # For potential regex dispatch
from typing import Any, Optional # For type hints
import time

# Import the _Backend protocol
from ..instruments.instrument import _Backend # Adjusted import path

# Attempt to import the Pydantic InstrumentConfig from its new location
# This assumes Section D (Pydantic models) has been completed.
try:
    from ..config.instrument_config import InstrumentConfig
except ImportError:
    # Fallback or placeholder if InstrumentConfig is not yet Pydantic or path is different
    # This is a safeguard; ideally, the path from Section D is correct.
    # For the purpose of this task, we'll assume a simple dict-like config if Pydantic one fails.
    InstrumentConfig = dict 
    logging.warning("Could not import Pydantic InstrumentConfig; SimBackend will use a generic config type.")

# Get a logger for the simulation backend
# This assumes Section C (Logging Façade) has been completed.
try:
    from .._log import get_logger
    sim_logger = get_logger("sim.backend")
except ImportError:
    sim_logger = logging.getLogger("sim.backend_fallback")
    sim_logger.warning("Could not import pytestlab's get_logger; SimBackend using fallback logger.")


class SimBackend:  # TODO: Consider adding ": _Backend" for static type checking if desired
    def __init__(self, profile: InstrumentConfig, device_model: str = "GenericSimDevice"):
        self.profile: InstrumentConfig = profile  # This should be the Pydantic model instance
        self.state: dict[str, Any] = {}  # To store simulated instrument state
        self.device_model = device_model
        self.error_queue: list[tuple[int, str]] = []
        self.error_config: dict[str, Any] = {}
        self.busy: bool = False
        self.busy_until: float = 0.0
        self.timeout_duration: float = 0.0
        sim_logger.info(f"SimBackend initialized for profile: {self.device_model}")
        # Initialize some basic state based on profile if possible
        # e.g., self.state['output_enabled'] = False
        # This part will be highly dependent on what's in InstrumentConfig
        # and what needs to be simulated.

    def connect(self) -> None:
        """Connects to the simulated instrument."""
        sim_logger.info(f"SimBackend for {self.device_model} connected (simulated).")
        # No actual connection needed for simulation, but method is required by protocol

    def disconnect(self) -> None:
        """Disconnects from the simulated instrument."""
        sim_logger.info(f"SimBackend for {self.device_model} disconnected (simulated).")
        # May call self.close() if they are intended to be the same
        self.close()

    def _record(self, cmd: str) -> None:
        """Helper to log commands sent to the simulated instrument."""
        sim_logger.debug(f"SimBackend received WRITE: '{cmd}' for {self.device_model}")
        # Potentially update self.state based on command
        # Example: if cmd.startswith(":OUTP:STAT "): self.state['output_enabled'] = "ON" in cmd

    def _simulate(self, cmd: str) -> str:
        """
        Simulates a query response.
        This needs to be implemented with command parsing (e.g., regex dispatch)
        to return meaningful simulated data based on self.profile and self.state.
        """
        sim_logger.debug(f"SimBackend received QUERY: '{cmd}' for {self.device_model}")
        
        # Minimal command set example (to be expanded based on actual instrument commands)
        # This is a placeholder for a more sophisticated dispatch mechanism.
        if cmd.upper() == "*IDN?":
            # Try to get model from profile, fallback to a generic sim response
            model_name = getattr(self.profile, 'model', self.device_model)
            return f"SimulatedDevice,Model,{model_name},Firmware,1.0"
        elif cmd.upper().startswith(":VOLT?"): # Example for a multimeter/PSU
            return str(self.state.get("voltage", 0.0)) 
        elif cmd.upper().startswith(":CURR?"): # Example
            return str(self.state.get("current", 0.0))
        elif cmd.upper().startswith(":OUTP:STAT?"): # Example
            return "1" if self.state.get("output_enabled", False) else "0"
        elif cmd.upper() in (":SYST:ERR?", ":SYSTEM:ERROR?", "SYST:ERR?", "SYSTEM:ERROR?"):
            if self.error_queue:
                code, msg = self.error_queue.pop(0)
                return f'{code},"{msg}"'
            return '0,"No error"'

        # Fallback for unknown commands
        sim_logger.warning(f"SimBackend for {self.device_model} received unknown QUERY: '{cmd}'")
        return "SIM_ERROR:UnknownQuery"

    def _push_error(self, code: int, message: str):
        """Pushes an error to the queue."""
        if len(self.error_queue) < 10:  # Limit queue size
            self.error_queue.append((code, message))
            sim_logger.warning(f"SimBackend for {self.device_model} pushed error: {code}, '{message}'")

    def write(self, cmd: str) -> None:
        if self.timeout_duration > 0:
            time.sleep(self.timeout_duration)
            self.timeout_duration = 0.0  # one-shot timeout

        if self.busy and time.time() < self.busy_until:
            self._push_error(-109, "Device busy")
            return
        self.busy = False

        self._record(cmd)
        # Actual state changes based on write commands would go here or in _record
        if cmd.upper().startswith(":VOLT "):
            try:
                val = float(cmd.split(" ")[1])
                max_voltage = self.error_config.get("max_voltage")
                if max_voltage is not None and val > max_voltage:
                    self._push_error(-222, "Data out of range")
                else:
                    self.state["voltage"] = val
                    sim_logger.info(f"SimBackend for {self.device_model} set voltage to {val}")
            except (IndexError, ValueError) as e:
                sim_logger.error(f"SimBackend error parsing VOLT command '{cmd}': {e}")
                self._push_error(-100, "Command error")
        elif cmd.upper().startswith(":OUTP:STAT "):
            status = cmd.split(" ")[1].upper()
            self.state["output_enabled"] = (status == "ON" or status == "1")
            sim_logger.info(f"SimBackend for {self.device_model} set output state to {self.state['output_enabled']}")
        elif cmd.upper().startswith(":SIM:BUSY "):
            try:
                duration = float(cmd.split(" ")[1])
                self.busy = True
                self.busy_until = time.time() + duration
                sim_logger.info(f"SimBackend for {self.device_model} will be busy for {duration}s")
            except (IndexError, ValueError) as e:
                sim_logger.error(f"SimBackend error parsing :SIM:BUSY command '{cmd}': {e}")
                self._push_error(-100, "Command error")
        elif cmd.upper().startswith(":SIM:TIMEOUT "):
            try:
                duration = float(cmd.split(" ")[1])
                self.timeout_duration = duration
                sim_logger.info(f"SimBackend for {self.device_model} will simulate a timeout of {duration}s")
            except (IndexError, ValueError) as e:
                sim_logger.error(f"SimBackend error parsing :SIM:TIMEOUT command '{cmd}': {e}")
                self._push_error(-100, "Command error")

    def query(self, cmd: str, delay: Optional[float] = None) -> str:
        if self.timeout_duration > 0:
            time.sleep(self.timeout_duration)
            self.timeout_duration = 0.0

        if self.busy and time.time() < self.busy_until:
            self._push_error(-109, "Device busy")
            return "SIM_ERROR:DeviceBusy"
        self.busy = False

        if delay is not None:
            sim_logger.debug(f"SimBackend received delay of {delay}s for QUERY '{cmd}', but it's ignored in simulation.")
        response = self._simulate(cmd)
        sim_logger.debug(f"SimBackend for {self.device_model} responding to '{cmd}' with: '{response}'")
        return response

    def query_raw(self, cmd: str, delay: Optional[float] = None) -> bytes:
        if self.timeout_duration > 0:
            time.sleep(self.timeout_duration)
            self.timeout_duration = 0.0

        if self.busy and time.time() < self.busy_until:
            self._push_error(-109, "Device busy")
            return b"SIM_ERROR:DeviceBusy"
        self.busy = False

        if delay is not None:
            sim_logger.debug(f"SimBackend received delay of {delay}s for RAW QUERY '{cmd}', but it's ignored in simulation.")
        response_str = self._simulate(cmd)
        sim_logger.debug(f"SimBackend for {self.device_model} responding to RAW QUERY '{cmd}' with: '{response_str}'")
        return response_str.encode('utf-8')

    def close(self) -> None:
        sim_logger.info(f"SimBackend for {self.device_model} closed.")
        # Any cleanup for the sim backend