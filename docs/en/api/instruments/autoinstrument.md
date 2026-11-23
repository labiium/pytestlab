---
title: AutoInstrument
description: Factory API for constructing PyTestLab instrument drivers from profiles and configuration.
---

# AutoInstrument

Use one normal instrument for both discovery and execution:

```python
from pytestlab import AutoInstrument

instrument = AutoInstrument.from_preset("keysight/EDU34450A", simulate=True)
try:
    options = instrument.list_operation_options("measure", "function")
    selected = next(option["value"] for option in options if option["value"] == "dc_voltage")
    result = instrument.measure(selected, uncertainty=False)
finally:
    instrument.close()
```

Construction validates the profile, selects the driver, and initializes its
normal Python state and facades. Discovery reads that metadata. The first I/O
operation allocates and connects the configured backend; discovery and closing
an unused instrument do not create hardware or simulator resources. There is no
separate metadata-only instance or discovery mode.

Use `from_preset()` for packaged keys and `from_file()` for local files.
`from_config()` also accepts mappings, validated configurations, and profile
overrides, retaining its existing local/CDN profile lookup. Explicit custom
driver and backend overrides keep their ordinary semantics.

Driver constructors initialize Python state only. Custom drivers should pass
the supplied backend through to their base class and perform I/O in operations,
not during construction. Backend settings and identity are captured when the
factory is called; deferring allocation does not change which instrument was
requested. Bench-scoped runtime resources remain shared, not copied.

`Bench.open()` validates the bench and owns cleanup. The default experiment
session can connect devices and run configured hooks. To open lazily without
experiment hooks, use `Bench.open(..., aliases={"dmm"}, start_experiment=False)`
and replace `dmm` with the bench alias you intend to use.

::: pytestlab.instruments.AutoInstrument
