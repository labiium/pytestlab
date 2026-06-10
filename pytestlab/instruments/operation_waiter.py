from __future__ import annotations

import time
from typing import TYPE_CHECKING
from typing import Any

from ..errors import InstrumentCommunicationError

if TYPE_CHECKING:
    from .instrument import Instrument


class InstrumentOperationWaiter:
    """SCPI operation-complete and event polling helper."""

    def __init__(self, instrument: Instrument[Any]) -> None:
        self.instrument = instrument

    def wait(self) -> None:
        instrument = self.instrument
        q = "*OPC?"
        instrument._ensure_backend_connected()
        try:
            try:
                q = instrument.scpi_engine.build("opc_query")[0]
            except Exception:
                q = "*OPC?"
            instrument._backend.query(q)
            instrument._logger.debug(
                "Waiting for instrument to finish processing commands (*OPC? successful)."
            )
            instrument._command_log.append(
                {"command": q, "success": True, "type": "wait", "timestamp": time.time()}
            )
        except Exception as e:
            instrument._logger.debug(f"Error during *OPC? wait: {e}")
            raise InstrumentCommunicationError(
                instrument=instrument.config.model,
                command=q,
                message="Failed to wait for operation complete.",
            ) from e

    def wait_event(self) -> None:
        instrument = self.instrument
        q = "*ESR?"
        instrument._ensure_backend_connected()
        result = 0
        max_attempts = 100
        attempts = 0
        while result == 0 and attempts < max_attempts:
            try:
                try:
                    q = instrument.scpi_engine.build("esr_query")[0]
                except Exception:
                    q = "*ESR?"
                esr_response = instrument._backend.query(q)
                result = int(esr_response.strip())
            except Exception as e:
                instrument._logger.debug(f"Error querying *ESR? during _wait_event: {e}")
                raise InstrumentCommunicationError(
                    instrument=instrument.config.model,
                    command=q,
                    message="Failed to query *ESR? during wait.",
                ) from e
            time.sleep(0.1)
            attempts += 1

        if attempts >= max_attempts and result == 0:
            instrument._logger.debug(
                "Warning: _wait_event timed out polling *ESR?. ESR did not become non-zero."
            )
        else:
            instrument._logger.debug(
                f"Instrument event occurred or ESR became non-zero (ESR: {result})."
            )
        instrument._command_log.append(
            {
                "command": "*ESR? poll",
                "success": True,
                "type": "wait_event",
                "timestamp": time.time(),
                "final_esr": result,
            }
        )

    def wait_for_operation_complete(
        self, query_instrument: bool = True, timeout: float = 10.0
    ) -> str | None:
        instrument = self.instrument
        if query_instrument:
            instrument._logger.debug(
                f"Waiting for operation complete (*OPC?). Effective timeout depends on backend (method timeout hint: {timeout}s)."
            )
            q = "*OPC?"
            try:
                try:
                    q = instrument.scpi_engine.build("opc_query")[0]
                except Exception:
                    q = "*OPC?"
                response = instrument._query(q)
                instrument._logger.debug("Operation complete query (*OPC?) returned.")
                if response.strip() != "1":
                    instrument._logger.debug(
                        f"Warning: *OPC? returned '{response}' instead of expected '1'."
                    )
                return response.strip()
            except InstrumentCommunicationError as e:
                err_msg = f"*OPC? query failed. This may be due to backend communication timeout (related to method's timeout param: {timeout}s)."
                instrument._logger.debug(err_msg)
                raise InstrumentCommunicationError(
                    instrument=instrument.config.model, command=q, message=err_msg
                ) from e

        try:
            cmds = instrument.scpi_engine.build("opc")
        except Exception:
            cmds = ["*OPC"]
        for c in cmds:
            instrument._send_command(c)
        instrument._logger.debug(
            "Operation complete command (*OPC) sent (non-blocking). Status polling required."
        )
        return None
