"""
pytestlab.gui.async_utils
=========================

Tiny helpers that make it easy to call *async* PyTestLab APIs from ordinary
ipywidgets callbacks (which must be regular, synchronous functions).

The pattern is:

    from pytestlab.gui.async_utils import awidget_callback

    slider.observe(awidget_callback(my_async_handler), names="value")

`awidget_callback(...)` converts any ``async def`` callback into a sync wrapper
that immediately *fires-and-forgets* an ``asyncio`` Task on the currently
running event-loop (creating one if necessary – e.g. inside classic Jupyter).

This file is completely generic and can be reused in other projects.
"""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable


def run_coro_safely(coro: Awaitable[Any]) -> None:
    """
    Ensure *coro* runs on the correct event-loop even if the notebook kernel
    was started with the legacy `nest_asyncio` patch or on platforms where
    the default loop is not yet running (e.g. plain IPython).

    If no loop is running we *create* one in a background thread – this keeps
    the widget UI responsive while the hardware communication happens.
    """
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(coro)
    except RuntimeError:  # "no running event loop"
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.create_task(coro)

        # Spin the new loop in a daemonised background-task.
        # The notebook kernel thread remains free for user interaction.
        import threading

        t = threading.Thread(target=loop.run_forever, daemon=True, name="pytestlab-bg-loop")
        t.start()


def awidget_callback(async_fn: Callable[..., Awaitable[Any]]) -> Callable[[Any], None]:
    """
    Convert ``async def callback(…)`` into a synchronous function suitable for
    ipywidgets' ``observe`` / ``on_click`` APIs.

    Example
    -------
    >>> voltage_slider.observe(
    ...     awidget_callback(my_async_voltage_setter), names="value"
    ... )
    """
    def _sync_wrapper(*args: Any, **kwargs: Any) -> None:  # noqa: D401
        run_coro_safely(async_fn(*args, **kwargs))

    # Provide nice repr/help text in the notebook
    _sync_wrapper.__name__ = f"{async_fn.__name__}_sync_wrapper"
    _sync_wrapper.__doc__ = f"SYNC → async wrapper around {async_fn.__name__}()"
    return _sync_wrapper
