"""
pytestlab.gui.async_utils
=========================

Tiny helpers that make it easy to call PyTestLab APIs from ordinary
ipywidgets callbacks (which must be regular, synchronous functions).

The pattern is:

    from pytestlab.gui.async_utils import widget_callback

    slider.observe(widget_callback(my_handler), names="value")

`widget_callback(...)` provides a consistent interface for PyTestLab callbacks
and handles any potential threading concerns for GUI interactions.

This file is completely generic and can be reused in other projects.
"""
from __future__ import annotations

from typing import Any, Callable
import threading


def run_safely(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
    """
    Run a function safely in a background thread to keep the widget UI responsive
    while hardware communication happens.
    """
    def _thread_target():
        try:
            fn(*args, **kwargs)
        except Exception as e:
            print(f"Error in widget callback: {e}")
            import traceback
            traceback.print_exc()

    t = threading.Thread(target=_thread_target, daemon=True, name="pytestlab-widget-callback")
    t.start()


def widget_callback(fn: Callable[..., Any]) -> Callable[[Any], None]:
    """
    Convert a PyTestLab callback function into a function suitable for
    ipywidgets' ``observe`` / ``on_click`` APIs.

    Example
    -------
    >>> voltage_slider.observe(
    ...     widget_callback(my_voltage_setter), names="value"
    ... )
    """
    def _wrapper(*args: Any, **kwargs: Any) -> None:  # noqa: D401
        run_safely(fn, *args, **kwargs)

    # Provide nice repr/help text in the notebook
    _wrapper.__name__ = f"{fn.__name__}_widget_wrapper"
    _wrapper.__doc__ = f"Widget wrapper around {fn.__name__}()"
    return _wrapper


# Legacy alias for backward compatibility
awidget_callback = widget_callback
