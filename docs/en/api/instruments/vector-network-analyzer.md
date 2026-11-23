---
title: Vector Network Analyzer
description: PyTestLab vector-network-analyzer sweep and S-parameter API.
---

# Vector network analyzer

## Inspect and configure a sweep without RF output

Use the bundled `keysight/E5071C_VNA` profile and an explicit VISA address.
On the same A-series firmware supported by held readback, the driver can
read a live channel-1 LIN or LOG configuration separately from the data.

Example `bench.yaml` (replace the address with your analyzer’s VISA resource):

```yaml
name: vna_bench
instruments:
  vna:
    profile: keysight/E5071C_VNA
    address: TCPIP0::192.0.2.10::inst0::INSTR
```

```python
from pytestlab import Bench

with Bench.open("bench.yaml", aliases={"vna"}, start_experiment=False) as bench:
    vna = bench.vna
    current = vna.get_s_parameter_sweep_settings()
    print(current.sweep_type, current.start_freq, current.stop_freq)
    print(current.s_params)  # Front-panel trace slot order

    # Before this call: set the instrument to idle Hold, turn RF Out OFF,
    # and turn off frequency offset and fixture simulation at the bench.
    configured = vna.configure_s_parameter_sweep(
        s_params=["S11", "S21"],
        start_freq=100e6,
        stop_freq=200e6,
        num_points=201,
        if_bandwidth=1e3,
        sweep_type="linear",
    )
    print(configured.num_points, configured.if_bandwidth)
```

An existing LIN or LOG sweep can be switched with `sweep_type="linear"`
or `sweep_type="log"`; omitting it keeps the current type. PyTestLab
checks the requested type and rechecks RF-off Hold before making any other
changes. To switch to LOG, first establish a span with stop frequency higher
than four times the start while RF is off. If the mode switch shifts the
frequency range or source power state, the remaining writes are refused. This operation does not switch from a
segment or power sweep. Only passed fields are written; passing `s_params`
replaces the channel's configured trace list, so back up any traces you
want to keep.
The return value is the observed `VNASweepSettings`, not a copy of the
request. It reports Hz, actual point count, trace order, RF enable state
and whether continuous triggering is enabled. `power_level` is the coupled
source setpoint in dBm, not measured power at the DUT. It is `None` when
ports are uncoupled; setting it requires coupled ports. The selected hardware option and current
power range may impose stricter limits than the profile.
`active_trace_correction_enabled` describes only the currently active trace,
not other traces or proof of a valid calibration. After a mode change,
recheck calibration and acquire new data before interpreting the trace.

These E5071C methods do not enable RF, reset the analyzer, change its trigger mode,
or collect calibration. If the instrument clips a setting, returns an
error, or can't be read back, the operation fails. Earlier writes may
already have taken effect; inspect the instrument before trying again.
Keep the front panel and other clients unchanged. The driver checks RF
state and holds its local command lock, but can't interlock the front panel
or physically limit RF. Disconnect or isolate any external sources before
configuring. Historically configured custom VNA profiles that
lack this readback capability retain their write-only setup behavior.

For data after setup, confirm the settings and safe RF power at the bench,
then acquire on the front panel and return the analyzer to Hold. Use the
held-read path below. For a verified safe setup, you can also request one
fresh sweep directly from Python. R&S ZNB is not covered by this E5071C profile.

Command references: Keysight [Configuring Measurement Conditions](https://helpfiles.keysight.com/csg/e5071c/programming/remote_control/setting_up_analyzer/configuring_measurement_conditions.htm),
[RF output](https://helpfiles.keysight.com/csg/e5071c/programming/command_reference/output/scpi_output_state.htm),
[sweep type](https://helpfiles.keysight.com/csg/e5071c/programming/command_reference/sense/scpi_sense_ch_sweep_type.htm),
and [Trigger System](https://helpfiles.keysight.com/csg/e5071c/programming/remote_control/making_measurement/trigger_system.htm).

## Acquire one fresh E5071C sweep

Call this method directly in Python on an RF-safe bench to trigger one sweep.
It does not enable RF, change settings, or certify the connected DUT.

```python
from pytestlab import Bench

with Bench.open("bench.yaml", aliases={"vna"}, start_experiment=False) as bench:
    sweep = bench.vna.acquire_s_parameter_sweep()
    print(sweep.fresh, sweep.sweep_type, sweep.param_names)
```

Use a two-port E5071C reporting option 240, 260 or 280 in `*OPT?`, with
A.11.20 or later A-series firmware. Prepare channel 1 in effective
single-channel mode, with 2–1601
points, a LIN or LOG **stepped** sweep, ASCII, BUS trigger, and idle Hold
(continuous initiation off). For LOG, set the stop frequency higher than
four times the start before selecting LOG; a narrower span can fall back
to LIN. Inspect the observed sweep type if the distinction matters.

At the bench, verify safe frequency and peak power at **both** DUT ports
through arming, switching, sweeping, and Hold. Isolate auxiliary
trigger/handler, external source, external test-set, and bias paths.
The operator enables RF only after these checks. The driver's native analyzer
frequency and source setpoint limits do not establish actual DUT power, safe
cabling, or an RF interlock.

The driver matches the observed two-port hardware, checks channel, trigger,
coupled source power and trace state, rechecks while armed, and returns the
data only after one synchronized sweep. It verifies the instrument-reported
axis and indexed complex data; for LOG, the stable channel stimulus must match
all measured trace axes. PyTestLab preserves these reported frequencies rather
than calculating ideal log bins. A held read never sets `fresh=True`.

Start from a clean instrument interface with no pending replies. A text
`*STB?` check cannot independently prove that the interface started clean.
Keep exclusive control of the instrument; the local transaction lock cannot
exclude the front panel or independent clients.

`timeout_ms` is a budget for starting commands and setting their remaining
I/O timeout. It does not interrupt a connection attempt, lock wait, or an
in-flight backend call. A synchronized abort has a separate cleanup budget.
After an interrupted exchange with an uncertain reply, the driver blocks
further I/O through that object and never retries the trigger. Stop the
sweep and make the DUT safe at the bench, clear the interface, and open a
new session. Where abort is safe and the stream is synchronized, the driver
attempts to return to Hold. **Hold is not RF off.** This path is covered by
scripted instrument responses, not qualified on live hardware.

Vendor references: [Trigger System](https://helpfiles.keysight.com/csg/e5071c/programming/remote_control/making_measurement/trigger_system.htm),
[single trigger completion](https://helpfiles.keysight.com/csg/e5071c/programming/command_reference/trigger/scpi_trigger_sequence_single.htm),
[measured LOG points](https://helpfiles.keysight.com/csg/e5071c/programming/command_reference/sense/scpi_sense_ch_sweep_type.htm),
[channel stimulus](https://helpfiles.keysight.com/csg/e5071c/programming/command_reference/sense/scpi_sense_ch_frequency_data.htm),
[LOG span error 53](https://helpfiles.keysight.com/csg/e5071c/product_information/error_messages/error_messages.htm),
[channel modes](https://helpfiles.keysight.com/csg/e5071c/measurement/setting_measurement_conditions/setting_channels_and_traces.htm),
[port count](https://helpfiles.keysight.com/csg/e5071c/programming/command_reference/service/scpi_service_port_count.htm),
[hardware option IDs](https://helpfiles.keysight.com/csg/e5071c/product_information/options.htm),
[stimulus power specifications](https://www.keysight.com/us/en/assets/7018-01424/data-sheets/5989-5479.pdf),
and [applied trace correction](https://helpfiles.keysight.com/csg/e5071c/programming/command_reference/sense/scpi_sense_ch_correction_type_tr.htm).

## Read an existing E5071C sweep

The bundled Keysight E5071C profile reads already acquired S-parameter traces
on channel 1 with firmware A.09.60 or later in the A series. Set up and acquire
the sweep at the instrument first, then place it in **Hold** with **ASCII** data
transfer. Leave frequency offset, fixture simulation, trace equations and
time-domain transforms off. This path supports nonzero-span linear and
logarithmic frequency sweeps. It fails rather than changing settings or
triggering a sweep when the requested state or firmware is unsupported.

```python
from pytestlab import Bench

with Bench.open("bench.yaml", aliases={"vna"}, start_experiment=False) as bench:
    trace = bench.vna.get_s_parameter_data()

    print(trace.param_names)         # ["S11", "S21"] in profile request order
    print(trace.frequencies[:3])     # Frequencies in Hz read from the analyser
    print(trace.s_params[0][:3])     # Complex S11 samples at those frequencies
```

The bundled E5071C profile requests existing S11 and S21 traces by default.
It reads their actual slots without selecting a different trace. The shared
axis is marked `"instrument"` and `trace.trace_identity_verified` is true.
Neither flag establishes buffer age or calibration. Keep other clients and
the front panel unchanged. This readback was tested offline, not on hardware.
See Keysight's
[indexed S-parameter data](https://helpfiles.keysight.com/csg/e5071c/programming/command_reference/calculate/scpi_calculate_ch_selected_data_sdata.htm)
and [indexed X-axis data](https://helpfiles.keysight.com/csg/e5071c/programming/command_reference/calculate/scpi_calculate%28ch%29_selected_data_xaxis.htm)
references.

Legacy custom profiles using an aggregate `sparameter_data` query retain their
historical result shape. For those profiles the axis is calculated from the
profile's start, stop and point count, not read from the instrument.
`axis_source == "profile_nominal"` and `trace_identity_verified == False`
distinguish that result from verified indexed readback.

## Inspect and export a result

Use a trace name instead of a position in the returned trace list. Lookup
returns the nearest **measured** frequency bin in the sweep, and its complex
sample. It stays within the measured span, does not interpolate, and chooses
the lower-frequency bin if two bins are equally close.

```python
from pytestlab import Bench

with Bench.open("bench.yaml", aliases={"vna"}, start_experiment=False) as bench:
    sweep = bench.vna.get_s_parameter_data()

point = sweep.trace("S21").at_frequency(150e6)  # Example: a sweep spanning 100–200 MHz
print(point.frequency_hz, point.value)
sweep.to_csv("sweep.csv")
```

The CSV contains the frequency in Hz, real and imaginary columns for each
returned trace, and the axis source, trace identity and freshness flags.
The export does not touch the analyzer and refuses to overwrite an existing
file unless you pass `overwrite=True`. Legacy profile-nominal results cannot
look up measured bins. CSV does not assert reference impedance or calibration.
Pass the sweep directly to `db.store_measurement(None, sweep)` or [return it from a session](../../user_guide/measurement_session.md#store-a-waveform-or-sweep-with-each-trial).

## Read an existing Copper Mountain C1209 buffer

The bundled `coppermountain/C1209` profile is **manual-backed and tested
against hand-authored transcripts**. It is not qualified on the vendor
simulator or on physical hardware. It expects a C1209 controlled by the
S2VNA application reporting software version `26.2.2` in `*IDN?`; use a
raw TCPIP SOCKET resource with a VISA implementation that supports it, not
a HiSLIP, VXI-11 or LAMB resource.

On the S2VNA host, configure the socket server and prepare and acquire the
measurement in the operator interface. Stop the trigger system in **Hold**
with continuous initiation off. Use channel 1 with a positive-span linear
or logarithmic frequency sweep and one distinct trace per requested
S-parameter. Frequency offset, fixture simulation, and selected-trace math,
time transform, gate, conversion, and min/max trace hold must be off. Do not
change setup or access the instrument from another client during the read.

In `bench.yaml`, set the C1209 profile and the real S2VNA host address:

```yaml
name: c1209_bench
instruments:
  vna:
    profile: coppermountain/C1209
    address: TCPIP0::s2vna-host.example::5025::SOCKET
```

```python
from pytestlab import Bench

with Bench.open("bench.yaml", aliases={"vna"}, start_experiment=False) as bench:
    held = bench.vna.get_s_parameter_data()  # default requests S11 and S21
    print(held.param_names, held.frequencies, held.s_params)
```

The driver requests the actual X-axis and complex buffer from the **same
indexed trace**, keeps the requested trace order, and rejects different
frequency axes even when their lengths match. Each axis must also agree with
the observed stimulus span, allowing for small rounding differences. This
is a consistency check, not a freshness check. The driver sends only
queries, never selects a trace or starts a sweep, and closes a stream after an ambiguous
exchange without retrying on that stream. The reply proves an indexed buffer
and axis were readable, not when or how the buffer was populated. The vendor
interface permits users to write the buffer or load previously captured data.
Hold is not an RF isolation or output-off guarantee. Setup and fresh acquisition are not supported by this Copper Mountain
profile.

See the vendor's [S2VNA 26.2.2 model list](https://coppermountaintech.com/help-s2/index.html),
[identification response](https://coppermountaintech.com/help-s2/idn.html),
[SCPI manual](https://coppermountaintech.com/wp-content/uploads/2020/09/SxVNA-SCPI-Programming-Manual-2.pdf)
(section 2.7 and the indexed trace command entries), and
[trace hold command](https://coppermountaintech.com/help-s2/calcholdtype.html).

## Inspect channel and trace context

`get_s_parameter_channel_context()` is a query-only inventory of the
configured channel in Hold, without reading the trace buffers. It reports
analyzer identity and firmware/software, the port count and reference
impedances, frequency range and point count, IF bandwidth, averaging
settings, whether port extension is on, and trace slots with their applied
correction method and ports.
On the E5071C, the same observed system Z0 is listed for each port. The
C1209 reports each port's Z0 separately. Correction data describes what
the instrument currently reports, not whether a calibration is valid.
The C1209 also reports its channel-wide correction switch; E5071C
correction is trace-specific.

```python
with Bench.open("bench.yaml", aliases={"vna"}, start_experiment=False) as bench:
    state = bench.vna.get_s_parameter_channel_context()
    print(state.model, state.channel, state.port_reference_ohms)
    print(state.trace(1).parameter, state.trace(1).correction_method)

    held = bench.vna.get_s_parameter_data(include_context=True)
    peak = held.trace("S21").magnitude_extrema().maximum
    print(peak.frequency_hz, peak.magnitude_db, peak.phase_deg)
```

Opt in to context around the data read to retain the matching configuration
on the result. The driver compares the settings before and after, and checks
the frequency endpoints and indexed traces. This is still a held read: it
does not determine the age, origin, or calibration of pre-existing or
imported data. The result's evidence labels distinguish an independent
configuration snapshot, a held read, and a fresh sweep. Start
with an exclusive, clean session. Both profiles limit this operation to
channel-1 LIN/LOG frequency sweeps in ASCII Hold with frequency offset and
fixture simulation disabled.

`magnitude_extrema(start_hz=…, stop_hz=…)` finds minima and maxima among the
measured bins inside the specified band, not an interpolated peak. A bin
also exposes its log magnitude and principal phase. Zero magnitude has
undefined phase. These methods never move instrument markers.

To read an existing front-panel marker, use
`bench.vna.get_s_parameter_frequency_marker(trace=2, marker=1)`. The trace
slot is not the returned trace order. The marker must already be on, on a
visible single-ended S-parameter data trace in Log Mag format. Turn off
the reference marker, memory display, time-domain transform and conversion
at the bench. E5071C supports marker numbers 1–9, and C1209 supports 1–15.
The result is the displayed absolute marker location in Hz and magnitude
in dB; the analyzer may interpolate it. For a measured bin from complex
data instead, use `trace.at_frequency()`.

## Attach setup-specific S-parameter uncertainty

Neither bundled profile infers S-parameter uncertainty. The [E5071C data
sheet](https://www.keysight.com/us/en/assets/7018-01424/data-sheets/5989-5479.pdf)
and [Keysight system verification](https://helpfiles.keysight.com/csg/e5071c/product_information/maintenance/system_verification.htm)
depend on the kit, cables and adapters. The [C1209 data sheet](https://coppermountaintech.com/wp-content/uploads/2022/10/CMT21-EXTENDED-DATA-SHEET_COBALT-9.pdf)
lists uncorrected performance; [CMT VNA metrology](https://coppermountaintech.com/introduction-to-the-metrology-of-vna-measurement/)
shows how residual errors and the DUT response affect a calibrated result.
Neither dynamic range nor correction status supplies a DUT budget.

If your lab has evaluated a joint standard uncertainty budget for the actual
setup, capture the sweep with `include_context=True` and attach the lab's
dimensionless `QuantityArray`. The independently supplied frequency grid,
trace order and nominal values must match the capture exactly. Flatten the
components by frequency, then by the recorded trace order, with each real
component followed by its imaginary component. The budget must cover every
component and explicitly represent the applicable correlations; missing
correlations are not estimated. This does not model frequency-axis
uncertainty.

```python
# budget.components is the QuantityArray from your lab's uncertainty evaluation.
measured = sweep.with_uncertainty(
    budget.components,
    frequencies_hz=budget.frequencies_hz,
    trace_order=budget.trace_order,
    source=budget.report_id,
    setup=budget.setup_id,  # Calibration, fixture and DUT reference planes
)
# View the full 2×2 covariance of the first trace at the first measured frequency.
components = measured.uncertainty
assert components is not None
print(components[:2].covariance_matrix())
key = db.store_measurement(None, measured)
saved = db.retrieve_measurement(key)
assert saved.uncertainty is not None
```

The same typed frequency and signed RI columns are stored in Session,
Experiment, Parquet, or SQLite. The budget keeps correlations across real
and imaginary components, traces, and frequencies. It is labeled
`externally_evaluated`: PyTestLab checks alignment, but does not validate the
physical calibration or certify the evaluation. Without an attached budget the
values remain useful and are explicitly `not_evaluated`; this does not mean
zero uncertainty. CSV and Touchstone exports contain nominal data only.

## Inspect analyzer capacity

```python
inventory = vna.get_vna_inventory()
print(inventory.active_channel, inventory.profile_channel)
print(inventory.max_sweep_points, inventory.profile_max_points)
print(inventory.frequency_limits)
```

This query-only snapshot reports the matched analyzer identity, physical port
count, service-reported channel, trace and point limits, the current active channel
in the instrument or application, and the trace count on the profile channel. It works in idle
Hold regardless of sweep type; it never selects a channel or reads trace data.
The service point limit can differ from both the current sweep's point count and
the profile's smaller readback cap.

C1209/S2VNA reads the analyzer's frequency limits directly. On E5071C the
nominal range and bias tee availability come from Keysight's option table
only when `*OPT?` identifies one recognized test set consistent with the
reported port count. Without that option evidence, frequency limits are
`None`. Neither source certifies a fixture or DUT power limit, or expands
the supported acquisition workflows. See the
[ENA service point limit](https://helpfiles.keysight.com/csg/e5071c/programming/command_reference/service/scpi_service_sweep_points.htm),
[ENA installed options query](https://helpfiles.keysight.com/csg/e5071c/programming/command_reference/ieee/scpi_ieee4882_opt.htm)
and [S2VNA service reference](https://coppermountaintech.com/wp-content/uploads/2020/09/SxVNA-SCPI-Programming-Manual-2.pdf#page=389).

## Inspect the instrument's segment table

```python
table = vna.get_s_parameter_segment_table()
print(table.active_sweep_type, table.frequency_mode)
for row in table.segments:
    print(row.index, row.start_hz, row.stop_hz, row.point_count)
```

This query-only operation observes the profile channel in idle Hold on both
models. It reports the stored table even when another sweep type is selected.
Rows are returned in instrument order. Center/span settings are converted to
start/stop in hertz; these are configured values, not a measured axis.
Optional fields such as bandwidth, power setpoint and delay are `None` when
not reported by the table. Their absence does not imply a default RF level.

On E5071C A.09.60+, the result includes the individual state control and the
enabled state of each row. A.11.20+ also reports the arbitrary-segment switch,
so reverse start/stop rows are preserved when it is enabled. Configured sweep
mode and timing are shown when present; ENA's reported sweep time of 0 means
automatic. The result does not include separate ENA per-port power, per-port
bandwidth or Shift LO tables. On C1209/S2VNA the native response does not
report per-row enable or stepped/swept mode, and its reserved optional timing
column is not interpreted as a time.

This operation does not set up or run a segment sweep, read its trace buffer
or authorize RF. See the
[ENA array format](https://helpfiles.keysight.com/csg/e5071c/programming/command_reference/sense/scpi_sense_ch_segment_data.htm),
[ENA segment controls and limits](https://helpfiles.keysight.com/csg/e5071c/measurement/optimizing_measurements/performing_a_segment_by_segment_sweep_segment_sweep.htm)
and [S2VNA array format](https://coppermountaintech.com/help-s2/senssegmdata.html).

## Export a complete characterized two-port sweep

On the E5071C in idle Hold with RF off, configure all four traces. This also
updates what this driver requests; the default is only S11 and S21.

```python
vna = bench.vna  # Keep this Bench session open through acquisition.
vna.configure_s_parameter_sweep(s_params=["S11", "S21", "S12", "S22"])
```

At the instrument, verify calibration, the fixture and safe RF at both DUT
ports. Follow the [fresh-sweep setup](#acquire-one-fresh-e5071c-sweep) for BUS
trigger and idle Hold, leave port extension off, and enable RF. Then use that
same `vna`:

```python
capture = vna.acquire_s_parameter_sweep(include_context=True)
capture.to_touchstone("device.s2p")
```

The local [Touchstone 1.0](https://ibis.org/touchstone_ver2.1/touchstone_ver2_1.pdf)
file uses Hz, real/imaginary pairs in S11, S21, S12, S22 order, and the verified
common real reference impedance. No renormalization or calibration certification.
Touchstone refuses held, partial, or modified results. Use `to_csv()` for held
or partial data; CSV does not assert a reference impedance.

## Model, option, and workflow coverage

These are software admission rules tested against offline responses, not
hardware qualification. The E5071C profile does not cover R&S ZNB, other
ENA models, or a different firmware series. The C1209 profile requires
the S2VNA socket dialect; it is not the separate CMT VNA or S4VNA app.

| Model or test-set option | Vendor configuration | PyTestLab scope |
| --- | --- | --- |
| E5071C 240 / 260 / 280 | Two ports, no bias tee; 9 kHz through 4.5 / 6.5 / 8.5 GHz respectively | Held reads on admitted A.09.60+ firmware. Fresh requires A.11.20+ in the A series, a reported supported option, and a prepared bench. |
| E5071C 230 / 430 | Two / four ports, no bias tee; 9 kHz to 3 GHz | Held and RF-off setup only, within the actual hardware range; no fresh support. |
| E5071C 440 / 460 / 480 | Four ports, no bias tee; 9 kHz through 4.5 / 6.5 / 8.5 GHz respectively | Held and RF-off setup only; no four-port fresh protocol or Touchstone export. |
| E5071C 235 / 245 / 265 / 285 and 435 / 445 / 465 / 485 | Two / four ports with bias tees; 100 kHz through the respective 3 / 4.5 / 6.5 / 8.5 GHz limits | Held and RF-off setup only with external paths isolated; no bias control or fresh support. |
| E5071C 2D5 / 4D5 / 2K5 / 4K5 | Two / four ports with bias tees; 300 kHz through 14 / 20 GHz | Held and RF-off setup only; native output limits differ from 240/260/280. |
| CMT C1209 | Two-port 9 GHz Cobalt, exact S2VNA 26.2.2 with numeric hardware revision in `*IDN?` | Bounded LF/ASCII TCPIP SOCKET; held trace, context and passive configuration only. The identity grammar and build number are vendor-documented; the combined current reply and trace context are not yet captured from the app or physical hardware. |

| Documented workflow family | E5071C | C1209 |
| --- | --- | --- |
| Frequency endpoints, points, bandwidth and trace settings | LIN/LOG verified RF-off setup and readback; channel context adds averaging readback | LIN/LOG readback in Hold; no setup writes |
| Data transfer and trace catalogue | Indexed complex ASCII, common measured frequency axis, trace context | Model-pinned indexed complex LF/ASCII, same-trace axis and stable catalogue |
| Error correction, port extensions and calibration kits | Applied correction and system Z0 readback only | Applied correction, channel correction switch and per-port Z0 readback only |
| Triggering, source power and output | One direct Python BUS-triggered LIN/LOG stepped sweep in supported two-port mode; no automatic RF enable | No fresh triggering, RF writes, or calibration runs |
| Markers, search, limits and statistics | Existing absolute Log Mag marker read; local measured-bin lookup and magnitude extrema | Same read-only workflow; no front-panel changes |
| Files and transfer formats | Local CSV; fresh full two-port common-Z0 Touchstone 1.0 | Local CSV; no claimed Touchstone normalization from a held buffer |
| Analyzer capacity and identity | Service channel/trace/point limits, active channel and installed options; nominal frequency limits when exactly identified | Service channel/trace/point and frequency limits, active channel and exact S2VNA identification |
| Segment sweep table | Passive readback of the main table, row enable and firmware-gated arbitrary mode; no writes or acquisition | Passive main-table readback only; no writes or acquisition |
| Power sweep, binary transfer, TDR, fixture simulation, de-embedding, mixed mode, switch matrices, extenders, and automation/macro/service controls | Vendor-documented families, not exposed by these workflows; feature and option availability varies | Vendor-documented where applicable to model/software, not implemented by these workflows |

See the [Keysight option table](https://helpfiles.keysight.com/csg/e5071c/product_information/options.htm),
[ENA system Z0](https://helpfiles.keysight.com/csg/e5071c/programming/command_reference/sense/scpi_sense_ch_correction_impedance_input_magnitude.htm),
[ENA port extension](https://helpfiles.keysight.com/csg/e5071c/programming/command_reference/sense/scpi_sense_ch_correction_extension_state.htm),
and [ENA trace correction](https://helpfiles.keysight.com/csg/e5071c/programming/command_reference/sense/scpi_sense_ch_correction_type_tr.htm).
For C1209 see [the S2VNA model list](https://coppermountaintech.com/help-s2/index.html),
[identity format](https://coppermountaintech.com/help-s2/idn.html), and
[SxVNA programming guide](https://coppermountaintech.com/wp-content/uploads/2020/09/SxVNA-SCPI-Programming-Manual-2.pdf)
(pp. 338, 342, 346, 390). Compare a physical C1209's raw identity and held
trace plus configuration replies with its About screen and vendor CSV
before claiming that build is hardware verified.

::: pytestlab.instruments.VectorNetworkAnalyser
    options:
      filters:
        - "!^_"
        - "!^to_measurement_result$"
