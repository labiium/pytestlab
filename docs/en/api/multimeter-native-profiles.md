# Native multimeter profiles

PyTestLab's generic `Multimeter` driver builds the complete profile-declared acquisition sequence before sending any command. In query mode it writes the setup commands and queries the final command. With `response.transport: read`, it writes the whole sequence, then reads the response without sending a query. Both paths use the response parser declared by the profile.

## Agilent/Keysight 3458A

The packaged `agilent/3458A` profile declares DC-voltage acquisition only. Select it with `dmm.measure("dc_voltage")`:

- `DMMFunction.VOLTAGE_DC` is translated from the generic `VOLT:DC` token to the native `DCV` function.
- Autorange or a caller-provided maximum input is passed to the native `FUNC` command. A default `DEF` resolution is represented by the native default (an empty resolution field).
- By default, the profile sequence sets `NPLC 1`, `NRDGS 1,AUTO`, `OFORMAT ASCII`, `TARM AUTO`, and `TRIG SYN`, then performs the controller data request through the profile-declared `read` transport.
- The native ASCII reading is parsed as a SCPI float. The profile configures CR/LF read termination.
- `configure_measurement()` uses the same setup sequence without the final data request. `get_config()` uses `FUNC?` and parses its two-field native CSV response; the profile maps the documented numeric DCV function code to the canonical `VOLT:DC` name before common unit/mode handling.
- `measure(..., nplc=...)` and `configure_measurement(..., nplc=...)` accept a finite NPLC value only because this profile declares the parameter and its `0..1000` range. Invalid values are rejected before any writes.
- The public trigger semantic is `ON_READ`; the profile translates it to the native `SYN` token internally. Other generic trigger values are rejected for this profile rather than being mis-mapped.

The synchronous trigger choice follows the [Keysight 3458A User's Guide](https://www.keysight.com/us/en/assets/9018-01343/user-manuals/9018-01343.pdf): a synchronous event occurs when the controller requests data while the output buffer is empty and reading memory is disabled. The guide also documents ASCII as the ordinary output format and `TARM AUTO` / `TRIG SYN` in the normal remote state.

The guide documents `FUNC?` as returning two comma-separated responses: the present measurement function and the actual measurement range. Query response format may be numeric or alpha, so this profile declares the verified numeric DCV mapping rather than embedding a model-specific code table in Python.

The profile does not send `RESET`, `*RST`, `PRESET`, `*CLS`, or `*OPC` implicitly. Those commands would alter instrument state and are not required for this acquisition sequence.

## Accuracy and supported functions

The 3458A profile intentionally contains no fabricated accuracy values. Unless a lab-provided accuracy/calibration fixture is added, `measure(..., uncertainty=True)` returns a nominal-only quantity marked non-report-grade; callers can request a nominal scalar with `uncertainty=False`.

Only the DCV function is declared as supported by this profile. Other generic DMM functions require a profile extension backed by the instrument manual and hardware evidence; they are not silently translated or guessed.
