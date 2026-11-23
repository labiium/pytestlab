# Instrument Backends

PyTestLab supports multiple instrument communication backends, each designed for a specific class of hardware or simulation use case. This page documents the main backend classes and their roles.

---

## Overview

A **backend** is the low-level driver responsible for communicating with an instrument. Backends abstract the transport mechanism (VISA, Lamb, simulation, etc.) so that high-level instrument drivers can use a unified API.

Backends are typically not used directly by end-users. Instead, they are selected automatically based on your instrument profile, connection string, and simulation settings.

---

## Available Backends

### `VisaBackend`

Synchronous backend for VISA-compatible instruments (e.g., GPIB, USB, TCPIP, RS232). Uses [PyVISA](https://pyvisa.readthedocs.io/) under the hood.

::: pytestlab.instruments.backends.visa_backend.VisaBackend

---

### `LambBackend`

Client backend for an existing compatible remote instrument transport. It uses synchronous HTTP and sends instrument addresses in the `resource_string` field. For explicit GPIB bindings it registers the exact resource string and rejects responses that do not confirm it. Ordinary requests do not send local script paths. Research attribution is enabled only by the TIM harness context or by explicitly setting `PYTESTLAB_TIM_ATTRIBUTION=1`; when enabled, attribution can include a local script path and line number in a header sent to the configured LAMB server.

::: pytestlab.instruments.backends.lamb.LambBackend

---

### `SimBackend`

The YAML-driven simulation backend for realistic instrument behavior.

::: pytestlab.instruments.backends.sim_backend.SimBackend

---

### `RecordingBackend`

A backend that wraps another backend and records all SCPI commands and responses. Used for generating simulation profiles and debugging.

::: pytestlab.instruments.backends.recording_backend.RecordingBackend

---

### `ReplayBackend` {#replaybackend}

Backend for replaying recorded instrument sessions with strict sequence validation. Used for reproducible measurements and regression testing.

::: pytestlab.instruments.backends.replay_backend.ReplayBackend

---

### `SessionRecordingBackend` {#sessionrecordingbackend}

Backend that wraps real instrument backends to record all interactions for later replay. Used in conjunction with ReplayBackend for record-and-replay workflows.

::: pytestlab.instruments.backends.session_recording_backend.SessionRecordingBackend

---

## Backend Selection Logic

PyTestLab chooses the backend automatically based on:

- Set `simulate=True` in the factory, or set `simulate: true` in the bench or
  its device entry, to use a compatible simulator. A device setting can override
  the bench's default. The `address` string alone does not enable simulation.
- For live I/O, set the backend type and address explicitly on the bench
  entry or device profile. Direct factory calls can supply `backend_type_hint`
  and `address_override`.
- For an offline CLI run with PyTestLab-managed transports, use
  `ptl run --simulate`. It rejects unsupported devices or hooks and does not
  sandbox your Python script.

---

## Extending Backends

To add support for a new hardware interface, implement the `InstrumentIO` protocol (synchronous methods such as `connect`, `disconnect`, `write`, `query`, etc.). See the source code and existing backends for examples.

---

For more details on simulation, see the [Simulation Guide](../user_guide/simulation.md).
