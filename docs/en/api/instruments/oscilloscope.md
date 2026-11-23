---
title: Oscilloscope
description: PyTestLab oscilloscope acquisition, trigger, channel, waveform, and analysis API.
---

# Oscilloscope

Configure channels and triggers, acquire waveform data, and work with measurement uncertainty.

## Run a hardware self-test

Disconnect the front-panel inputs before running this service diagnostic.
Use a clean, exclusive connection and allow a few minutes.

```python
print(bench.scope.run_self_test())  # "Passed", or a failure message
```

Supported Keysight profiles: DSOX1202G, DSOX1204G, DSOX3054G, MSOX2024A,
HD304MSO, and MXR404A. Each profile maps the inherited Python method to
the native `*TST?` query with a four-minute communication timeout for the
test. It leaves existing error-queue entries untouched, and bulk diagnostics
do not run it. If communication fails, check the
instrument and clear its interface before reconnecting or retrying.

Keysight command references:
[1200 X, p. 140](https://www.keysight.com/by/en/assets/9018-07747/programming-guides/9018-07747.pdf#page=140),
[3000G, p. 235](https://www.keysight.com/ng/en/assets/9922-01537/programming-guides/InfiniiVision-3000G-X-Series-Oscilloscopes-Programmers-Guide.pdf#page=235),
[2000 X, p. 162](https://www.keysight.com/cd/en/assets/9018-06893/programming-guides/9018-06893.pdf#page=162),
[HD3, p. 263](https://www.keysight.com/gb/en/assets/9924-01795/programming-guides/InfiniiVision-HD3-Series-Oscilloscopes-Programmers-Guide.pdf#page=263),
and [MXR, p. 270](https://www.keysight.com/bf/en/assets/9018-18183/programming-guides/9018-18183.pdf#page=270).

## Channel bandwidth limit

Bandwidth values are profile-specific. For the Keysight DSOX1204G profile, use
`"25M"` (or `25e6`) to enable its 25 MHz low-pass filter, and `"FULL"` to
disable that filter. The MXR404A profile supports `"20M"`, `"200M"`, and
`"FULL"`:

```python
scope.channel(1).setup(bandwidth_limit="FULL")
```

`"FULL"` is translated to the instrument's documented filter-off command. A
bandwidth value not listed by the loaded profile raises
`InstrumentParameterError` before a command is sent. Use
`scope.describe_operation("bandwidth_limit")` to inspect the available values.

## Channel vertical scale

`set_channel_axis()` validates the requested volts-per-division against the
scope's current probe attenuation and input impedance before applying settings.
`describe_operation("channel_axis")` exposes the
profile's contextual ranges; pass `probe_attenuation` and `input_impedance` in
`context` to see the active limits. For example:

```python
scope.describe_operation(
    "channel_axis",
    context={"probe_attenuation": 10, "input_impedance": 50},
)
```

The DSOX1204G connector limits at 1:1 are 0.0005–10 V/div. The MXR404A 1:1
limits depend on its selected input: 0.001–1 V/div at 50 Ω and 0.001–5 V/div
at 1 MΩ. For either instrument, the driver multiplies those limits by the live
probe factor, so supported factors such as 0.1:1, 2:1, 3.2:1, and 10:1 do not
need to appear in a fixed option list. The driver queries current probe
attenuation and the MXR input selection for each write; it fails before writing
if a required context value cannot be read or is invalid. Other profiles retain
their declared validation behavior.

Offset limits also depend on scale. On the DSOX1204G and MXR404A, the driver
validates the complete requested axis, neutralizes a nonzero offset before a
scale change, and reads the effective scale before sending a nonzero offset.
The instrument may round the scale. If that rounding makes the requested offset
invalid, Python raises `InstrumentParameterError` without sending that offset;
the valid scale change can remain applied. The operation is therefore not an
atomic rollback transaction. Combined channel setup validates the requested
probe and impedance context before applying it, including MXR 50 Ω transitions.

Horizontal scale uses seconds per division; acquisition duration uses the full
ten-division range. The qualified MXR404A limits are 5 ps–20 s/div and 50 ps–200 s
for the full range; the connected DSOX1204G accepts 2 ns–50 s/div and 20 ns–500 s
for the full range. Position bounds use the profile's qualified context, with effective
scale readback. An incompatible retained delay is reset to zero when changing
acquisition duration. DSOX XY mode rejects unavailable timebase operations before
writes. DSOX window/roll position bounds are not qualified by these profiles.

The DSOX1204G waveform reader also selects a transfer record compatible with
the current acquisition type. Average and peak acquisition retain their
acquisition settings and use the normal waveform record; normal and high
resolution acquisition retain the raw-record transfer path.

On profiles that declare channel-display state handling, `read_channels()`
restores the requested channels' prior display state after controlled digitize,
including when waveform retrieval raises an error. Other scope profiles keep
their existing acquisition behavior.

## Waveform point count

`acquire_waveform(1, points=2000)` and `read_channels(1, points=2000)` request
the count on the instrument. The DSOX1204G controls transfer decimation after
selecting the waveform record; its normal record accepts 100, 250, 500, or
1000 points, while its raw record supports additional counts listed by
`describe_operation("waveform_readout")`. The MXR404A sets acquisition depth
before digitize and validates the request against its current device limits.
On the MXR, this is an acquisition-depth request. Enabled interpolation can
produce more exported waveform points than the acquired sample count. The
driver preserves that setting and reports the actual exported count.

`points=None` keeps the existing full-record behavior. Numeric requests require
a profile that declares the control and cannot be used in read-only mode.
The `read_channels()` result's `envelope["waveform_transfer"]` records
`requested_points` and per-channel `effective_points`; `acquire_waveform()`
records them in its acquisition notes and exposes the returned `point_count`.
Instruments can return a different count;
PyTestLab reports that difference and retains the actual data and preamble
time axis. It does not truncate the waveform to manufacture the requested count.

::: pytestlab.instruments.Oscilloscope
    options:
      members:
        - Oscilloscope
