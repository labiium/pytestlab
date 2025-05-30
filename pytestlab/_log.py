from __future__ import annotations # Consistent with Section B changes
import logging
import sys
import os

def get_logger(name: str) -> logging.Logger:
    """
    Retrieves a logger instance, configuring the root logger on first call.
    """
    root = logging.getLogger("pytestlab")
    if not root.handlers:
        level_name = os.getenv("PYTESTLAB_LOG", "WARNING").upper()
        log_level = getattr(logging, level_name, logging.WARNING)
        
        # Ensure basicConfig is only called if no handlers are configured for the root logger
        # This check is slightly more robust if other parts of an application might configure logging.
        if not logging.getLogger().handlers: # Check handlers on the *actual* root logger
            logging.basicConfig(
                level=log_level,
                format="%(asctime)s %(name)s %(levelname)s – %(message)s",
                handlers=[logging.StreamHandler(sys.stderr)]
            )
        else: # If root is configured, just set level for our specific root logger
            root.setLevel(log_level)

        # If basicConfig configured the actual root, ensure our pytestlab logger also has handlers
        # or add one if it doesn't (e.g. if basicConfig was skipped due to other handlers)
        if not root.handlers:
            handler = logging.StreamHandler(sys.stderr)
            formatter = logging.Formatter("%(asctime)s %(name)s %(levelname)s – %(message)s")
            handler.setFormatter(formatter)
            root.addHandler(handler)
            root.setLevel(log_level) # Ensure level is set if we added handler manually

    return root.getChild(name)