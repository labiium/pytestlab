# Declarative profile instruments

These examples retain the generic descriptor interface under explicit
`agilent/3458A_legacy`, `hp/4142B_legacy`, `hp/HP4084B_legacy`, and
`suss/PA200_legacy` presets. The canonical presets now use the native
multimeter, source-measure, switch-matrix, and prober device APIs.
The PA200 protocols differ: choose the preset matching your controller firmware.
The native HP4142B requires configured installed-module limits before sourcing.
`touptek/E3CMOS12000KPA` adds the LAMB camera preset; backend and address
are supplied by the bench, not embedded in the profile. Copy the camera's
complete resource string from `ptl camera discover` into `address`.

The built-in `ProfileInstrument` exposes the operation descriptors declared in
an instrument profile. It is intended for legacy controllers whose commands do
not have a reusable model-specific Python driver.

The example bench in `examples/profile_instrument_bench.yaml` binds the HP
controller to example GPIB address 22 and the SUSS PA200 to example address 1.
Those addresses and the Lamb backend belong to the bench descriptor; they are
not part of either packaged profile.

## Legacy controller operations

The `hp/HP4084B_legacy` controller profile covers the HP4084B/HP4085B matrix
family. Its `connect`, `disconnect`, `guard`, and `clear` operations change live
wiring. Take connected sources to zero and let them settle before switching,
and check the fixture and interlocks locally. The driver does not verify those
physical conditions.

```python
controller.execute_profile_operation("connect", port=1, pin=12)
```

Pins are constrained to 1–48; valid HP ports are 1–6 and 8–10 (port 7 is
unused). The profiles expose the documented `ID`/`IDEX`, `PN`, and `PT`
queries, plus native status-byte decoding metadata. HP status-byte reads use
the backend's `read_status_byte` capability; they do not issue `*IDN?` or an
SCPI error-queue query.

The `suss/PA200_legacy` profile intentionally has no identity alias. Its documented
status, chuck-position, chuck-status, external-mode, and stop commands are all
query transactions because the controller requires a response before another
command, including for state-changing commands. Its native status byte only
describes response/data readiness (bit 4), not a global health fault.

The optional `agilent/3458A_legacy` and `hp/4142B_legacy` reference profiles are deliberately
read-only: they expose only their documented identity query and native status
byte. They do not infer acquisition, reset, source-control, module-limit, or
error-queue operations. The HP 4084B, PA200, and these reference profiles carry
`capabilities.message_io.read_termination: "\\n"`; the generic driver applies
that setting before connecting, while native status and raw transfers remain
unchanged.
