# Profile-driven operation discovery

## Status

The operation contract is profile-owned and shared by Python and the CLI.
Normal user workflows are semantic: callers discover values from the loaded
profile and pass those values to ordinary instrument methods. Private command
aliases, placeholders, tokens, and rendered messages are not returned by public
discovery.

## Public Python workflow

```python
from pytestlab import AutoInstrument

instrument = AutoInstrument.from_config("keysight/EDU34450A")

operations = instrument.list_operations()
description = instrument.describe_operation("measure")
functions = instrument.list_operation_options("measure", "function")

function = functions[0]["value"]
ranges = instrument.list_operation_options(
    "measure",
    "range_val",
    context={"function": function},
)
result = instrument.measure(function=function, range_val=ranges[0]["value"])
```

There is one lifecycle. `AutoInstrument.from_config(...)` constructs the normal
instrument lazily; discovery does not allocate or connect a backend. There is no
metadata-only constructor, `_offline` mode, public resolver, or enum requirement.

## Public CLI workflow

```bash
ptl instrument list-operations keysight/EDU34450A
ptl instrument describe-operation keysight/EDU34450A measure
ptl instrument list-options keysight/EDU34450A measure function
ptl instrument list-options keysight/EDU34450A measure range_val \
  --context '{"function":"dc_voltage"}'
```

JSON is the default output. Interactive terminals syntax-highlight it; pipes and
redirection receive plain valid JSON. There is no redundant `--json` switch.

## Profile contract

- Static Python descriptors identify the public method, safety class, capability
  gate, and whether the operation is required.
- YAML `operation_options` owns semantic parameters, dependencies, constraints,
  defaults, private command mappings, and parameter bindings.
- Explicit semantic-to-transport mappings are required. Identity mappings must
  be opted into explicitly; missing mappings never fall back to raw values.
- Models reject unknown fields and malformed bindings.
- DMM `measurement_functions` remains profile capability data and is adapted by
  the shared resolver for function-dependent ranges and resolution.
- Public descriptions serialize semantic data only.

## Diagnostics

Two explicit diagnostics are retained:

- `check-commands` builds and validates every private profile command mapping.
- `full-test` runs command checks and then exercises supported public semantic
  operations against live hardware. Add `--include-writes` to run writes,
  which can change output or instrument settings.

These commands are maintenance/hardware diagnostics. Their transport detail is
not part of normal discovery.

## Acceptance criteria

- [x] Every advertised supported value is accepted by the ordinary public method.
- [x] Python and CLI discovery use the same profile-backed resolver.
- [x] Discovery works without backend creation, connection, simulation, or I/O.
- [x] Missing operations, mappings, dependencies, and constraints fail explicitly.
- [x] Public discovery contains no private command data.
- [x] AWG, DMM, oscilloscope, PSU, load, power-meter, spectrum, VNA, and virtual
  profiles use the canonical operation schema.
- [x] `check-commands` and `full-test` remain available with guarded writes.
- [x] Generated legacy schema churn is excluded from this change set.
- [ ] Re-run external discovery-ranking benchmarks when the benchmark environment
  is available; this does not affect runtime correctness.
