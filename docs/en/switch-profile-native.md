# Profile-defined switching

`SwitchMatrixDevice` applies routes. A native `switch` profile declares the
crosspoint grammar, limits and commands for a non-SCPI controller.

## Use the HP4084B

Try the [fake-transport example](https://github.com/labiium/pytestlab/blob/master/examples/native_capabilities_offline.py)
from a source checkout without hardware. For a configured `hp/HP4084B`, declare
a route using your actual fixture map, then [preview it](cli.md#inspect-a-measurement-plan)
with `ptl bench route bench.yaml measurement` before applying it.

Take connected sources to zero and let them settle before switching. Check
the fixture and interlocks at the station. With a prepared bench open:

```python
bench.route("measurement").apply()
```

The adapter validates commands before the first write. It cannot verify
continuity or relay state; the HP profile has no decoded route readback.
See [Keysight IC-CAP, Matrix Drivers](https://edadownload.software.keysight.com/eedl/iccap/2012_01/pdf/measurement.pdf#page=72).

## Native profile schema

This synthetic profile describes commands, not fixture wiring:

```yaml
manufacturer: example
model: profile-switch
device_type: switch_matrix
terminals: [source, dut]
channels: []
switch:
  crosspoint:
    pattern: '^P(?P<port>[1-6]|[89]|10):(?P<pin>[0-9]+)$'
    fields: [port, pin]
    constraints: {pin: {min: 1, max: 48}}
  commands:
    connect: 'PC{port}ON{pin:02d}'
    open: 'PC0ON{pin:02d}'
    clear: 'CL'
    identity: 'ID'
```

`matrix.identity()` and `matrix.read_status_byte()` require their corresponding
I/O capabilities. Profiles without `switch` retain the legacy `ROUTE:*`
fallback. Optional `switch.requires_context` values are caller assertions,
not readings. Route paths belong to the bench, not the profile.

Native switches share `ProfileTransport` with motion devices. Configure
`message_io.read_termination` (including null), `min_command_interval_s`
(completion to next start), and `query_delay_s` (write to read) as needed.
Required acknowledgements are nonempty and consumed before the next command.
Use `success_token`, full-match `success_pattern`, or legacy `success_prefix`.
Identity text is not an action acknowledgement or native bus status.

`matrix.open_all()` disconnects routes without closing the session. Exclusive
clear and subsequent writes share one lock; local route state is invalidated
before a partial change can occur. `settling_time_s` is a local wait.
