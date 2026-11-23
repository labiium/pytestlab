# Profile-driven probers

`GenericProberDevice` exposes native prober actions while keeping every wire
command in the selected profile. The public methods are `contact()`,
`separate()`, `move_to_align()`, `align()` (only for profiles that declare a
genuine alignment action), `move_to_load()`, `set_vacuum(enabled)`, and
`configure_chuck(overtravel, auto_z, interlock, edge_sensor)`.

The boolean arguments are strict booleans. In particular,
`interlock=True` engages the chuck interlock and `False` explicitly bypasses
it; integers and truthy objects are rejected before the backend connects.

The profile's `motion.commands` block owns the native keys. Auxiliary actions
are not exposed as opaque `operation("...")` calls, so a second protocol can
implement the same API by changing only YAML templates.

For an initial read-only check over LAMB, first replace the example host and
GPIB address with the intended controller's canonical resource. The following
queries contact the controller but do not request movement:

```python
from pytestlab import AutoDevice

prober = AutoDevice.from_preset(
    "suss/PA200",
    address_override="GPIB0::1::INSTR",
    backend_spec_override={"type": "lamb", "url": "http://lamb-host:8000"},
    simulate=False,
)
try:
    print(prober.get_position())
    print(prober.get_status())
    print(prober.read_status_byte())
finally:
    prober.close()
```

The PA200 profile declares `transport.write_termination: null` for exact
EOI-only command packets and CRLF for replies. LAMB must advertise
`write_termination`, `query_delay_ms`, and `resource_timing_policy` support;
required framing and timing fail before instrument I/O on an older server.
An explicit backend `url` overrides the profile's legacy `lamb_url` and the
`LAMB_SERVER` environment fallback. Framing keys and suffixes are validated
before connection, and server capabilities are checked again after reconnect.

PA200 command acknowledgements are not physical completion evidence. Its
profile therefore does not advertise `wait`, contact/vacuum readbacks, or a
settled state. `38` is exposed as `move_to_align()`: it is a move to alignment
height/preset, not an automatic wafer/probe alignment operation. `align()` is
not advertised by PA200. `get_contact_state()`, `get_vacuum_state()`, and
`get_settled_state()` fail before I/O unless the profile declares an explicit
mapped query. Use `preflight_recipe()` when a multi-step recipe needs to
check its declared actions and readbacks without connecting. Vacuum is
checked only when a recipe explicitly includes `set_vacuum`.

## Prober CLI

The shared `ptl motion` group handles position, motion and status. The
primary prober commands are `ptl prober contact ALIAS` and
`ptl prober separate ALIAS`. Both can actuate hardware. These commands
and the advanced commissioning routes below use typed methods on
`GenericProberDevice`, not arbitrary profile command names.

```bash
# Optional: inspect the profile without connecting.
ptl prober capabilities prober --json --bench bench.yaml
```

The following are command names for commissioning, not a sequence to run.
Contact, separation, height changes, vacuum, and chuck configuration can
change physical state. Check the selected station and its interlocks first.
Use each subcommand's `--help` for its flags, and supply an explicit on/off
choice for every chuck setting.

| Purpose | Subcommands under `ptl prober` |
| --- | --- |
| Change probe or chuck position | `contact`, `separate`, `move-to-align`, `move-to-load` |
| Set vacuum or chuck options | `vacuum`, `configure-chuck` |
| Read physical state if mapped by the profile | `contact-state`, `vacuum-state`, `settled-state` |

`capabilities` and `preflight` use the selected alias without connecting its
backend. Action and readback methods connect lazily when their typed method
requires I/O. Each command scopes bench initialization to its alias and skips
pre- and post-experiment automation hooks. `preflight` is static: omitting
`--required` checks the full automated recipe, including explicit contact and
settled readback declarations. Pass one or more `--required ACTION` options
to check specific actions; including `set_vacuum` also requires its mapped
readback. These diagnostics do not verify physical state or gate ordinary
single actions.

`--wait` is accepted by action commands but only works for a profile that
declares completion verification. PA200 acknowledges commands without a
settled-state readback, so its `--wait` action is rejected before sending the
command.

The PA200 profile currently declares the API frame as `machine`. Its wire
`H` suffix is a controller command token; it is not treated as evidence that
the controller's saved/manual home has been machine-coordinate calibrated.
For MoveChuck command `34`, the manual defines `H` as absolute from home, `Z`
as absolute from zero, `C` as absolute from center, and `R` as relative from
the current position. The PA200 profile declares `relative_from_position: [x, y]`
and does not send the native `R` command. PyTestLab reads the XY position from
the same controller home reference, converts it to millimetres, adds the
requested offsets, and checks the final XY target against the configured
position limits. An omitted X or Y axis stays at its reported position.
If a valid target cannot be computed, no move command is sent. A valid
target is sent with `34 ... H`.

The read and move are serialized within this PyTestLab process. That does not
prevent movement by another process or at the controller, verify clearance,
or replace physical interlocks. The profile's limits are configured software
limits, not detected physical stops. Both absolute and relative moves require
a commissioned home reference, clearance and controller travel limits.
See the [ProberBench 4 User Manual, Remote Interface, MoveChuck command](https://wiki.epfl.ch/carplat/documents/ProberBench_4_User_Manual_Remote_Interface.pdf).

## API reference

::: pytestlab.prober.GenericProberDevice
