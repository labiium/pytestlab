---
title: Operation discovery contract
description: Shared semantic operation discovery and resolution models.
---

# Operation discovery contract

Instrument profiles describe semantic operation values independently of their
private transport spelling. Discovery is available without a backend:

```python
from pytestlab import AutoInstrument

instrument = AutoInstrument.from_preset("keysight/EDU34450A", simulate=True)
options = instrument.list_operation_options("measure", "function")
selected = next(option["value"] for option in options if option["value"] == "dc_voltage")
```

Discovery does not allocate or connect a backend. The same fully initialized
instrument executes `instrument.measure(function=selected)` when ready; its
normal backend settings determine whether it uses hardware or simulation.
The example explicitly uses simulation. Callers do not need to import a concrete
driver or construct a second object. Close the instrument when finished.

Use `describe_operation()` for parameter kinds, defaults, units, constraints,
dependencies, and support reasons. Dependent parameters require context:

```python
instrument.list_operation_options(
    "measure", "range_val", context={"function": "dc_voltage"}
)
```

The same profile-backed resolver validates execution inputs and measurement-plan
selections. Public option records contain `value`, `label`, aliases, and other
semantic metadata. Private transport tokens, aliases, and rendered commands are
never part of the public discovery contract.

Missing metadata is reported as unsupported or as a structured
`OperationDiscoveryError`; it is never interpreted as an unrestricted range or
an empty supported enum. Capability support is also independent of uncertainty
availability.

## Browse supported capabilities

Use `describe_operations()` to browse a profile without issuing commands or
allocating a backend. It returns a dictionary of semantic group IDs to lists of
regular operation descriptions:

```python
instrument.describe_operations(include_unsupported=False)
instrument.describe_operations(group="general", scope="family")
```

Unannotated groups go in `general`. A `family` operation belongs to a shared
device-type API; a `model` operation is a model-specific extension or is
defined by the generic profile driver. Unclassified operations are included
when no scope is selected. Scope does not imply standards compliance or support
on every model. `support` describes what this profile exposes, not bench
verification; source `references` are optional profile documentation.
Use `describe_operation(..., context=...)` for conditional parameters.

Call `python_only` operations through their typed methods, not
`execute-operation` or `full-test`. The optional `python_arguments` list
documents required Python objects when present. Discovery neither builds
these from JSON nor verifies live conditions.

## Compatibility and completeness

`OperationDescription`, `OperationParameterDescription`, and `OperationOption`
define the shared output.
Older profile sections such as DMM `measurement_functions` are adapted internally
to that same contract; they do not require a separate DMM discovery API.

Inspect support in the same dependency context used for execution. A required
callable argument with unresolved metadata makes the operation unsupported.
Optional settings can be unavailable while the operation remains usable without
them. For example, a profile's no-argument diode measurement cannot accept a
generic range or resolution setting: omit those arguments rather than passing
`AUTO` or `DEF`.

Python operation descriptors name the public method, safety classification,
capability gate, and requiredness. They can also declare a semantic `group` and
discovery `scope`. A profile may set its own group and supply a description
and source references. Parameter semantics and all private command bindings
live in the profile. The selection workflow therefore
uses discovered values directly and never requires an enum import or a separate
resolver call. Missing profile metadata fails explicitly rather than falling
back to a driver-side command assumption.

::: pytestlab.instruments.operation_contract.OperationDescription

::: pytestlab.instruments.operation_contract.OperationOption

::: pytestlab.instruments.operation_contract.OperationParameterDescription
