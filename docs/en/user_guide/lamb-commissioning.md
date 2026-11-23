# LAMB station commissioning

`examples/lamb_bench.yaml` shows instrument addresses and an explicit camera address placeholder. Before using it, replace the host, confirm the instrument addresses, and copy the intended camera's complete resource string from `ptl camera discover` into the `microscope` entry's `address`.
It declares no fixture routes, source cards, or automated experiment hooks.
Supply qualified channel ratings, DUT limits, and wiring before electrical tests.

```bash
export PYTESTLAB_BENCH=/absolute/path/to/examples/lamb_bench.yaml
ptl prober capabilities prober --json
ptl motion position prober --json
ptl motion status prober --json
ptl device status-byte prober --json
ptl camera list --json
ptl camera capture microscope /tmp/prober-view.jpg
```

The capability listing is optional and does not connect to the prober.
CLI device sessions skip experiment hooks and database startup.
Position, status, and status-byte are live reads of the named resource.
`camera list` reports declarations only; `camera capture` connects to the named camera.

For this ToupTek SDK example, configure the LAMB server for your camera model.
The exact configured resource string must appear in its camera inventory; see
[Cameras through LAMB](../api/camera-lamb.md). Image timestamps are client receipt
times, not calibrated sensor timestamps.

Before testing movement, establish probe separation, clear travel, and a safe
axis/displacement. Record the controller position and camera image before the
move, then collect images and position readings during and after it. Track
sample features relative to the probe tips. A command acknowledgement alone
does not establish motion or settling. Do not use `--wait` with PA200 until
qualified completion observations exist.

The full probing recipe remains unavailable until these are qualified:

- PA200 coordinate references and contact, vacuum, and settled readbacks.
- Installed 4142B channel IDs, ratings, and physical output/quiescence observations.
- Fixture wiring and matrix connection-state decoding.
- DMM uncertainty/calibration metadata, if uncertainty estimates are required.

Keep unsupported observations absent from profiles. Populate state maps only
with documented queries and observed response tokens; unknown data must fail.
