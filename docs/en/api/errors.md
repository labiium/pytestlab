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
    DatabaseError,
)

q
except InstrumentParameterError as e:
    print(f"Invalid parameter: {e}")
except DatabaseError as e:
    print(f"Database error: {e}")
```

---

For a practical guide to error handling, see the [Error Handling Guide](../user_guide/errors.md).