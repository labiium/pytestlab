# Optional notebook GUI

`pytestlab.gui` provides `InstrumentPanel`, `Slider`, `Toggle`, and `Button` for
declarative Jupyter controls. Importing the package itself is lazy; accessing a
widget class requires the optional `ipywidgets` package.

```python
from pytestlab.gui import Button, InstrumentPanel, Slider, Toggle
```

Callbacks are synchronous PyTestLab operations wrapped for widget event handlers.
The GUI surface is intentionally excluded from generated mkdocstrings in the core
documentation environment because `ipywidgets` is not a core runtime dependency.
