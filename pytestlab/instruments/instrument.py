import numpy as np
from ..errors import InstrumentConnectionBusy, InstrumentConfigurationError, InstrumentNotFoundError, InstrumentCommunicationError, InstrumentConnectionError, InstrumentParameterError
from ..config import InstrumentConfig
from pyscpi import usbtmc
from .backends.lamb import VisaInstrument
import time

backend = "lamb"

class Instrument:
    """
    A class representing an SCPI-compliant instrument.

    Attributes:
        visa_resource (str): The VISA resource string that identifies the instrument.
    """

    def __init__(self, config=None, debug_mode=False):
        """
        Initialize the SCPIInstrument class.

        Args:
            visa_resource (str): The VISA resource string to use for the connection.
        """
        if isinstance(config, InstrumentConfig):
            match backend:
                # case "usbtmc":
                #     self.instrument = usbtmc.Instrument(config.vendor_id, config.product_id)
                case "lamb":
                    self.instrument = VisaInstrument(config.model, config.serial_number)
                case _:
                    raise InstrumentConfigurationError("Invalid backend")
        else:
            raise InstrumentConfigurationError("Either a VISA resource string or a vendor and product ID must be provided.")
        self.config = config
        self._command_log = []
        self.debug_mode = debug_mode
        try:
            self.clear_errors()
        except InstrumentCommunicationError:
            raise InstrumentConnectionError("Failed to connect to the instrument.")

    @classmethod
    def from_config(cls, config: InstrumentConfig, debug_mode=False):
        return cls(config=InstrumentConfig(**config), debug_mode=debug_mode)

    def _read_to_np(self, data) -> bytes:
        chunk_size = 1024
        np.frombuffer(data[10:], dtype=np.uint8)
        header = data[2:10].decode('utf-8')
        data = np.frombuffer(data[10:], dtype=np.uint8)
        # self._log(header)

        # hpoints = int(header)

        # while len(data) < hpoints:
        #     data = np.append(data, np.frombuffer(
        #         self.instrument.read_raw(chunk_size), dtype=np.uint8))

        return data[:-1]

    def _send_command(self, command, skip_check=False):
        """
        Send an SCPI command to the instrument.

        Args:
            command (str): The SCPI command to send.

        Raises:
            SCPICommunicationError: If sending the command fails.
        """
        try:
            self.instrument.write(command)
            if not skip_check:
                self._error_check()
            self._command_log.append({"command": command, "success": True, "type": "write", "timestamp":time.time})
        except Exception as e:
            raise InstrumentCommunicationError(f"Failed to send command `{str(command)}`\n{str(e)}")

    def _query(self, query):
        """
        Query the instrument and return the response.

        Args:
            query (str): The SCPI query to send.

        Returns:
            str: The instrument's response to the query.

        Raises:
            SCPICommunicationError: If the query fails.
        """
        try:
            response =  self.instrument.query(query)
            self._error_check()
            # self.lo
            # print(response)
            self._command_log.append({"command": query, "success": True, "type": "query", "timestamp":time.time, "response": response})
            self.instrument.query("*OPC?")
            return response
        except Exception as e:
            self._command_log.append({"command": query, "success": False, "type": "query", "timestamp":time.time})
            raise InstrumentCommunicationError(f"Failed to query instrument: {str(e)}")
        
    def _query_raw(self, query):
        """
        Query the instrument and return the raw response.

        Args:
            query (str): The SCPI query to send.

        Returns:
            bytes: The raw instrument response to the query.

        Raises:
            SCPICommunicationError: If the query fails.
        """
        try:
            match backend:
                case "usbtmc":
                    response = self.instrument.ask_raw(query.encode("utf-8"))
                case "lamb":
                    response = self.instrument.query_raw(query)
                case _:
                    pass
            # self._error_check()
            return response
        except Exception as e:
            raise InstrumentCommunicationError(f"Failed to query instrument: {str(e)}")

    def lock_panel(self, lock=True):
        """
        Locks the panel of the instrument

        Args:
            lock (bool): True to lock the panel, False to unlock it
        """
        if lock:
            self._send_command(":SYSTem:LOCK")
        else:
            self._send_command(":SYSTem:LOCal")

    def _wait(self):
        """
        Blocks until all previous commands have been processed by the instrument.
        """
        self.instrument.query("*OPC?")
        self._log("Waiting for instrument to finish processing commands.")
        self._command_log.append({"command": "BLOCK", "success": True, "type": "wait", "timestamp":time.time})

    def _wait_event(self):
        """
        Blocks until all previous commands have been processed by the instrument.
        """
        result = 0
        while (result == 0):
            result =  int(self.instrument.query("*ESR?"))
        self._log("Waiting for instrument to finish processing commands.")
        self._command_log.append({"command": "BLOCK", "success": True, "type": "wait", "timestamp":time.time})

    def _log(self, message):
        """
        Log a message.

        Args:
            message (str): The message to log.
        """
        if self.debug_mode:
            print(message)

    def _history(self):
        """
        Prints history of executed commands
        """
        for command in self._command_log:
            print(command)

    def _error_check(self):
        """
        Checks for errors on the instrument
        """
        error = self.instrument.query(":SYSTem:ERRor?")
        if error.strip() != "+0,\"No error\"":
            raise InstrumentCommunicationError(f"Instrument returned error: {error}")


    def id(self):
        """
        Query the instrument for its identification.

        Returns:
            str: The identification string of the instrument.
        """

        name = self._query("*IDN?")
        self._log(f"Connected to {name}")
        self._command_log.append({"command": "*IDN?", "success": True, "type": "query", "timestamp":time.time, "response": name})
        return name
    
    def close(self):
        """Close the connection to the instrument."""
        self.instrument.close()

    def reset(self):
        """Reset the instrument to its default settings."""
        self._send_command("*RST")
        self._log("Resetting instrument to default settings.")
        self._command_log.append({"command": "RESET", "success": True, "type": "reset", "timestamp":time.time})

    @classmethod
    def requires(cls, requirement: str):
        """
        Decorator that can be used to specify requirements for a method.
        
        Args:
            requirement (str): The requirement that must be met for the method to be executed.
        """
        def decorator(func):
            def wrapped_func(self, *args, **kwargs):
                if self.config.requires(requirement):
                    return func(self, *args, **kwargs)
                else:
                    raise InstrumentConfigurationError(f"Method '{func.__name__}' requires '{requirement}'. This functionality is not available for this instrument.")
            return wrapped_func
        return decorator

    def clear_errors(self):
        self._send_command("*CLS")

# def error_info(original_exception_type, custom_exception_type):
#     def decorator(func):
#         def wrapper(*args, **kwargs):
#             try:
#                 return func(*args, **kwargs)
#             except original_exception_type as e:
#                 raise custom_exception_type(e) from None
#         return wrapper
#     return decorator
