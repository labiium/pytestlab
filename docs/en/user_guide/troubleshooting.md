---
title: Troubleshooting
description: Diagnose VISA discovery, driver, permission, connection, and simulation problems in PyTestLab.
---

# Troubleshooting

Start here when PyTestLab cannot discover or connect to an instrument. Test in simulation first: it separates application or profile problems from driver, cable, permission, and hardware problems.

## Verify PyTestLab without hardware

Create the same instrument with simulation enabled. If this works, the Python package and profile can load correctly.

```python
from pytestlab.instruments import AutoInstrument

scope = AutoInstrument.from_config("keysight/DSOX1204G", simulate=True)
print(scope.identity())
scope.close()
```

If simulation also fails, verify the profile key against the [Profile Gallery](../profiles/gallery.md) and inspect the full Python traceback.

## No VISA instruments are listed

1. Confirm that a vendor VISA implementation is installed, such as NI-VISA, Keysight IO Libraries, or Rohde & Schwarz VISA.
2. Restart the terminal after installing the driver so environment changes are visible.
3. Ask PyVISA what it can see:

```python
import pyvisa

manager = pyvisa.ResourceManager()
print(manager.list_resources())
print(manager.visalib)
```

If the tuple is empty, use the vendor connection utility to confirm that the instrument, cable, IP address, and VISA resource string work outside PyTestLab.

## Permission denied on Linux

USB instruments can require a vendor driver or a `udev` rule. Confirm that the device appears in `lsusb`, install the rule recommended by the instrument vendor, then disconnect and reconnect the device. Avoid running the whole application as root; fix device permissions instead.

## The resource exists but connection fails

- Copy the exact resource string returned by `list_resources()` rather than typing it from memory.
- Confirm that another application is not holding an exclusive session.
- For TCP/IP instruments, verify reachability and that the instrument's remote-control service is enabled.
- Increase the connection timeout only after confirming that the address is correct.
- Compare real and simulated construction using the same profile.

## Profile or command mismatch

An instrument can connect successfully but reject a command when its firmware or model differs from the selected profile. Query the instrument identity, compare it with the profile model, and capture the failing SCPI command in debug logs before modifying a profile.

## Comparing uncertainty-aware readings

Comparison operators answer the ordinary nominal-value question and work in
conditionals, `pytest.approx(...)` assertions, sorting, and `min()` / `max()`:

```python
reading = dmm.measure_voltage_dc().values  # 4.98 +/- 0.05 V

if reading > 4.75:                        # compares 4.98 > 4.75
    print("nominal reading is above the limit")
```

A bare scalar is interpreted in the reading's unit. Comparisons between two
quantities convert compatible units, so `uq(1, 0.1, "V") == uq(1000, 20, "mV")`
is true because both nominal values are one volt. Uncertainty is not part of
operator comparisons.

For measurement acceptance, choose an explicit uncertainty-aware decision:

```python
reading.exceeds(4.75, k=2)          # complete expanded interval is above 4.75 V
reading.below(5.25, k=2)            # complete expanded interval is below 5.25 V
reading.consistent_with(5.0, k=2)   # agrees with 5.0 V within expanded uncertainty
comparison = reading.compare(4.75)  # auditable delta, uncertainty, direction, En ratio
```

Two quantities can have equal nominal values while carrying different uncertainty
representations. Use `left.same_representation(right)` only when you need to check
that their nominal value, unit spelling, gradient, and correlation registry are
identical; provenance and measurement-model metadata are outside that check.

## Get more help

Include the PyTestLab version, Python version, operating system, VISA backend, resource string with sensitive network details removed, profile key, and complete traceback when opening a [GitHub discussion](https://github.com/labiium/pytestlab/discussions) or issue.
