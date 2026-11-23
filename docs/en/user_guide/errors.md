# Error Handling

PyTestLab provides robust error handling through a set of custom exception types. Understanding these exceptions and best practices for handling them will help you write reliable, safe, and maintainable test scripts.

---

## Common Exceptions

Here are the most important exception types you may encounter:

- **`InstrumentConnectionError`**
  Raised when PyTestLab fails to connect to an instrument. Causes include an incorrect address, network issues, or the instrument being offline.

- **`InstrumentCommunicationError`**
  Raised when an error occurs during communication with an instrument after a connection is established. Examples: timeouts, malformed commands, or unexpected responses.

- **`InstrumentParameterError`**
  Raised when an invalid parameter is passed to an instrument method. For example, setting a voltage outside the allowed range.

- **`InstrumentConfigurationError`**
  Raised when there is an error in an instrument's profile or bench configuration file. This can happen if required fields are missing or the file does not conform to the expected schema.

- **`SafetyLimitError`**
  Raised when a supported operation would violate a configured bench limit. It does not replace station interlocks or hardware protection. Import it from `pytestlab.bench`.

- **`AttributeError` or `KeyError` for a bench alias**
  A nonexistent `bench.alias` raises `AttributeError`; a nonexistent `bench.devices["alias"]` key raises `KeyError`. Check the configured names with `ptl bench ls`.

---

## Best Practices

### Catch Specific Exceptions

Always catch the most specific exception possible. This allows you to handle different error types appropriately.

```python
import pytestlab
from pytestlab.bench import SafetyLimitError
from pytestlab.errors import InstrumentConnectionError, InstrumentParameterError

# Use the simulated descriptor from “Working with Benches”.
try:
    with pytestlab.Bench.open("bench.yaml") as bench:
        # This might raise InstrumentParameterError if 6.0 is out of range,
        # or SafetyLimitError if it exceeds a safety limit.
        bench.psu.set_voltage(1, 6.0)
except InstrumentConnectionError as e:
    print(f"Failed to connect: {e}")
except InstrumentParameterError as e:
    print(f"Invalid parameter: {e}")
except SafetyLimitError as e:
    print(f"Safety violation: {e}")
except Exception as e:
    print(f"Unexpected error: {e}")
```

---

### Use context managers for Cleanup

`Bench` and `MeasurementSession` are regular context managers. Use `with` for cleanup even if an error interrupts the body. A successfully opened experiment bench can run its configured post-experiment hooks on close. A lazy bench opened with `start_experiment=False` does not run those hooks.

```python
from pytestlab import Bench


def safe_operation():
    try:
        with Bench.open("bench.yaml") as bench:
            # ... your code ...
            pass
    except Exception as e:
        print(f"Operation failed: {e}")
    # Instruments are closed automatically here
```

---

### Debugging Tips

- **Check addresses:** If you get a connection error, verify the instrument address in your config.
- **Consult datasheets:** If you get a parameter error, check the instrument's manual for valid ranges.
- **Enable logging:** PyTestLab uses Python's `logging` module. Increase the log level for more detail.
- **Validate configs:** Use the CLI (`ptl profile validate` or `ptl bench validate`) to catch configuration errors early.
- **Use simulation:** Develop and debug with simulated instruments to avoid hardware risks.

---

## Further Reading

- [API Exception Reference](../api/errors.md)
- [Simulation Guide](simulation.md)
- [Bench Descriptors & Safety Limits](bench_descriptors.md)

---
