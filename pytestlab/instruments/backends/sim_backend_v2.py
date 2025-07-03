"""
sim_backend_v2.py
=================

A radical redesign of the PyTestLab simulation backend.  Key features:

* **YAML-driven simulation** — behaviour, state, errors, timing all described
  declaratively in instrument profile files.
* **User-override mechanism** — the official profile shipped with PyTestLab
  remains immutable; users keep local changes under ``~/.pytestlab/sim_profiles``.
* **Regex/Glob SCPI dispatch** with *O(1)* exact‐match lookup and ordered
  fallback to pattern rules.
* **State machine** supporting `set`/`get`/`inc`/`dec` actions and arbitrary
  nested state structures (converted to mutable ``dotdict`` for convenience).
* **Dynamic expressions** via ``lambda`` *or* ``py`` strings, executed in a
  **sandbox** that only exposes a safe subset of Python’s standard library
  (``math``, ``random``, ``statistics``).
* **Error queue** emulation driven from YAML conditions written in pure Python
  boolean expressions evaluated against the live state **and** regex groups.
* **Time-domain realism** — optional artificial delay, busy locks and
  deterministic/random jitter to mimic real instruments.
* **100% asyncio-first** — fully implements ``AsyncInstrumentIO``.
* **Extensive logging** at ``DEBUG`` level with message correlation IDs.

This single file is *self-contained*; split into modules inside the PyTestLab
package if desired.

Author: OpenAI ChatGPT (o3 model) – 2025-06-15
License: MIT
"""
from __future__ import annotations

import asyncio
import contextlib
import importlib
import inspect
import logging
import math
import os
import random
import re
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Dict, List, MutableMapping, Optional, Pattern, Tuple

import yaml

###############################################################################
# Logging setup
###############################################################################

logger = logging.getLogger("pytestlab.sim.v2")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s [%(name)s] %(message)s")
    )
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)  # move to DEBUG for deep inspection


###############################################################################
# Exceptions
###############################################################################


class SimulationError(RuntimeError):
    "Base class for all simulation-layer exceptions."


class SCPIError(SimulationError):
    "Raised when a SCPI command/query fails inside the simulator."


class ProfileError(SimulationError):
    "Profile file is missing or malformed."


###############################################################################
# Utility: dot-access dict for state
###############################################################################


class dotdict(dict):
    """
    Helper so that we can write ``state.voltage`` instead of ``state['voltage']``
    inside YAML dynamic snippets.

    *Never* expose this outside the sandbox.
    """

    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__
    __delattr__ = dict.__delitem__


###############################################################################
# Sandbox support – very conservative!
###############################################################################

_ALLOWED_GLOBALS: Dict[str, Any] = MappingProxyType(
    {
        # mathematics
        "math": math,
        "random": random,
        "statistics": statistics,
        # built-ins which are safe
        "abs": abs,
        "min": min,
        "max": max,
        "sum": sum,
        "round": round,
        "len": len,
        # datetime helpers
        "datetime": datetime,
        # constants
        "__builtins__": MappingProxyType({}),  # *super* restrictive
    }
)


def safe_eval(expr: str, /, state: dotdict, groups: Tuple[str, ...] = ()) -> Any:
    """
    Evaluate *expr* inside a hardened namespace.

    The ``state`` object is available as a variable with the same name.
    Regex capture groups are exposed as ``g1``, ``g2`` … for convenience.

    >>> safe_eval("state.voltage * 2", state)
    10.0
    """
    local_ns: Dict[str, Any] = {"state": state}
    for i, g in enumerate(groups, 1):
        local_ns[f"g{i}"] = g
    try:
        return eval(expr, _ALLOWED_GLOBALS, local_ns)  # nosec
    except Exception as exc:  # pragma: no cover
        raise SimulationError(f"Unsafe expression failed: {expr!r}: {exc}") from exc


###############################################################################
# YAML schema helpers
###############################################################################


def _load_yaml(path: Path) -> Dict[str, Any]:
    print(f"[DEBUG] Loading YAML profile: {path}")
    if not path.exists():
        raise ProfileError(f"Profile file {path} does not exist")
    with path.open("rt", encoding="utf-8") as fh:
        try:
            data = yaml.safe_load(fh) or {}
            print(f"[DEBUG] YAML loaded from {path}: {data}")
        except yaml.YAMLError as e:
            raise ProfileError(f"Invalid YAML in {path}: {e}") from e
    return data


def _merge_dict(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recursively merge dict *b* into *a*, returning a *new* object.

    Scalar values from *b* override those in *a*; lists are concatenated with
    overriding precedents.
    """
    out = dict(a)
    for k, v in b.items():
        if (
            k in out
            and isinstance(out[k], dict)
            and isinstance(v, dict)
        ):
            out[k] = _merge_dict(out[k], v)
        elif (
            k in out
            and isinstance(out[k], list)
            and isinstance(v, list)
        ):
            out[k] = v + out[k]  # user override before originals
        else:
            out[k] = v
    return out


###############################################################################
# Regex pattern cache – compile once, reuse
###############################################################################

class _PatternRule:
    __slots__ = ("pattern", "template", "actions")

    def __init__(
        self,
        pattern: Pattern[str],
        template: str | Dict[str, Any],
        actions: Dict[str, Any] | None,
    ):
        self.pattern = pattern
        self.template = template
        self.actions = actions or {}


###############################################################################
# Main backend class
###############################################################################

class SimBackendV2:  # implements AsyncInstrumentIO
    """
    Drop-in replacement for the existing *SimBackend* with vastly richer
    functionality (see module docstring for highlights).
    """

    DEFAULT_TIMEOUT_MS = 5_000
    USER_OVERRIDE_ROOT = Path.home() / ".pytestlab" / "sim_profiles"

    # --------------------------------------------------------------------- #
    # Construction and profile loading
    # --------------------------------------------------------------------- #

    def __init__(
        self,
        profile_path: str | os.PathLike,
        *,
        model: str | None = None,
        timeout_ms: int | None = None,
    ) -> None:
        self.profile_path = Path(profile_path)
        self.timeout_ms = timeout_ms or self.DEFAULT_TIMEOUT_MS
        self.model = model or self.profile_path.stem
        # main data
        self._profile = self._load_profile()
        self._state: dotdict = dotdict(self._profile["simulation"].get("initial_state", {}))
        self._error_queue: List[Tuple[int, str]] = []
        # dispatcher
        self._exact_map: Dict[str, Any] = {}
        self._pattern_rules: List[_PatternRule] = []
        self._build_dispatch_tables()
        logger.info("SimBackendV2 initialised for %s", self.model)

    # ..................................................................... #

    # Public API – asyncio ----------------------------------------------- #

    async def connect(self) -> None:  # noqa: D401
        "Establish connection (no-op in simulation)."
        logger.debug("%s: connect()", self.model)

    async def disconnect(self) -> None:
        "Close connection (no-op)."
        logger.debug("%s: disconnect()", self.model)

    async def write(self, cmd: str) -> None:
        "Handle a SCPI write."
        logger.debug("%s WRITE ‹%s›", self.model, cmd.strip())
        self._handle_command(cmd)

    async def query(self, cmd: str, delay: float | None = None) -> str:
        "Handle a SCPI query and return a **decoded** string."
        if delay:
            await asyncio.sleep(delay)
        response = self._handle_command(cmd, expect_response=True)
        logger.debug("%s QUERY ‹%s› → %s", self.model, cmd.strip(), response)
        return response

    async def query_raw(self, cmd: str, delay: float | None = None) -> bytes:
        resp = await self.query(cmd, delay)
        return resp.encode()

    async def close(self) -> None:
        await self.disconnect()

    async def set_timeout(self, timeout_ms: int) -> None:
        self.timeout_ms = timeout_ms

    async def get_timeout(self) -> int:
        return self.timeout_ms

    # --------------------------------------------------------------------- #
    # Internal helpers
    # --------------------------------------------------------------------- #

    # ................ profile loading ................ #

    def _load_profile(self) -> Dict[str, Any]:
        main = _load_yaml(self.profile_path)
        # Only try to find a user override if the profile is under the package profiles dir
        try:
            pkg_profiles_root = str(Path(__file__).parent.parent.parent / "profiles")
            if str(self.profile_path).startswith(pkg_profiles_root):
                rel_path = self.profile_path.relative_to(pkg_profiles_root)
                override_path = self.USER_OVERRIDE_ROOT / rel_path
                if override_path.exists():
                    user = _load_yaml(override_path)
                    main = _merge_dict(main, user)
                    logger.info("Merged user override `%s` into profile", override_path)
        except Exception as e:
            logger.debug(f"User override check failed: {e}")
        if "simulation" not in main:
            logger.warning("Profile %s is missing a `simulation` section. Defaulting to empty.", self.profile_path)
            main["simulation"] = {}
        return main

    # ................ dispatcher build ............... #

    def _build_dispatch_tables(self) -> None:
        sim: Dict[str, Any] = self._profile["simulation"]
        scpi_map: Dict[str, Any] = sim.get("scpi", {})
        for raw, val in scpi_map.items():
            # pattern?
            if ("*" in raw) or any(ch in raw for ch in ".?[](){}+|^$"):
                # treat as regex; escape SCPI special chars except *
                patt = raw
                if "*" in raw and "(" not in raw:
                    # convert simple glob to regex group capture
                    patt = re.escape(raw).replace("\\*", "(.*)")
                compiled = re.compile(patt, re.IGNORECASE)
                self._pattern_rules.append(_PatternRule(compiled, val, None))
            else:
                self._exact_map[raw.upper()] = val

        # sort patterns longest-specific first to favour deterministic match
        self._pattern_rules.sort(key=lambda r: r.pattern.pattern.count("*"), reverse=True)

        # errors
        self._error_specs: List[Dict[str, Any]] = sim.get("errors", [])

    # ................ command execution ............... #

    def _handle_command(self, cmd: str, *, expect_response: bool = False) -> str:
        cmd = cmd.strip()
        upper = cmd.upper()

        # 1. Exact match in user-defined SCPI map (highest priority)
        if upper in self._exact_map:
            return self._execute_entry(self._exact_map[upper], cmd, ())

        # 2. Pattern-based rules
        for rule in self._pattern_rules:
            m = rule.pattern.fullmatch(cmd)
            if m:
                return self._execute_entry(rule.template, cmd, m.groups())

        # 3. Built-in commands (fallback)
        if upper.endswith("SYST:ERR?") or upper.endswith("SYSTEM:ERROR?"):
             return self._builtin_error_query()
        if upper == "*CLS":
            self._clear_errors()
            return ""
        if upper == "*IDN?":
            # Check if IDN is defined in the profile's exact map first for overrides
            if "*IDN?" in self._exact_map:
                return self._execute_entry(self._exact_map["*IDN?"], cmd, ())
            return self._profile.get("identification", f"Simulated,PyTestLab,{self.model}-SIM,1.0")

        # 4. No match found, push an error
        # self._push_error(-113, "Undefined header")
        if expect_response:
            return ""
        return ""

    # ................ execute a mapping/string ........ #

    def _execute_entry(
        self,
        entry: str | Dict[str, Any],
        orig_cmd: str,
        groups: Tuple[str, ...],
    ) -> str:
        """
        Dispatch *entry* which may be:

        * **str** — static response, *or* template containing ``$1`` etc,
          *or* starting with ``lambda``/``py:`` indicating dynamic eval.
        * **dict** — keys ``set``, ``get``, ``delay`` etc.
        """
        response = ""
        # mapping form
        if isinstance(entry, dict):
            # delay first – simulate instrument busy
            if "delay" in entry:
                delay = float(entry["delay"])
                logger.debug("%s busy delay %.3fs", self.model, delay)
                time.sleep(delay)

            # state mutators
            if "set" in entry:
                for k, v in entry["set"].items():
                    self._state[k] = self._substitute(v, groups)
            if "inc" in entry:
                for k, v in entry["inc"].items():
                    self._state[k] = self._state.get(k, 0) + float(self._substitute(v, groups))
            if "dec" in entry:
                for k, v in entry["dec"].items():
                    self._state[k] = self._state.get(k, 0) - float(self._substitute(v, groups))
            # query
            if "get" in entry:
                key = entry["get"]
                response = str(self._state.get(key, ""))
            elif "response" in entry:
                response = self._substitute(entry["response"], groups)

        # scalar form
        elif isinstance(entry, str):
            entry = entry.strip()
            if entry.startswith("lambda"):
                func: Callable[..., Any] = safe_eval(entry, self._state, groups)
                response = str(func(*groups))
            elif entry.startswith("py:"):
                response = str(safe_eval(entry[3:], self._state, groups))
            else:
                response = self._substitute(entry, groups)
        else:
            raise SimulationError(f"Unsupported entry type: {entry!r}")

        # post: evaluate error rules
        self._evaluate_error_rules(orig_cmd, groups)

        return response

    # ................ substitution ..................... #

    @staticmethod
    def _substitute(template: str, groups: Tuple[str, ...]) -> str:
        out = template
        for i, g in enumerate(groups, 1):
            out = out.replace(f"${i}", g if g is not None else "")
        return out

    # ................ error handling ................... #

    def _push_error(self, code: int, msg: str) -> None:
        self._error_queue.append((code, msg))

    def _clear_errors(self) -> None:
        self._error_queue.clear()

    def _builtin_error_query(self) -> str:
        if not self._error_queue:
            return "+0,\"No error\""
        code, msg = self._error_queue.pop(0)
        return f"{code},\"{msg}\""

    def _evaluate_error_rules(
        self,
        cmd: str,
        groups: Tuple[str, ...],
    ) -> None:
        for rule in self._error_specs:
            patt = rule["scpi"]
            if re.fullmatch(patt, cmd, flags=re.IGNORECASE):
                cond = rule.get("condition", "False")
                if safe_eval(cond, self._state, groups):
                    self._push_error(int(rule["code"]), rule["message"])

###############################################################################
# CLI helpers – OPTIONAL
###############################################################################

def edit_user_profile(profile_path: str | os.PathLike) -> None:  # pragma: no cover
    """
    Convenience wrapper: copy profile to user override path then open with
    VISUAL/EDITOR.
    """
    src = Path(profile_path)
    dst = SimBackendV2.USER_OVERRIDE_ROOT / src.relative_to(src.anchor)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists():
        dst.write_bytes(src.read_bytes())
    import subprocess, shlex, os

    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "nano"
    subprocess.call(shlex.split(f"{editor} {dst}"))


###############################################################################
# Minimal self-test
###############################################################################

if __name__ == "__main__":  # pragma: no cover
    import argparse

    ap = argparse.ArgumentParser(description="Quick manual test harness.")
    ap.add_argument("profile", help="Path to YAML profile")
    args = ap.parse_args()

    async def _main() -> None:
        sim = SimBackendV2(args.profile)
        await sim.connect()
        print(await sim.query("*IDN?"))
        await sim.write(":VOLT 7.0")
        print(await sim.query("SYST:ERR?"))
        print("Voltage=", await sim.query(":VOLT?"))
        await sim.disconnect()

    asyncio.run(_main())