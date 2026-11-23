# Using a camera or microscope

A microscope camera is a camera device. Use its exact LAMB resource to save preview frames directly from Python, or bind it to a Bench alias for the CLI and shared setups. Focus knobs, objective turrets, XY stages, and illumination controllers are separate devices unless their hardware exposes those capabilities through its own backend.

## Discover cameras

For cameras exposed by a LAMB server, replace `your-lamb-host` with the camera server’s hostname, then list its resources:

```bash
export LAMB_SERVER=http://your-lamb-host:8000
ptl camera discover
```

Copy the complete `resource_string` reported for the desired camera. Keep it as-is, including any USB port or SDK identifier. A port-based address changes when you move the camera to a different port.

## Capture directly from Python (no Bench file)

For the packaged ToupTek example, use its profile and the complete resource
string from discovery. Replace both placeholders with your station's values:

```python
from pytestlab import AutoDevice

camera = AutoDevice.from_preset(
    "touptek/E3CMOS12000KPA",
    address_override="<exact resource_string from discovery>",
    backend_spec_override={"type": "lamb", "url": "http://your-lamb-host:8000"},
)
try:
    camera.capture().save("microscope-preview.jpg")
finally:
    camera.close()
```

If the configured address is not in the server's camera inventory, capture
fails rather than choosing a different camera.

## Select a camera in `bench.yaml`

Save this as `bench.yaml`. Copy the exact `resource_string` for the intended
camera into `address`, even when only one camera is attached. The alias names
the configured device; it does not select from the server's inventory.

```yaml
bench_name: Microscope camera
devices:
  microscope:
    device_type: camera
    address: "<copy the complete resource_string from ptl camera discover>"
    backend:
      type: lamb
```

To inspect configured cameras or their available capture settings, optionally run:

```bash
ptl camera list --json
ptl camera info microscope
```

## Capture a preview

Save one image to a path you can open locally:

```bash
ptl camera capture microscope /tmp/microscope-preview.jpg
```

For a series, provide a directory and capture interval:

```bash
ptl camera capture microscope /tmp/preview-series --count 5 --interval 0.5
```

Open the resulting image with your image viewer. These examples connect to a physical camera. Capture output is a saved frame, not an interactive live video stream. Supported resolution and camera settings depend on the camera and server.

Python applications can capture through the same alias:

```python
from pytestlab import Bench

with Bench.open("bench.yaml", aliases={"microscope"}, start_experiment=False) as bench:
    frame = bench.microscope.capture(width=640, height=480)
    frame.save("microscope-preview.jpg")
```

`Frame` includes dimensions and content type. You can save a JSON sidecar with `frame.save("preview.jpg", metadata_path="preview.json")` when you need capture metadata alongside the image.

## Focus, stage, and microscope control

Camera capture does not move a microscope stage or change focus. Configure a supported stage or motion controller as its own device and use the motion API for its declared axes and capabilities. For example, query position and status before choosing a target, and use the controller's documented units and limits. `home()` may run a physical reference cycle, so use it only when you intend to move the mechanism.

Likewise, illumination and objective selection require a backend that exposes those controls. A camera alias alone does not imply that PyTestLab can control those parts of the microscope.

For camera resource details, see [Cameras through LAMB](../api/camera-lamb.md). For camera and motion APIs, see [Cameras, motion, and robots](camera-motion.md).
