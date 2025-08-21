from __future__ import annotations

import pathlib

from .._log import get_logger
from .patch import apply_patches

_LOG = get_logger("compliance")


def initialize():
    """
    Initialize the compliance features.
    """
    _LOG.info("Initializing compliance features...")
    homedir = pathlib.Path.home() / ".pytestlab"
    homedir.mkdir(exist_ok=True)
    apply_patches(homedir)


# Automatically initialize when the module is imported.
initialize()
