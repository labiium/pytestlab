---
title: Spectrum Analyzer
description: Configure a sweep or zero-span capture, work with traces and markers, and measure channel power, adjacent-channel power, or occupied bandwidth.
---

# Spectrum analyzer

Use the same Python calls for a Keysight N9000A and a Rohde & Schwarz FSW26.
To change vendor, change the profile and address, not the Python measurement.
The example uses a Bench alias. A direct connection with
`AutoInstrument.from_profile(profile, address_override=address)` runs the same
measurement calls without a `bench.yaml` file.

```yaml
bench_name: RF bench
instruments:
  spectrum:
    profile: keysight/N9000A_SA # or rohdeschwarz/FSW26
    address: "TCPIP0::192.0.2.10::inst0::INSTR"
```

## Configure, capture, and find the peak

Connect a passive RF input. Start in **Swept SA** on the N9000A or the
default **Spectrum** channel with one Diagram window on the FSW26.
Use single sweep, with continuous sweep off. The requested trace must already
be active and in **Clear/Write**.
Turn off tracking or external generator control, trace math and normalization,
and the FSW sequencer. Use FSW sweep count 0 or 1 and leave any other
updating Keysight traces in Clear/Write.

```python
from pytestlab import Bench

with Bench.open("bench.yaml", aliases={"spectrum"}, start_experiment=False) as bench:
    sa = bench.spectrum
    ready = sa.prepare_sweep()
    print(ready.trace_mode, ready.transfer_format, ready.display_evidence)
    sa.configure_rf_input(attenuation_db=20)
    sa.configure_sweep_control(trigger_source="free_run")
    sa.configure_measurement(
        center_freq=1e9, span=10e6, rbw=10e3, vbw=3e3, sweep_points=1001
    )
    actual = sa.get_sweep_settings()
    print(actual.center_freq_hz, actual.rbw_hz, actual.sweep_points)

    trace = sa.acquire_trace(timeout_ms=15_000)
    peak = trace.peak()
    print(trace.acquisition)  # "fresh"
    print(peak.coordinate, peak.axis_unit, peak.amplitude, peak.amplitude_unit)
```

`prepare_sweep()` verifies single sweep and switches a compatible analyzer
to ASCII as needed. If you intend to end an ongoing continuous run, use
`prepare_sweep(stop_continuous=True)` instead. The analyzer may need to finish its current sweep
sequence; preparation does not promise to preserve or return pending trace
data. A pending trigger can exhaust the timeout; preparation does not abort it. It checks single-sweep readback, operation completion, and the
documented idle status flags before changing transfer format. It verifies
the selected trace and, on FSW26, the base Spectrum application and sole
Diagram window before and after preparation. On Keysight it selects Normal view and checks command
acceptance, since the programmer's reference does not provide a reliable view
query. `display_evidence` distinguishes these cases. Preparation has one
timeout, waits for pending work and never initiates a measurement. It does not
reset, select another measurement application, alter trace processing or
connector direction, or enable a source. Unsupported retained state is
rejected rather than overwritten; choose the needed application and trace
state explicitly before retrying. A failed readback does not roll back
accepted single-sweep or transfer-format changes.

`configure_measurement` validates all supplied settings before attempting
writes. The three original positional arguments still work; `vbw` and
`sweep_points` are optional keyword arguments. Bandwidth is in Hz. The
analyzer can round or couple settings, so use `get_sweep_settings()` to get
actual readback. Changing settings while continuous sweep is enabled can
restart the analyzer's own sweeping; use single sweep for the sequence above.

`acquire_trace` initiates a new measurement and waits for completion before
fetching. Its timeout budget covers SCPI preflight, acquisition and readback
after connection. The transport must honor its timeout to bound how long
the call blocks; a reply returned after the deadline is rejected. A timeout
does not return an old trace, abort the analyzer,
or retry the sweep. A failed transport exchange or unconfirmed sweep
completion can leave an old reply waiting in the interface. The current
driver instance then refuses further spectrum I/O. Use the instrument or
transport's documented recovery procedure to stop any pending acquisition
and clear unread replies, then close and reopen the bench. Reopening alone
does not guarantee that the instrument's reply queue was cleared.
The Keysight workflow selects the
Normal view so it cannot read an old Spectrogram slice. Acquisition does not reset the instrument, change trigger or transfer
settings, or enable an RF source. Use a single controlling client and avoid front-panel changes
during an acquisition.

Use `get_trace(channel=1)` instead to read what is already held, without
starting a sweep. It reports `acquisition="held"`, not whether the data is
new. Do not change settings after gathering the trace and then interpret the
held samples with the new settings. `channel` is the display trace index,
not an RF input. Both methods return measured coordinates in Hz for a swept
trace or seconds for zero span, with analyzer-reported amplitude units.
`trace.peak()` finds the highest measured bin without interpolation. To
persist a trace, put `x` and `y` into a typed table with their units; see
[session storage](../../user_guide/measurement_session.md#store-a-waveform-or-sweep-with-each-trial).

## Capture multiple traces in one sweep

Set up two or more active, Clear/Write display traces with the desired
detectors, then call `acquire_traces()`. It triggers exactly one sweep, waits
for completion, and reads every requested trace against one timeout.

```python
sa.configure_sweep_control(continuous=False, trigger_source="free_run")
sa.configure_trace(1, mode="clear_write", detector="positive_peak", accumulation_count=1)
sa.configure_trace(2, mode="clear_write", detector="sample")
frame = sa.acquire_traces([1, 2], timeout_ms=15_000)
print(frame.channels, frame.axis_unit, frame.amplitude_unit)
for trace in frame.traces:
    print(trace.trace, trace.peak().amplitude)
```

The elements of `frame.traces` follow the requested display trace order.
`frame.axis` holds instrument-returned frequencies in Hz or zero-span times
in seconds. A mismatched axis, unit, mode, or failed transfer rejects the
whole frame, not just the affected trace. The FSW26 requires the base
Signal and Spectrum operating mode, a single Diagram window at index 1,
and each selected display trace enabled. Keysight switches to Normal view and verifies that all selected
traces are updating. Keep one controlling client and avoid front-panel
changes during capture. For one trace with native average/hold, use
`acquire_trace(accumulation_count=...)` instead.

## RF input, detector, and zero span

Set the amplitude scale to dBm before setting or reading the reference level.
A manual attenuation value disables auto attenuation and may be rounded.
Check the actual state with `get_rf_input()`. The optional internal preamp
is reported as `None` when no known hardware option is installed. Asking
to set the preamp without that option fails before writes. The attenuation
control covers the analyzer's documented RF/mechanical attenuator, not its
optional electronic or external front-end stages. Check the instrument's
input limits before reducing attenuation or enabling the preamp.

```python
sa.configure_measurement(center_freq=1e9, span=0, rbw=100e3, vbw=100e3)
sa.configure_sweep_control(continuous=False, sweep_time_s=2e-3)
sa.configure_external_trigger("external_1", level_v=1.4, slope="rising")
sa.configure_trace(channel=1, mode="clear_write", detector="sample", detector_auto=False)
print(sa.get_external_trigger_settings(), sa.get_sweep_control(), sa.get_trace_settings(1))
time_trace = sa.acquire_trace(timeout_ms=10_000)
assert time_trace.axis_unit == "s"
```

Check that the external input is configured and receiving a trigger before
running this example, or set `trigger_source="free_run"` with
`configure_sweep_control()`. Keysight CXA N9000A has Trigger 1 only.
FSW26 also supports External 2 and External 3 when the connector has been
set to Input; the driver does not change connector direction. The FSW26
only reads an edge for the currently selected source. Gating, trigger
delay/holdoff and detector averaging type are separate settings.
Keysight automatic timing is not available in zero span or an FFT sweep
(`sweep_time_auto is None`); manual timing is available in zero span but
not an FFT sweep. Timing, attenuation and detector settings can be coupled
to other analyzer settings. Read back what the instrument actually took.
Use `describe_operation()` for profile limits and `list_operation_options()`
for supported trigger sources, trace modes, and detectors.

## Native trace accumulation and instrument markers

```python
sa.configure_trace(channel=1, mode="average", accumulation_count=8)
trace = sa.acquire_trace(channel=1, accumulation_count=8, timeout_ms=20_000)
print(trace.trace_mode, trace.sweep_count)  # "average", 8

# With span > 0 and dBm units, capture a Clear/Write trace for markers.
sa.configure_trace(channel=1, mode="clear_write", accumulation_count=1)
sa.acquire_trace(channel=1)
carrier = sa.find_marker_peak(channel=1, marker=1)
spur = sa.find_marker_peak(channel=1, marker=1, next_peak=True)
delta = sa.measure_marker_delta(carrier.frequency_hz, spur.frequency_hz, channel=1)
print(delta.frequency_delta_hz, delta.amplitude_delta_db)
```

The explicit count must match the instrument's configured Average/Hold
or Sweep/Average count and the selected trace must use Average, Max Hold,
or Min Hold. Both instruments restart and discard prior history; a fresh
batch never includes sweeps from an earlier run. The count is global,
not per trace. Keysight also requires other updating traces in Clear/Write
to avoid unintended accumulation. Without an explicit count, the existing
single Clear/Write workflow still applies.

Markers operate on the **held** trace, do not start a sweep, and change
front-panel marker state. Use them after a completed sweep on a normal
spectrum display in dBm (logarithmic on the FSW26). `set_marker()` positions a normal marker at a
requested frequency and reads back its actual coordinate and amplitude. On the
N9000A, the selected trace must be updating and in Clear/Write; a frozen
trace may still hold zero-span data even when the current span is non-zero.
Peak selection and next peak use the instrument's criteria, unlike
`trace.peak()`. Delta is target minus reference from two normal marker
readbacks, not a front-panel delta-mode assignment.

## Channel power and occupied bandwidth

```python
# Select Channel Power in Keysight SA mode before calling this.
channel = sa.measure_channel_power(bandwidth_hz=1e6, timeout_ms=15_000)
print(channel.power_dbm, channel.bandwidth_hz)

# Select Occupied BW in Keysight SA mode before calling this.
occupied = sa.measure_occupied_bandwidth(power_percent=99, timeout_ms=15_000)
print(occupied.bandwidth_hz, occupied.power_percent)
```

Both methods start a fresh native measurement and return the analyzer's
actual integration bandwidth or power percentage. On the N9000A select the
matching SA measurement and turn measurement averaging off. On the FSW26
start in the default Spectrum channel with non-zero span, single sweep,
an active Trace 1 in Clear/Write, sweep count 0 or 1, and trace math off. For channel
power use one transmit channel, Clear/Write power mode, and logarithmic
dBm with power density (/Hz) off.
The FSW26 call selects the named measurement and switches back to the
standard sweep after a validated result. It does not reset the analyzer,
retune, or optimize RBW, span, detector or reference level. A failure after
FSW26 measurement selection may leave the analyzer in a power view that
looks like ordinary Spectrum to a mode query. The driver then refuses
further spectrum I/O: restore the standard spectrum display, recover the
interface if needed, and reopen the bench. The channel power
result is a single carrier in dBm, not an adjacent-channel ratio.

## Adjacent-channel power (ACP/ACLR)

```python
acp = sa.measure_adjacent_channel_power(
    carrier_bandwidth_hz=150e3,
    adjacent_bandwidth_hz=175e3,
    spacing_hz=300e3,
    timeout_ms=15_000,
)
print(acp.carrier_power_dbm, acp.lower_power_dbm, acp.upper_power_dbm)
print(acp.lower_relative_dbc, acp.upper_relative_dbc, acp.adjacent_bandwidth_hz)
```

The operation measures one carrier and one symmetric pair. Spacing is
center-to-center. It returns the actual integration bandwidths and spacing;
omitting an argument keeps the instrument setting. The carrier and adjacent
passbands must not overlap, and the sweep must include both adjacent
channels. Choose the span, RBW, weighting filters, and trigger for your
signal first. This is not a standards-conformance recipe.

- **N9000A:** Select ACP in the SA application with Radio Standard None,
  one carrier, Total Power Ref and Reference Carrier power, Integration BW,
  offset A only with both sides active, center-to-center offsets, and
  measurement averaging off. The instrument returns carrier power and
  lower/upper dBc; the driver derives the absolute adjacent powers.
- **FSW26:** ACP/ACLR is not exposed by this profile. An FSW can load a
  Multi-Standard Radio ACLR preset inside the ordinary Spectrum mode.
  The legacy channel queries can then describe the lower side only.
  Without a verified preset readback or complete per-side geometry, the
  driver cannot safely label either one pair or multiple pairs as symmetric.

The driver rejects unexpected result layouts, unavailable-result sentinels,
and density units. See Keysight pp. 1585–1589, 1681–1696, 1709–1713,
1722–1724 and 1827, and FSW pp. 929, 931–934, and 954–957.

For adjacent **and alternate** channels, preconfigure the instrument's
pair count and geometry, then request exactly that count:

```python
series = sa.measure_adjacent_channel_pairs(pair_count=2, timeout_ms=20_000)
for band in series.pairs:
    print(band.pair, band.spacing_hz, band.bandwidth_hz,
          band.lower_relative_dbc, band.upper_relative_dbc)
```

Keysight supports 2–6 pairs, with offsets enabled contiguously from A.
The first item is the nearest adjacent pair; subsequent items are alternates in increasing
center-to-center spacing. Choose symmetric, non-overlapping bands that fit the
sweep span. This call reads rather than writes the pair count, bandwidths and
spacings, and checks geometry again after the sweep. It does
not enable additional pairs, retune, or select a standards-specific preset.
The Keysight response must match its documented 28-value Total Power
table. Disabled offsets are not included in the typed result. Multi-carrier
and asymmetric results remain outside this workflow.

## Profile limits

The bundled workflows cover standard spectrum sweeps and zero span, not
Spectrogram history, trace math, tracking, arbitrary multi-channel or
vector measurement applications, asymmetric or multi-carrier ACP, or binary transfers. They reject known
unsupported states instead of falling back to guesses. The FSW26 profile
requires the default active Spectrum channel and its standard window, not a
renamed channel or arbitrary display layout. Use
`supports_operation("acquire_trace")` for profile-level discovery. Use
`describe_operation("configure_measurement")` to see the configured limits.

- **N9000A:** the profile targets the portable 9 kHz–3 GHz center range,
  supports trace indexes 1–6, and limits requests and readback to 40,001
  points. It fetches paired X and Y coordinates in one response.
- **FSW26:** the profile limits center requests to 1 kHz–26.5 GHz and sweep
  point settings to 101–32,001; trace indexes are 1–6. It queries X and Y
  separately. A point-count and coordinate-order check is applied
  to avoid returning a truncated or mismatched trace.
- **Both:** RBW and VBW requests use conservative profile bounds of 1 Hz–1 MHz.
  Installed options and current settings can narrow actual valid ranges.
  Read the instrument's input limits and protect the RF input for your setup.

The models are verified against scripted command responses, not physical
instruments.

## Marker amplitude uncertainty

A normal CW marker on N9000A or FSW26 can evaluate one manufacturer component.
Pass the recorded conditions for that held acquisition, not later settings.
Missing or inapplicable conditions leave the marker nominal and explain why.

```python
from pytestlab.instruments.SpectrumAnalyser import SpectrumMarkerConditions

# Example only. Use evidence from your actual held acquisition.
capture = SpectrumMarkerConditions(
    model="N9000A", evidence="capture log A", prerequisites_met=True,
    temperature_c=24, tone_frequency_hz=50e6, input_power_dbm=-30,
    span_hz=100e3, rbw_hz=1e3, attenuation_db=10, preamp_on=False,
    vbw_hz=1e3, accuracy_coupled=True,
)
result = marker.to_measurement_result(
    uncertainty=True, conditions=capture, bound_distribution="rectangular",
)
```

Verify the live model, calibration interval, warm-up, alignment, and the
uncorrected single tone at the RF input before setting `prerequisites_met`.
The [N9000A guide](https://www.keysight.com/us/en/assets/9018-04769/technical-specifications/9018-04769.pdf)
(pp. 14, 27–28) gives a hard 50 MHz limit. Only a caller-selected
rectangular or triangular Type B model turns it into standard uncertainty.
The [FSW26 specs](https://www.rohde-schwarz.com/us/brochure-datasheet/fsw/)
(pp. 4, 23) use k=2; supply actual reference level, S/N, auto sweep time,
electronic attenuation, YIG state, and DC coupling below 10 MHz.
Read the component as `result.uncertainty` when available. Frequency,
whole traces, deltas, ACP, channel power and OBW are not covered here.
No calibration or correlation is inferred.

## Manual coverage by subsystem

See the [spectrum analyzer capability matrix](spectrum-analyzer-capabilities.md)
for the documented workflows, vendor-specific controls and unsupported modes.

## Programming references

- Keysight [X-Series Spectrum Analyzer Mode User's and Programmer's Reference](https://www.keysight.com/me/en/assets/9018-06099/user-manuals/9018-06099.pdf)
  (N9060-90027): pp. 594–596 (swept SA fetch), 620 (units), 638–639 (VBW),
  649 and 749–750 (continuous mode and ASCII format), 843–844 and 891 (restart/single), 198–199 (operation condition), 901 (source state), 981–982 (points),
  986–996 (trace type/update), 1010 and 1019–1020 (math/normalization),
  and 1053–1055 (Normal view and Spectrogram trace identity). See also pp.
  529–534 and 544–546 (trigger), 597–602 and 631–632 (RF input), 671–684 and 806–808
  (markers), 752–755 (average/hold), 927–933 (timing), 998–1001 (detector),
  1063–1064 and 1154–1155 (channel power), 1326–1328 and 1411–1412 (occupied
  bandwidth). Preamp option IDs are listed in the
  [N9000A configuration guide](https://www.keysight.com/in/en/assets/7018-02226/configuration-guides-archived/5990-4341.pdf).
  The [N9000A specifications guide](https://www.keysight.com/us/en/assets/9018-04769/technical-specifications/9018-04769.pdf),
  p. 57, identifies its Trigger 1 input and voltage limits.
- Rohde & Schwarz [FSW User Manual](https://scdn.rohde-schwarz.com/ur/pws/dl_downloads/pdm/cl_manuals/user_manual/1173_9411_01/FSW_UserManual_en_57.pdf)
  (1173.9411.02, v57, firmware 6.40): pp. 905–906 (options), 913–917
  (channel and sequencer), 841–842 and 1500 (operation condition), 921–923 (single sweep), 1180–1184 (external
  generator), 1214–1224 (bandwidths, sweep count, points and units),
  1116 and 1121 (window catalog and type), 1257–1260 and 1273 (trace modes, enablement and math), and 1274–1278 (ASCII and X/Y transfer).
  See also pp. 923–928 and 932–934 (power measurement and TX channel),
  983 (absolute power versus power density), 993–994 (occupied bandwidth),
  1218 and 1221 (count and timing),
  1224–1230 (RF input), 1236–1239 and 1246 (trigger), 1262–1263 (detector), and
  1290–1291, 1298 and 1304–1305 (markers).

See the [power and bandwidth result types](spectrum-analyzer-capabilities.md#power-and-bandwidth-results) for their fields.

::: pytestlab.instruments.SpectrumAnalyser
    options:
      filters:
        - "!^_"
        - "!^to_measurement_result$"
        - "!^(SpectrumMarkerConditions|SpectrumBoundDistribution)$"
        - "!^(SpectrumChannelPower|SpectrumOccupiedBandwidth|SpectrumAdjacentChannelPower|SpectrumAdjacentChannelPair|SpectrumAdjacentChannelPowerSeries)$"
