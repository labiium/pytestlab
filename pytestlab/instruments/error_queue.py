from __future__ import annotations

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
        paths return a bare ``0``/``+0`` for "no error"; accepting that
        no-error form prevents successful commands from failing during the
        follow-up error check.
        """
        raw = response.strip().strip('"')
        if raw in {"0", "+0"}:
            return 0, ""

        code_str, msg_part = raw.split(",", 1)
        code = int(code_str)
        message = msg_part.strip().strip('"')
        return code, message or f"SCPI error {code}"

    def check(self) -> None:
        instrument = self.instrument
        q = ":SYSTem:ERRor?"
        instrument._ensure_backend_connected()
        try:
            try:
                q = instrument.scpi_engine.build("get_error")[0]
            except Exception:
                q = ":SYSTem:ERRor?"
            error_response = instrument._backend.query(q).strip()

            try:
                code, message = self._parse_error_response(error_response)
            except (ValueError, IndexError) as e:
                if q != ":SYSTem:ERRor?":
                    try:
                        raw_resp = instrument._backend.query(":SYSTem:ERRor?").strip()
                        code, message = self._parse_error_response(raw_resp)
                    except Exception:
                        raise InstrumentCommunicationError(
                            instrument=instrument.config.model,
                            command=q,
                            message=f"Could not parse error response: '{error_response}'",
                        ) from e
                else:
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
        try:
            cmds = instrument.scpi_engine.build("clear")
        except Exception:
            cmds = ["*CLS"]
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
        try:
            q = instrument.scpi_engine.build("get_error")[0]
        except Exception:
            q = "SYSTem:ERRor?"
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
                instrument._send_command("*RST", skip_check=True)
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
