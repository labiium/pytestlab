# Exceptions

This page documents the custom exception types used throughout PyTestLab. Understanding these exceptions is essential for writing robust, reliable, and safe test scripts.

---

## Exception Reference

::: pytestlab.errors.InstrumentConnectionError
    options:
      show_root_heading: true
      show_if_no_docstring: true

::: pytestlab.errors.InstrumentCommunicationError
    options:
      show_if_no_docstring: true

::: pytestlab.errors.InstrumentParameterError

::: pytestlab.errors.OperationDiscoveryError
    options:
      show_if_no_docstring: true

::: pytestlab.errors.InstrumentConfigurationError
    options:
      show_if_no_docstring: true

::: pytestlab.errors.DatabaseError
    options:
      show_if_no_docstring: true

::: pytestlab.errors.InstrumentNotFoundError
    options:
      show_if_no_docstring: true

### ReplayMismatchError {#replaymismatcherror}

::: pytestlab.errors.ReplayMismatchError
    options:
      show_if_no_docstring: true

---

## Usage Example

```python
from pytestlab.errors import (
    InstrumentConnectionError,
    InstrumentParameterError,
)


def read_dc_voltage(dmm, range_val="AUTO"):
    try:
        return dmm.measure("dc_voltage", range_val=range_val)
    except InstrumentParameterError as exc:
        print(f"Invalid measurement setting: {exc}")
        raise
    except InstrumentConnectionError as exc:
        print(f"Could not connect to the configured meter: {exc}")
        raise
```

---

For a practical guide to error handling, see the [Error Handling Guide](../user_guide/errors.md).
