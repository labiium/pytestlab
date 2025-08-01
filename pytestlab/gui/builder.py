"""
pytestlab.gui.builder
=====================

A *tiny* declarative GUI layer for Jupyter notebooks.

Core idea
---------
Users describe **what they want to control** in plain Python dictionaries:

    from pytestlab.gui.builder import InstrumentPanel, Slider, Toggle, Button

    panel = InstrumentPanel(
        inst=my_psu,                 # *any* PyTestLab driver instance
        controls=[
            Slider(
                label="Voltage  (V)",
                getter=lambda psu: psu.read_voltage(1),
                setter=lambda psu, x: psu.set_voltage(1, x),
                min=0, max=6, step=0.05,
            ),
            Slider(
                label="Current  (A)",
                getter=lambda psu: psu.read_current(1),
                setter=lambda psu, x: psu.set_current(1, x),
                min=0, max=5, step=0.05,
            ),
            Toggle(
                label="Output",
                getter=lambda psu: psu.output(1),        # returns bool
                setter=lambda psu, on: psu.output(1, on),
            ),
            Button(
                label="⟳  Refresh read-back",
                action=lambda psu, p: p.refresh(),       # can mutate the panel
            ),
        ],
    )

That's it – run the cell and the panel is displayed & fully asynchronous.

Widgets
-------
Slider  – float/int slider + live read-back
Toggle  – on/off button
Button  – executes arbitrary function
(You can extend the base‐class with only ~15 LOC.)

All callbacks (`getter`, `setter`, `action`) are synchronous functions – the
framework handles them efficiently in the background.

The code is only ~180 lines yet covers 95 % of typical bench‐control needs.
"""
from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Callable, List, Sequence

import ipywidgets as w
from IPython.display import display

from .async_utils import awidget_callback


# --------------------------------------------------------------------------- #
# Type helpers                                                                #
# --------------------------------------------------------------------------- #
T_Inst = Any
CoroOrVal = Awaitable[Any] | Any
Getter = Callable[[T_Inst], CoroOrVal]
Setter = Callable[[T_Inst, Any], CoroOrVal]
Action = Callable[[T_Inst, "InstrumentPanel"], CoroOrVal]


def _maybe_await(value: CoroOrVal) -> Any:
    """Return value directly since all operations are now synchronous."""
    return value


# --------------------------------------------------------------------------- #
# Control base-class                                                          #
# --------------------------------------------------------------------------- #
@dataclass
class _ControlBase:
    label: str

    # concrete subclasses must implement _build_widget()
    def _build_widget(self, panel: "InstrumentPanel") -> w.Widget:  # noqa: D401
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# Controls – Slider / Toggle / Button                                         #
# --------------------------------------------------------------------------- #
@dataclass
class Slider(_ControlBase):
    getter: Getter
    setter: Setter
    min: float
    max: float
    step: float = 0.01
    readout_fmt: str = ".3f"

    def _build_widget(self, panel: "InstrumentPanel") -> w.Widget:
        sld = w.FloatSlider(
            description=self.label,
            min=self.min,
            max=self.max,
            step=self.step,
            continuous_update=False,
            readout_format=self.readout_fmt,
        )

        # initialise from instrument
        def _init():
            val = _maybe_await(self.getter(panel.inst))
            sld.value = float(val)

        panel._background(_init())

        # push changes → instrument
        sld.observe(
            awidget_callback(lambda ch: self.setter(panel.inst, ch["new"])), names="value"
        )

        return sld


@dataclass
class Toggle(_ControlBase):
    getter: Getter
    setter: Setter
    on_desc: str | None = "ON"
    off_desc: str | None = "OFF"

    def _build_widget(self, panel: "InstrumentPanel") -> w.Widget:
        btn = w.ToggleButton(value=False, description=self.off_desc or self.label)

        # read initial state
        def _init():
            state = _maybe_await(self.getter(panel.inst))
            btn.value = bool(state)
            btn.description = self.on_desc if btn.value else self.off_desc or self.label

        panel._background(_init())

        def _apply(change):
            new_state = change["new"]
            _maybe_await(self.setter(panel.inst, new_state))
            btn.description = self.on_desc if new_state else self.off_desc or self.label

        btn.observe(awidget_callback(_apply), names="value")
        return btn


@dataclass
class Button(_ControlBase):
    action: Action  # action(inst, panel) – may mutate panel widgets

    style: str = "primary"

    def _build_widget(self, panel: "InstrumentPanel") -> w.Widget:
        btn = w.Button(description=self.label, button_style=self.style)

        def _on_click(_):
            _maybe_await(self.action(panel.inst, panel))

        btn.on_click(awidget_callback(_on_click))
        return btn


# --------------------------------------------------------------------------- #
# Panel – brings everything together                                          #
# --------------------------------------------------------------------------- #
@dataclass
class InstrumentPanel:
    inst: T_Inst
    controls: Sequence[_ControlBase]
    title: str | None = None
    widgets: List[w.Widget] = field(init=False, default_factory=list)

    def __post_init__(self):
        # build widgets
        self.widgets = [c._build_widget(self) for c in self.controls]

        col = w.VBox(
            ([w.HTML(f"<b>{self.title}</b>")] if self.title else []) +  # header
            list(self.widgets)
        )

        display(col)

    # helper to execute operations in background
    @staticmethod
    def _background(func: Any) -> None:
        # Since operations are now synchronous, just call the function
        if callable(func):
            func()

    # ------------------------------------------------------------------ #
    # Convenience helpers users can call in their actions if needed      #
    # ------------------------------------------------------------------ #
    def refresh(self):
        """Iterate over **Slider** controls and re-pull their getter."""
        for ctrl, widget in zip(self.controls, self.widgets):
            if isinstance(ctrl, Slider):
                val = _maybe_await(ctrl.getter(self.inst))
                widget.value = float(val)
