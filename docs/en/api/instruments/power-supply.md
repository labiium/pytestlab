---
title: Power Supply
description: PyTestLab programmable power-supply channel, voltage, current, and output-control API.
---

# Power supply

The EDU36311A profile separates programmable limits from nominal measurement
ranges. Channel 1 accepts 0–6.18 V and 0.002–5.15 A; channels 2 and 3 accept
0–30.9 V and 0.001–1.03 A. Nominal ranges used by accuracy specifications and
calibration matching remain 6 V/5 A and 30 V/1 A respectively. These native
capabilities do not replace the DUT voltage/current caps in a bench descriptor.

Both `set_voltage`/`set_current` and `channel(...).set(...)` use the selected
channel's constraints. A combined voltage/current request validates both values
before either setting is written, including through a safety-limited bench
handle. Invalid native values raise `InstrumentParameterError`; descriptor cap
violations raise `SafetyLimitError`.

::: pytestlab.instruments.PowerSupply
