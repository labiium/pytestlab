---
title: Instrument
description: Base lifecycle, transport, identity, and health API shared by PyTestLab instrument drivers.
---

# Instrument

`Instrument` defines the common lifecycle and communication behavior used by concrete drivers.

::: pytestlab.instruments.instrument.Instrument

## Self-test result

The generic `run_self_test()` returns text. Supported RF power meters return this structured result instead. A native code of zero means the instrument reports success.

::: pytestlab.instruments.self_test.InstrumentSelfTestResult
