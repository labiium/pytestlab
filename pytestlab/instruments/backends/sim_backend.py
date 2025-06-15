from __future__ import annotations
import logging  # For logging within the sim backend
import re  # For potential regex dispatch
import warnings
from typing import Any, Optional, TYPE_CHECKING

# Import the AsyncInstrumentIO protocol
if TYPE_CHECKING:
    from ..instrument import AsyncInstrumentIO, InstrumentIO # For type hinting
    from ...config import InstrumentConfig # Assuming InstrumentConfig is the base Pydantic model
else: # Runtime fallback for InstrumentConfig if not strictly typed or for older versions
    InstrumentConfig = dict


# Attempt to import the Pydantic InstrumentConfig from its new location
try:
    from ...config import InstrumentConfig as PydanticInstrumentConfig
    # Ensure InstrumentConfig is the Pydantic one if available
    if not TYPE_CHECKING: # Runtime check
        InstrumentConfig = PydanticInstrumentConfig
except ImportError:
    if TYPE_CHECKING: # If in type checking mode and import fails, it's an issue
        pass # Let type checker handle it
    else: # Runtime fallback
        logging.warning("Could not import Pydantic InstrumentConfig for SimBackend; using generic dict.")
        InstrumentConfig = dict


# Get a logger for the simulation backend
try:
    from ..._log import get_logger
    sim_logger = get_logger("sim.backend")
except ImportError:
    sim_logger = logging.getLogger("sim.backend_fallback")
    sim_logger.warning("Could not import pytestlab's get_logger; SimBackend using fallback logger.")


class SimBackend:  # Implements AsyncInstrumentIO (and InstrumentIO for completeness if needed)
    """
    A simulated backend for instruments, supporting asynchronous operations.
    This class implements the AsyncInstrumentIO protocol (and can implement InstrumentIO).
    """
    def __init__(self, profile: InstrumentConfig, device_model: str = "GenericSimDevice", timeout_ms: Optional[int] = 5000):
        self.profile: InstrumentConfig = profile
        self.state: dict[str, Any] = {} # To store simulated instrument state
        self.device_model = device_model
        self._timeout_ms = timeout_ms if timeout_ms is not None else 5000
        self._sim_responses: dict[str, str] = {}
        sim_logger.info(f"Async SimBackend initialized for profile: {self.device_model}")
        warnings.warn(f"Instrument is running in simulation mode.", UserWarning)
        # Initialize some basic state
        self.state['output_enabled'] = False
        self.state['voltage'] = 0.0
        self.state['current'] = 0.0
        self.state['errors'] = []  # Simulate an error queue
        self.error_config: dict[str, Any] = {}

    def configure_error_simulation(self, config: dict[str, Any]) -> None:
        """Configures the error simulation behavior."""
        self.error_config.update(config)
        sim_logger.info(f"SimBackend for {self.device_model} error simulation configured with: {config}")

    def set_sim_response(self, cmd: str, value: str) -> None:
        """
        Sets a custom simulation response for a specific command.

        Args:
            cmd: The command to which the simulation should respond.
            value: The value to be returned when the command is received.
        """
        self._sim_responses[cmd.upper()] = value
        sim_logger.info(f"SimBackend for {self.device_model} registered custom response for '{cmd}': '{value}'")

    async def connect(self) -> None:
        """Connects to the simulated instrument (async)."""
        sim_logger.info(f"Async SimBackend for {self.device_model} connected (simulated).")
        # No actual connection needed for simulation

    async def disconnect(self) -> None:
        """Disconnects from the simulated instrument (async)."""
        sim_logger.info(f"Async SimBackend for {self.device_model} disconnected (simulated).")
        await self.close()

    def _record_sync(self, cmd: str) -> None:
        """Synchronous helper to log commands and update state."""
        sim_logger.debug(f"SimBackend (sync part of async op) received WRITE: '{cmd}' for {self.device_model}")
        cmd_upper = cmd.upper()
        if cmd_upper in self._sim_responses:
            # If a custom response is set for a write command, it might just be logged
            # or could trigger a state change, but it won't return a value here.
            # For now, we just log that we acknowledged it.
            sim_logger.info(f"SimBackend handled '{cmd}' with a custom response rule (action: log).")
            return
        if cmd.upper().startswith(":VOLT "):
            try:
                val = float(cmd.split(" ")[1])
                max_voltage = self.error_config.get("max_voltage")
                if max_voltage is not None and val > max_voltage:
                    self.state['errors'].append(("-222", "Data out of range"))
                    sim_logger.warning(f"SimBackend: Overvoltage triggered for {self.device_model}. Voltage {val} > {max_voltage}")
                else:
                    self.state["voltage"] = val
                    sim_logger.info(f"SimBackend for {self.device_model} set voltage to {val}")
            except (IndexError, ValueError) as e:
                sim_logger.error(f"SimBackend error parsing VOLT command '{cmd}': {e}")
                self.state['errors'].append(("-102", "Syntax error in VOLT command"))
        elif cmd.upper().startswith(":OUTP:STAT "):
            status_str = cmd.split(" ")[-1].upper()
            self.state["output_enabled"] = (status_str == "ON" or status_str == "1")
            sim_logger.info(f"SimBackend for {self.device_model} set output state to {self.state['output_enabled']}")
        elif cmd.upper() == "*RST":
            self.state['output_enabled'] = False
            self.state['voltage'] = 0.0
            self.state['current'] = 0.0
            self.state['errors'] = []
            sim_logger.info(f"SimBackend for {self.device_model} has been reset (*RST).")
        elif cmd.upper() == "*CLS":
            self.state['errors'] = []
            sim_logger.info(f"SimBackend for {self.device_model} error queue cleared (*CLS).")
        elif cmd.upper().startswith(":SIM:BUSY"):
            try:
                duration = float(cmd.split(" ")[1])
                self.write(f":SIM:BUSY {duration}")
            except (IndexError, ValueError):
                self.state['errors'].append(("-102", "Syntax error in :SIM:BUSY"))
        elif cmd.upper().startswith(":SIM:TIMEOUT"):
            try:
                duration = float(cmd.split(" ")[1])
                self.write(f":SIM:TIMEOUT {duration}")
            except (IndexError, ValueError):
                self.state['errors'].append(("-102", "Syntax error in :SIM:TIMEOUT"))


    def _simulate_sync(self, cmd: str) -> str:
        """
        Synchronous part of simulating a query response.
        """
        sim_logger.debug(f"SimBackend (sync part of async op) received QUERY: '{cmd}' for {self.device_model}")
        cmd_upper = cmd.upper()
        if cmd_upper in self._sim_responses:
            return self._sim_responses[cmd_upper]
        if cmd_upper == "*IDN?":
            model_name = getattr(self.profile, 'model', self.device_model)
            return f"SimulatedDevice,Model,{model_name},Firmware,SIM1.0"
        elif cmd_upper == "SYST:VERS?":
            return "1999.0" # SCPI version
        elif cmd_upper == "SYST:ERR?" or cmd_upper == "SYSTEM:ERROR?" or cmd_upper == ":SYSTEM:ERROR?" or cmd_upper == ":SYST:ERR?":
            if not self.state['errors']:
                return "+0,\"No error\""
            else:
                err_code, err_msg = self.state['errors'].pop(0) # FIFO queue
                return f"{err_code},\"{err_msg}\""
        elif cmd_upper.startswith(":VOLT?"):
            return str(self.state.get("voltage", 0.0))
        elif cmd_upper.startswith(":CURR?"):
            return str(self.state.get("current", 0.0))
        elif cmd_upper.startswith(":OUTP:STAT?"):
            return "1" if self.state.get("output_enabled", False) else "0"
        elif cmd_upper == "*OPC?":
            return "1" # Assume operations complete immediately
        elif cmd_upper == "*TST?":
            return "0" # Simulate self-test pass

        sim_logger.warning(f"SimBackend for {self.device_model} received unknown QUERY: '{cmd}'")
        self.state['errors'].append(("-113", "Undefined header"))
        return "SIM_ERROR:UnknownQuery"

    async def write(self, cmd: str) -> None:
        """Writes a command to the simulated instrument (async)."""
        self._record_sync(cmd)
        # In a true async simulation, one might add `await anyio.sleep(0)` here
        # to yield control, but for simple state changes, it's not strictly necessary.

    async def query(self, cmd: str, delay: Optional[float] = None) -> str:
        """Sends a query and returns string response (async)."""
        if delay is not None:
            sim_logger.debug(f"SimBackend (async) received delay of {delay}s for QUERY '{cmd}', but it's ignored in simulation.")
            # await anyio.sleep(delay) # If we wanted to simulate network delay
        response = self._simulate_sync(cmd)
        sim_logger.debug(f"SimBackend (async) for {self.device_model} responding to '{cmd}' with: '{response}'")
        return response

    async def query_raw(self, cmd: str, delay: Optional[float] = None) -> bytes:
        """Sends a query and returns raw bytes response (async)."""
        if delay is not None:
            sim_logger.debug(f"SimBackend (async) received delay of {delay}s for RAW QUERY '{cmd}', but it's ignored in simulation.")
        response_str = self._simulate_sync(cmd) # Raw query often implies specific formatting, but here we reuse
        sim_logger.debug(f"SimBackend (async) for {self.device_model} responding to RAW QUERY '{cmd}' with: '{response_str}'")
        return response_str.encode('utf-8')

    async def close(self) -> None:
        """Closes the connection to the simulated instrument (async)."""
        sim_logger.info(f"Async SimBackend for {self.device_model} closed (simulated).")
        # Any cleanup for the sim backend

    async def set_timeout(self, timeout_ms: int) -> None:
        """Sets the communication timeout (simulated, async)."""
        if timeout_ms <= 0:
            # In a real backend, this might raise ValueError.
            # For sim, we can just log it or store if sim logic depends on it.
            sim_logger.warning(f"SimBackend: set_timeout called with non-positive value: {timeout_ms} ms. Storing as is.")
        self._timeout_ms = timeout_ms
        sim_logger.debug(f"Async SimBackend for {self.device_model} timeout set to {timeout_ms} ms (simulated).")

    async def get_timeout(self) -> int:
        """Gets the communication timeout (simulated, async)."""
        sim_logger.debug(f"Async SimBackend for {self.device_model} get_timeout returning {self._timeout_ms} ms (simulated).")
        return self._timeout_ms

# Static type checking helper
if TYPE_CHECKING:
    # Ensure SimBackend correctly implements AsyncInstrumentIO
    def _check_sim_backend_protocol_async(backend: AsyncInstrumentIO) -> None: ...
    def _test_sim_async() -> None:
        # Assuming PydanticInstrumentConfig or a compatible dict for profile
        profile_data = {"model": "TestSim"} # Example profile data
        # Create an instance of PydanticInstrumentConfig if it's defined, else dict
        try:
            from ...config import InstrumentConfig as PydanticInstrumentConfigForTest
            config_instance = PydanticInstrumentConfigForTest(**profile_data)
        except (ImportError, TypeError): # TypeError if PydanticInstrumentConfig is not a class or wrong args
            config_instance = profile_data # Fallback to dict

        _check_sim_backend_protocol_async(SimBackend(profile=config_instance))

    # If it should also implement the synchronous InstrumentIO (for phased rollout or dual use)
    def _check_sim_backend_protocol_sync(backend: InstrumentIO) -> None: ...
    # SimBackend would need to be adjusted if it were to *also* implement sync InstrumentIO
    # For this task, focus is on AsyncInstrumentIO.
    # If sync support is needed, one might have:
    # class SimBackend(InstrumentIO, AsyncInstrumentIO): ...
    # and implement both sync and async versions or make async versions call sync ones.
    # However, the prompt implies a "True Async" path, so AsyncInstrumentIO is primary.