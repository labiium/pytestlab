# Source-measure instruments

`SourceMeasure` is a generic source-measure driver. Commands, response
parsing, status text, and compliance statuses are profile data; the Python
driver does not contain vendor branches.

```python
smu.set_current(1, 100e-6)       # voltage-mode current compliance
smu.set_voltage(1, 1.2)           # emits a paired force-voltage command
smu.channel(1).on()
reading = smu.read_current(1)
assert reading.compliance is not None
smu.channel(1).off()              # disconnects output; does not zero it
```

Current forcing is intentionally explicit because `set_current` follows
power-supply naming and means current compliance:

```python
smu.force_current(1, 10e-6, voltage_compliance=2.0)
```

All source and compliance values are checked against finite, static channel
ratings before any command is sent. `validate_channel_settings(...)` performs
the same checks offline. `output(..., True)` requires a complete configured
mode/compliance pair. `output(..., False)` only sends the profile's off
command. `get_output_state` is available only when a profile supplies a
verified query; the cached requested state is never reported as readback.

Reads return `TypedMeasurementResult`, preserving the raw header, channel,
status, decoded status text, and profile-defined compliance flag alongside a
`Quantity`. If no accuracy model is configured, the quantity is explicitly
nominal-only and non-report-grade; no uncertainty is invented.

The packaged HP 4142B profile has no assumed installed source cards. Supply
qualified `channels` entries with the installed unit's ratings before using
actuation APIs. The profile's `DV`, `DI`, `CN`, `CL`, `TI`, and `TV` mappings
follow the [Keysight 4142B HP-IB Command Reference](https://www.keysight.com/aw/en/assets/9018-07919/reference-guides/9018-07919.pdf):

- `DV ch, output-range, voltage, I-compliance, compliance-polarity`
- `DI ch, output-range, current, V-compliance, compliance-polarity`

The profile uses the documented auto-range (`0`) and automatic compliance
polarity (`0`) defaults. The command reference lists these forms in the DV/DI
sections; the [Control Software Programming Manual, Force_v/Force_i sections](https://www.keysight.com/aw/en/assets/9018-07920/programming-guides/9018-07920.pdf)
specifies that `0` is auto ranging for both voltage and current output ranges.

## API reference

::: pytestlab.instruments.SourceMeasure.SourceMeasure
