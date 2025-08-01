import pytest
from typing import List, Optional

from pytestlab.instruments.instrument import Instrument
from pytestlab.config.instrument_config import InstrumentConfig
from pytestlab.instruments.backends.sim_backend import SimBackend
from pytestlab.errors import InstrumentCommunicationError, InstrumentDataError

# A specialized SimBackend for testing error handling
class ProgrammableErrorSimBackend(SimBackend):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._error_responses: List[str] = []
        self._syst_err_query_count: int = 0
        # Ensure SYST:ERR? is in the command_map if not already by default
        if "SYST:ERR?" not in self.command_map and "SYSTEM:ERROR?" not in self.command_map :
             self.command_map["SYST:ERR?"] = lambda: self._get_next_error()


    def _get_next_error(self) -> str:
        if self._syst_err_query_count < len(self._error_responses):
            response = self._error_responses[self._syst_err_query_count]
            self._syst_err_query_count += 1
            return response
        return "+0,\"No error\"" # Default after queue is exhausted

    def query(self, cmd: str, delay: Optional[float] = None) -> str:
        cmd_upper = cmd.upper().strip()
        if cmd_upper == "SYST:ERR?" or cmd_upper == "SYSTEM:ERROR?":
            return self._get_next_error()
        return super().query(cmd, delay)

    def set_error_responses(self, responses: List[str]):
        self._error_responses = responses
        self._syst_err_query_count = 0

    def get_syst_err_query_count(self) -> int:
        return self._syst_err_query_count

@pytest.fixture
def error_handling_instrument():
    """Fixture to provide an Instrument instance with ProgrammableErrorSimBackend."""
    backend = ProgrammableErrorSimBackend(default_response="DUMMY_RESPONSE")
    # Minimal config for the instrument
    config = InstrumentConfig(
        general=dict(id="TestErrorInstrument", driver="GenericInstrument"),
        settings=dict(check_errors_on_read=False, check_errors_on_write=False) # Disable auto checks for these tests
    )
    instrument = Instrument(config=config, backend=backend, address="SIM::ERRTEST")
    # instrument.connect() # connect might do an error check, skip for manual control initially
    # Manually set connected state if needed, or ensure connect doesn't auto-error-check
    instrument._connected = True # pylint: disable=protected-access
    return instrument, backend

# Tests for _error_check()

def test_error_check_no_error(error_handling_instrument):
    """Test _error_check() when SimBackend returns '+0,No error'."""
    instrument, backend = error_handling_instrument
    backend.set_error_responses(["+0,\"No error\""])

    instrument._error_check() # Should not raise an error
    assert backend.get_syst_err_query_count() == 1

def test_error_check_with_error(error_handling_instrument):
    """Test _error_check() when SimBackend returns an error string."""
    instrument, backend = error_handling_instrument
    error_message = "-101,\"Command error; Something went wrong\""
    backend.set_error_responses([error_message, "+0,\"No error\""]) # Error then no error

    with pytest.raises(InstrumentCommunicationError, match="Something went wrong"):
        instrument._error_check()
    assert backend.get_syst_err_query_count() == 1 # Should stop after first error

# Tests for get_error()

def test_get_error_no_error(error_handling_instrument):
    """Test get_error() when no error is present."""
    instrument, backend = error_handling_instrument
    backend.set_error_responses(["+0,\"No error\""])

    code, message = instrument.get_error()
    assert code == 0
    assert message == "No error"
    assert backend.get_syst_err_query_count() == 1

def test_get_error_with_error(error_handling_instrument):
    """Test get_error() correctly parses an error code and message."""
    instrument, backend = error_handling_instrument
    error_str = "-222,\"Data out of range\""
    backend.set_error_responses([error_str])

    code, message = instrument.get_error()
    assert code == -222
    assert message == "Data out of range"
    assert backend.get_syst_err_query_count() == 1

def test_get_error_malformed_response(error_handling_instrument):
    """Test get_error() with a malformed error string from the instrument."""
    instrument, backend = error_handling_instrument
    # Example of a response that doesn't fit the "code,message" pattern
    backend.set_error_responses(["MALFORMED_ERROR_STRING"])

    # Depending on implementation, this might raise an error or return default/parsed values
    # Assuming it might raise an InstrumentError or return (0, "Malformed error response")
    with pytest.raises(InstrumentDataError): # Or check for specific parsing error handling
         instrument.get_error()
    # Or if it tries to parse and fails:
    # code, message = instrument.get_error()
    # assert code == 0 # Or some other default/error indicator
    # assert "Malformed" in message
    assert backend.get_syst_err_query_count() == 1


# Tests for get_all_errors()

def test_get_all_errors_single_error(error_handling_instrument):
    """Test get_all_errors() reads a single error."""
    instrument, backend = error_handling_instrument
    error_str = "-350,\"Queue overflow\""
    backend.set_error_responses([error_str, "+0,\"No error\""])

    errors = instrument.get_all_errors()
    assert len(errors) == 1
    assert errors[0] == (-350, "Queue overflow")
    assert backend.get_syst_err_query_count() == 2 # One for error, one for "No error"

def test_get_all_errors_multiple_errors(error_handling_instrument):
    """Test get_all_errors() reads multiple errors until '+0,No error'."""
    instrument, backend = error_handling_instrument
    error1 = "-110,\"Command header error\""
    error2 = "-112,\"Program mnemonic too long\""
    backend.set_error_responses([error1, error2, "+0,\"No error\""])

    errors = instrument.get_all_errors()
    assert len(errors) == 2
    assert errors[0] == (-110, "Command header error")
    assert errors[1] == (-112, "Program mnemonic too long")
    assert backend.get_syst_err_query_count() == 3

def test_get_all_errors_no_errors_initially(error_handling_instrument):
    """Test get_all_errors() when there are no errors initially."""
    instrument, backend = error_handling_instrument
    backend.set_error_responses(["+0,\"No error\""])

    errors = instrument.get_all_errors()
    assert len(errors) == 0
    assert backend.get_syst_err_query_count() == 1

def test_get_all_errors_stops_after_max_attempts(error_handling_instrument):
    """Test get_all_errors() stops after max attempts if '+0,No error' is not received."""
    instrument, backend = error_handling_instrument
    # Instrument.MAX_ERRORS_TO_READ is assumed to be, e.g., 10 or 20.
    # Let's assume it's 10 for this test.
    # This requires knowing or setting Instrument.MAX_ERRORS_TO_READ
    # Monkeypatch or use a known value. Let's assume it's accessible or a constant.
    # For this test, we'll assume a default like 10.

    # If Instrument.MAX_ERRORS_TO_READ is not easily accessible/mockable,
    # this test might be harder to make precise.
    # Let's assume we can access/set it for the test.
    original_max_errors = Instrument.MAX_ERRORS_TO_READ
    Instrument.MAX_ERRORS_TO_READ = 5 # Temporarily change for test

    persistent_error = "-420,\"Query UNTERMINATED\""
    responses = [persistent_error] * (Instrument.MAX_ERRORS_TO_READ + 5) # More errors than max_attempts
    backend.set_error_responses(responses)

    errors = instrument.get_all_errors()
    assert len(errors) == Instrument.MAX_ERRORS_TO_READ
    for code, msg in errors:
        assert code == -420
        assert msg == "Query UNTERMINATED"
    assert backend.get_syst_err_query_count() == Instrument.MAX_ERRORS_TO_READ

    Instrument.MAX_ERRORS_TO_READ = original_max_errors # Restore original value

# Note: Some tests might depend on the exact implementation details of
# Instrument.MAX_ERRORS_TO_READ or specific error codes that halt reading.
# The provided tests cover the main scenarios described.
