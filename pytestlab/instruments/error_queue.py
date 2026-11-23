from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING
from typing import Any

from ..errors import InstrumentCommunicationError

if TYPE_CHECKING:
    from .instrument import Instrument


class InstrumentErrorQueue:
    """SCPI error queue parsing, status clearing, and recovery helper."""

    def __init__(self, instrument: Instrument[Any]) -> None:
        self.instrument = instrument

    @staticmethod
    def _parse_error_response(response: str) -> tuple[int, str]:
        """Parse common SCPI error queue response variants.

        Most instruments return ``<code>,"<message>"``.  Some USBTMC/LAMB
        paths return only the numeric code. A bare signed integer is valid,
        including nonzero codes, which must still be surfaced as errors by
        callers.
        """
        raw = response.strip()
        if raw.startswith('"') and raw.endswith('"') and len(raw) >= 2:
            raw = raw[1:-1].strip()

        if "," in raw:
            code_str, msg_part = raw.split(",", 1)
            message = msg_part.strip()
            if message.startswith('"') and message.endswith('"') and len(message) >= 2:
                message = message[1:-1]
        else:
            code_str = raw
            message = ""

        code_str = code_str.strip()
        if re.fullmatch(r"[+-]?\d+", code_str) is None:
            raise ValueError(f"Invalid SCPI error code: {code_str!r}")
        code = int(code_str)
        return code, message or (f"SCPI error {code}" if code != 0 else "")

    def check(self) -> None:
        instrument = self.instrument
        instrument._ensure_backend_connected()
        q = instrument._build_profile_alias("get_error")[0]
        try:
            error_response = instrument._backend.query(q).strip()
            try:
                code, message = self._parse_error_response(error_response)
            except (ValueError, IndexError) as e:
                raise InstrumentCommunicationError(
                    instrument=instrument.config.model,
                    command=q,
                    message=f"Could not parse error response: '{error_response}'",
                ) from e

            if code != 0:
                raise InstrumentCommunicationError(
                    instrument=instrument.config.model,
                    message=f"Instrument error: {message}",
                )
        except InstrumentCommunicationError:
            raise
        except Exception as e:
            raise InstrumentCommunicationError(
                instrument=instrument.config.model,
                command=q,
                message=f"Failed to query instrument for errors: {e}",
            ) from e

    def clear_status(self) -> None:
        instrument = self.instrument
        cmds = instrument._build_profile_alias("clear")
        for c in cmds:
            instrument._send_command(c, skip_check=True)
        instrument._logger.debug("Status registers and error queue cleared (*CLS).")

    def get_all_errors(self) -> list[tuple[int, str]]:
        instrument = self.instrument
        errors: list[tuple[int, str]] = []
        for i in range(instrument.MAX_ERRORS_TO_READ):
            try:
                code, message = instrument.get_error()
            except InstrumentCommunicationError as e:
                instrument._logger.debug(
                    f"Communication error while reading error queue (iteration {i + 1}): {e}"
                )
                if errors:
                    instrument._logger.debug(
                        f"Returning errors read before communication failure: {errors}"
                    )
                return errors

            if code == 0:
                break
            errors.append((code, message))
            if code == -350:
                instrument._logger.debug("Error queue overflow (-350) detected. Stopping read.")
                break
        else:
            instrument._logger.debug(
                f"Warning: Read {instrument.MAX_ERRORS_TO_READ} errors without reaching 'No error'. "
                "Error queue might still contain errors or be in an unexpected state."
            )

        if not errors:
            instrument._logger.debug("No errors found in instrument queue.")
        else:
            instrument._logger.debug(f"Retrieved {len(errors)} error(s) from queue: {errors}")
        return errors

    def get_error(self) -> tuple[int, str]:
        instrument = self.instrument
        q = instrument._build_profile_alias("get_error")[0]
        response = (instrument._query(q, skip_check=True)).strip()
        try:
            code, message = self._parse_error_response(response)
        except (ValueError, IndexError) as e:
            instrument._logger.debug(
                f"Warning: Unexpected error response format: '{response}'. Raising error."
            )
            raise InstrumentCommunicationError(
                instrument=instrument.config.model,
                command=q,
                message=f"Could not parse error response: '{response}'",
            ) from e

        if code != 0:
            instrument._logger.debug(f"Instrument Error Query: Code={code}, Message='{message}'")
        return code, message

    def attempt_recovery(self) -> bool:
        instrument = self.instrument
        instrument._logger.info("Attempting to recover from instrument error state...")

        try:
            instrument._logger.debug("Attempting to clear status and errors...")
            instrument.clear_status()
            errors = instrument.get_all_errors()
            if errors:
                instrument._logger.info(f"Cleared {len(errors)} errors: {errors}")

            try:
                idn = instrument.id()
                instrument._logger.info(f"Instrument recovered, ID: {idn}")
                return True
            except Exception as e:
                instrument._logger.warning(f"Still unresponsive after clearing errors: {e}")

            instrument._logger.debug("Attempting instrument reset...")
            try:
                instrument._send_profile_alias("reset")
                time.sleep(2.0)

                idn = instrument.id()
                instrument._logger.info(f"Instrument recovered after reset, ID: {idn}")
                return True
            except Exception as e:
                instrument._logger.error(f"Reset failed: {e}")

        except Exception as e:
            instrument._logger.error(f"Error recovery attempt failed: {e}")

        instrument._logger.error("Failed to recover instrument from error state")
        return False
