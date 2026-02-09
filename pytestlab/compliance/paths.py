"""Compliance path resolution.

The compliance system needs a place to store local state (keys, audit DB).
Historically this used `~/.pytestlab/`, but that is non-standard and can be
undesirable.

We now use platform-appropriate state locations by default and allow explicit
override via environment variables.

Overrides:
    - `PYTESTLAB_STATE_DIR`: absolute or relative path to store compliance state

Defaults (no override):
    - macOS:   ~/Library/Application Support/pytestlab
    - Linux:   $XDG_STATE_HOME/pytestlab or ~/.local/state/pytestlab
    - Windows: %LOCALAPPDATA%\\pytestlab or %APPDATA%\\pytestlab
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


ENV_STATE_DIR = "PYTESTLAB_STATE_DIR"


def state_dir() -> Path:
    """Return the base directory for local pytestlab compliance state."""
    override = os.getenv(ENV_STATE_DIR)
    if override:
        return Path(override).expanduser()

    home = Path.home()

    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "pytestlab"

    if sys.platform.startswith("win"):
        base = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA")
        if base:
            return Path(base) / "pytestlab"
        return home / "AppData" / "Local" / "pytestlab"

    # Linux / other unix
    xdg_state = os.getenv("XDG_STATE_HOME")
    if xdg_state:
        return Path(xdg_state) / "pytestlab"
    return home / ".local" / "state" / "pytestlab"


def key_dir() -> Path:
    return state_dir() / "keys"


def private_key_path(name: str = "auto_generated.pem") -> Path:
    return key_dir() / name


def public_key_path(name: str = "auto_generated.pub") -> Path:
    return key_dir() / name


def audit_db_path(name: str = "audit.sqlite") -> Path:
    return state_dir() / name
