# Cameras, motion, and robots

PyTestLab exposes cameras, stages, gantries, and robots as ordinary devices
with capability-specific APIs. The APIs are transport- and vendor-neutral:
the same Python call can be backed by a USB camera, a network microscope, a
serial stage, a GCS controller, or a typed simulator. No agent or application
runtime is part of these interfaces.

## Camera capture

A camera driver subclasses `pytestlab.camera.Camera`, or provides a backend
with `capture()` and/or `capture_to(path)`. The two backend surfaces are
independent; a camera does not have to hold the entire image in memory.

```python
from pytestlab import Camera

frame = camera.capture(exposure_ms=5)
print(frame.width, frame.height, frame.content_type)
frame.save("/tmp/view.png", metadata_path="/tmp/view.json")
```

For repeated captures, preflight all destinations and keep one connection
open:

```python
results = camera.capture_many(
    [f"/tmp/series/frame-{index:06d}.png" for index in range(1, 101)],
    interval_s=0.05,
    metadata=True,
)
```

`capture_sequence()` is the convenience form for a numbered directory. Image
and metadata files are written through same-directory temporary files and
published without clobbering existing files unless `overwrite=True` is
explicitly selected. The two published files are individually atomic; a
filesystem cannot provide a multi-file transaction.

For LAMB cameras, copy the desired resource string from `ptl camera discover` into the bench entry's explicit `address`. Discovery is inventory, not camera selection. The CLI keeps the common path short:

```bash
# Select the configured alias and the output path
ptl camera capture microscope /tmp/view.png

# Capture a numbered series into a directory
ptl camera capture microscope /tmp/series --count 100 --interval 0.05

ptl camera list --json
ptl camera info microscope
```

The explicit `--bench PATH` option remains available. Resolution order is
explicit path, `PYTESTLAB_BENCH`, then the nearest `bench.yaml` or
`bench.yml` ancestor.

CLI device commands use lazy sessions without experiment hooks or database
startup. Motion commands select their named resource; camera commands load
camera resources and connect only the camera being captured. Python callers
can request the same lifecycle with
`Bench.open(path, aliases={"prober"}, start_experiment=False)`.

## Generic motion

`MotionDevice` models axes rather than a product family. A backend may declare
axis limits, units, axis groups, and coordinate frames through
`MotionCapabilities`:

```python
from pytestlab import CoordinateFrame, MotionDevice

stage.move_absolute(
    x=12.5,
    y=-3.0,
    z=0.1,
    frame=CoordinateFrame("machine"),
    units="mm",
    wait=True,
)
stage.move_relative(x=0.25, units="mm", wait=True)
stage.home(wait=True)  # Run the controller's physical reference cycle.
stage.set_home(axes=("x", "y"))  # Save the current position as the home origin.
stage.move_home(axes=("x", "y"), wait=True)  # Return to that saved origin.
print(stage.position, stage.status)
```

These three operations have different meanings: `home()` runs a controller's
reference cycle and may physically move until limit or reference sensors are
found; `set_home()` records the current position as a saved origin and does
not run a reference cycle; `move_home()` returns to that saved origin. The
last two operations are optional controller capabilities, so unsupported
devices report an explicit capability error. Absolute and relative moves
accept either the existing mapping form (`{"x": 1.0}`) or axis keywords such
as `x=1.0, y=2.0`, but do not mix the two forms.
For profiles with bounded axes, validating an offset alone cannot verify
the destination. A profile can opt into relative movement with
`motion.relative_from_position` when it declares the axes to read and an
absolute move in the same coordinate frame. PyTestLab checks the computed
final coordinates against the configured limits before sending the absolute
move. Without that declaration, relative moves on bounded axes are rejected.
See the [PA200 example](using_prober.md#relative-xy-moves). These checks do
not discover physical travel limits or establish clearance.

Every mutating call returns a `MotionResult` with an operation ID, requested
target, state, optional actual position, and error details. `MotionStatus`
normalizes settled, homed, enabled, target-reached, and fault information.
When a controller supplies operation IDs, `wait_operation()` correlates the
wait with the issued operation instead of accepting a stale settled response.

The shared motion commands take the alias from the bench:

```bash
ptl motion position stage
ptl motion status stage --json
ptl motion move --help
```

Use `axis=value` coordinates for `move` and confirm units, travel, and interlocks first. Extra commands such as `home` and `jog` remain available at the root for compatibility; exact support depends on the profile.

`stop` and `abort` are controller operations, not safety-rated emergency-stop
circuits. The machine safety system remains external to PyTestLab.

The generic fallback for a raw text backend preserves the historical
`MOVE ABS`/`MOVE REL` command prefixes for compatibility. It is a transport
fallback, not a claim that those strings are a universal vendor protocol.
Native drivers should implement the optional typed `motion_command`,
`motion_query`, and `wait_operation` hooks and translate them to the chosen
controller's programming guide.

## Robots and high-level tasks

`RobotDevice` adds arbitrary joint, pose, and trajectory spaces to the same
motion foundation:

```python
robot.move_joints({"j1": 10.0, "j2": -2.0}, wait=True)
robot.move_pose(
    {"x": 10.0, "y": 5.0, "orientation": [0, 0, 0, 1]},
    frame="base",
    units="mm",
)
robot.execute_trajectory(
    [{"j1": 0.0, "j2": 0.0}, {"j1": 10.0, "j2": -2.0}],
    space="joint",
    wait=True,
)
```

The device layer intentionally stops at motion primitives and trajectory
execution. Application-specific tasks, planning, collision checking, and
cell recipes should be separate code that composes these primitives. This
keeps arbitrary robot vendors interoperable and prevents a microscope or
wafer stage from being forced into a robot-specific hierarchy.

## Backend boundaries

`DeviceBackend` contains only lifecycle methods (`connect`, `disconnect`, and
`close`). Raw `write`, `query`, and `query_raw` belong to `DeviceIO` and are
not required by camera or typed-motion backends. This allows capability-only
devices to remain free of SCPI/PyVISA assumptions while preserving the raw
instrument API for devices that genuinely need it.


## Profile-defined controller protocols

`ProfileMotionDevice` implements the same `MotionDevice` API and generic CLI
for controllers that use SCPI, arbitrary ASCII, or compact numeric commands.
The profile defines the protocol; application code uses capability methods:

```python
from pytestlab import AutoDevice

prober = AutoDevice.from_preset(
    "suss/PA200",
    address_override="GPIB0::1::INSTR",
    backend_spec_override={"type": "lamb"},
)
try:
    position = prober.get_position()  # millimetres
    status = prober.get_status()
    status_byte = prober.read_status_byte()  # native bus operation
finally:
    prober.close()
```

Connection details belong to the bench, so the same resource can be used by
`ptl motion position prober --json` and `ptl motion status prober --json` without exposing
wire commands. `ptl device status-byte prober --json` reads the shared native
bus-status capability and works for instruments and matrices as well. These
calls perform physical reads when used with a real backend.

The packaged PA200 profile uses the compact ProberBench protocol from the
existing station driver. Its `motion` section declares XY axes in mm, wire
scaling to micrometres, the `31` position/status query, the `34` movement
commands, CRLF text termination, 100 ms command spacing, and a 100 ms delay
between query write and read. Exchanges through one profile backend are
serialized so concurrent callers cannot defeat its pacing.

Profiles may specify `success_token`, `success_pattern` (a full regular
expression match), or the legacy `success_prefix`. Required query responses
must be nonempty. Token `0` is matched as a whole whitespace-delimited token,
so `01` and `0bad` are rejected. A query is transmitted once, not as a separate
write followed by another query.

A successful acknowledgement produces a running `MotionResult`. A command may
explicitly declare `result_state: succeeded` only when its protocol guarantees
physical completion before replying. The PA200 profile does not make that
claim: its status preserves an unknown settled state after a successful
position transaction, and `wait` is not advertised. Its Z contact/alignment/
separation/load actions remain secondary profile operations rather than a
continuous Z axis; reset is not declared.

The `supports` list is exact; an explicit empty list disables every operation.
When omitted, support is inferred from implemented command/query names.
Units, frames, axis groups and axis limits are profile declarations, and
unsupported requests are rejected rather than silently passed through.
Profiles should declare their API units explicitly alongside per-axis units;
`wire_scale` and response `scale` define the matching protocol conversion.
The internal template renderer retains its historical `SCPIEngine` name,
but neither the templates nor this API require SCPI syntax or query markers.

Offline validation uses fake transports, including a second unrelated ASCII
protocol, and does not establish physical qualification of a powered station.


Positive write-to-read delays through LAMB require a server advertising
`query_delay_ms: true` at `GET /capabilities`. This capability currently applies
to native GPIB resources. The SDK checks it before sending a delayed command;
an older server fails explicitly rather than ignoring the timing parameter.
The existing text `/health` response is unchanged. Zero-delay calls keep their
existing behavior. Native server source support must be installed separately
before these profile delays can be used with an older running server.
