---
title: Waveform Generator
description: PyTestLab waveform-generator frequency, amplitude, function, burst, and output API.
---

# Waveform generator

Use `list_operation_options("set_function", "function_type")` to choose a
profile-supported semantic waveform and pass its `value` to `set_function()`.
No waveform enum import is required.

Compound function changes validate the supplied settings before writing.
Function values remain profile-defined and extensible; settings not explicitly
accepted by the method are rejected before instrument I/O.

`frequency`, `amplitude`, and `offset` are the only optional settings accepted
by `set_function`. They use the same aliases, channel-dependent ranges, and
validation as their standalone setters. Unknown keyword arguments are rejected
before any command is built or sent; function-specific settings should use
their existing explicit profile/source methods.

The EDU33212A profile validates native frequency, amplitude, offset, unit and
load limits. Standalone numeric setters query current native bounds; compound
settings also check the prospective waveform and the joint amplitude/offset
budget. Enabled instrument voltage limits are checked before setting writes.
Selecting dBm requires a finite load. A function change with an incompatible
retained frequency requires an explicit valid frequency. Compatible supplied
settings are ordered to avoid a transient native settings conflict.

Some native amplitude-bound replies are rounded; sending the returned number
literally can produce a firmware range error. The driver recognizes requested
endpoints and sends native `MINimum`/`MAXimum` tokens after checking the joint
output budget. The selected unit remains unchanged. Values between endpoints
still require a valid unit-aware range; rounded replies do not enlarge the
physical output envelope.

Use `MIN`/`MAX` for native-bound queries. `DEF` remains a supported setter value,
but is not a documented EDU33212A query selector. Invalid requests raise
`InstrumentParameterError`; connection failures and unexpected firmware errors
remain possible. Arbitrary waveform asymmetric peak/offset validation is not
qualified by the standard-waveform envelope. Raw SCPI commands bypass these
high-level parameter checks.

::: pytestlab.instruments.WaveformGenerator.WaveformGenerator
    options:
      members:
        - from_config
        - channel
        - set_function
        - get_function
        - set_frequency
        - get_frequency
        - set_amplitude
        - get_amplitude
        - set_offset
        - get_offset
        - set_phase
        - get_phase
        - synchronize_phase_all_channels
        - set_output_state
        - get_output_state
        - set_output_load_impedance
        - get_output_load_impedance
        - set_voltage_unit
        - get_voltage_unit
        - download_arbitrary_waveform_data
        - apply_waveform_settings
        - get_complete_config
        - enable_modulation
        - enable_sweep
        - enable_burst

::: pytestlab.instruments.waveform_set.SharedClockModel

::: pytestlab.instruments.waveform_set.WaveformSetResult
