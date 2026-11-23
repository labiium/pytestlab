"""Best-effort attribution for instrument transport calls."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


def describe_emitter(transport: str = "pytestlab_lamb") -> dict[str, Any]:
    """Describe the Python API that emitted the current transport operation.

    Only primitive frame data is retained. Attribution is diagnostic metadata and
    callers should tolerate the explicit raw/failure fallback.
    """
    try:
        frame = sys._getframe(1)
        candidates: list[tuple[str, str, int, str, str]] = []
        device_calls: list[tuple[str, str, int, str, str]] = []
        while frame is not None:
            module = frame.f_globals.get("__name__", "")
            name = frame.f_code.co_name
            filename = frame.f_code.co_filename
            item = (module, name, frame.f_lineno, filename, frame.f_code.co_qualname)
            if module == "pytestlab.devices.base" and name in {"query", "write", "query_raw"}:
                device_calls.append(item)
            if module.startswith("pytestlab.instruments"):
                if module.endswith(("command_attribution",)) or ".backends" in module:
                    pass
                elif module.endswith(("command_session", "error_queue")):
                    candidates.append(item)
                elif module.endswith("instrument"):
                    if name in {"_query", "_send_command", "_query_raw"}:
                        candidates.append(item)
                elif not name.startswith("__"):
                    candidates.append(item)
            frame = frame.f_back

        if device_calls:
            # A Device facade is intentionally the raw SCPI boundary.
            device_method = "Device." + device_calls[0][1]
            return _metadata("agent_raw_scpi", device_method, device_calls[0], transport)
        if candidates:
            driver = [
                item
                for item in candidates
                if not item[0].endswith(("command_session", "error_queue", "instrument"))
            ]
            public = next((item for item in driver if not item[1].startswith("_")), None)
            lowlevel = next(
                (
                    item
                    for item in candidates
                    if item[1] in {"_query", "_send_command", "_query_raw"}
                ),
                None,
            )
            chosen = public or lowlevel or candidates[0]
            result = _metadata("pytestlab_native_method", chosen[4], chosen, transport)
            if lowlevel and (public or chosen != lowlevel):
                result["lowlevel_method"] = lowlevel[4]
            return result

        # Backend direct calls and unattributed callers remain explicitly raw.
        callsite = ("", "LambBackend", 0, "<transport>", "LambBackend")
        frame = sys._getframe(1)
        while frame is not None:
            module = frame.f_globals.get("__name__", "")
            if ".backends" not in module:
                callsite = (
                    module,
                    frame.f_code.co_name,
                    frame.f_lineno,
                    frame.f_code.co_filename,
                    frame.f_code.co_qualname,
                )
                break
            frame = frame.f_back
        return _metadata("agent_raw_scpi", "LambBackend", callsite, transport)
    except Exception as exc:  # best effort must never alter I/O
        frame = sys._getframe(1)
        callsite = {"file": frame.f_code.co_filename, "line": frame.f_lineno}
        return {
            "schema_version": 1,
            "kind": "transport",
            "method": "LambBackend",
            "callsite": callsite,
            "basis": "python_call_stack",
            "transport": transport,
            "classification_complete": False,
            "instrumentation_error": type(exc).__name__,
        }


def _metadata(
    kind: str, method: str, item: tuple[str, str, int, str, str], transport: str
) -> dict[str, Any]:
    filename = item[3]
    try:
        filename = str(Path(filename).resolve())
    except Exception:
        pass
    return {
        "schema_version": 1,
        "kind": kind,
        "method": method,
        "callsite": {"file": filename, "line": item[2]},
        "basis": "python_call_stack",
        "transport": transport,
        "classification_complete": True,
    }
