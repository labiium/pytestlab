# Cameras through LAMB

Cameras use the generic Camera API and the standard LAMB backend. No manufacturer profile is required, but each camera needs an explicit resource address.

Set the server once, then list its camera resource strings. Discovery reports inventory; it does not open or select a camera:

```bash
export LAMB_SERVER=http://your-lamb-host:8000
ptl camera discover
```

Copy the complete `resource_string` for the intended camera into `address`:

```yaml
bench_name: Camera bench
devices:
  camera:
    device_type: camera
    address: "<copy the complete resource_string from ptl camera discover>"
    backend:
      type: lamb
```

A missing address is rejected before contacting the server, whether zero, one,
or many cameras are attached. When opening a configured camera, PyTestLab checks
for that exact resource. If it is missing or ambiguous, the connection fails
rather than falling back to a different camera.

```python
from pytestlab import Bench

with Bench.open("bench.yaml", aliases={"camera"}, start_experiment=False) as bench:
    frame = bench.camera.capture(width=640, height=480)
    frame.save("capture.jpg")
```

Discovery identifies USB cameras by their physical USB port, retaining serial metadata when available. This avoids treating duplicated manufacturer serials as unique. SDK cameras use their SDK identity; devices without stronger identity are marked ephemeral. A port-based address follows the port, not a camera moved to a different port. Copy the entire resource string without interpreting or constructing it yourself.

An explicit backend `url` overrides `LAMB_SERVER`; absent both, the default is `http://lamb-server:8000`. Direct factory callers can use `address_override`, or explicitly supply the same resource in backend `resource_string`. Conflicting values are rejected.

**Migrating an addressless camera configuration:** Run `ptl camera discover --json`, copy the intended camera's exact `resource_string`, and set the device's `address`. No change to the bench alias or capture code is required. If a USB camera is moved to another port, rediscover and confirm the new address before updating it.

Only the selected camera is opened for the capture; experiment hooks are disabled.
Capture returns a JPEG; supported dimensions depend on the device and server. This does not imply native JPEG sensor output or a universal maximum resolution. Instrument profiles and SCPI access remain unchanged. This client requires the matching resource-string camera discovery server, not the earlier camera-ID API.

## API reference

::: pytestlab.config.camera_config.CameraConfig
