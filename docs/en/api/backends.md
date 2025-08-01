# Instrument Backends

PyTestLab supports multiple instrument communication backends, each designed for a specific class of hardware or simulation use case. This page documents the main backend classes and their roles.

---

## Overview

A **backend** is the low-level driver responsible for communicating with an instrument. Backends abstract the transport mechanism (VISA, Lamb, simulation, etc.) so that high-level instrument drivers can use a unified API.

Backends are typically not used directly by end-users. Instead, they are selected automatically based on your instrument profile, connection string, and simulation settings.

---

## Available Backends

### `AsyncVisaBackend`

Asynchronous backend for VISA-compatible instruments (e.g., GPIB, USB, TCPIP, RS232). Uses [PyVISA](https://pyvisa.readthedocs.io/) under the hood.

::: pytestlab.instruments.backends.async_visa_backend.AsyncVisaBackend

---

### `AsyncLambBackend`

Backend for instruments accessible via the [Lamb](https://github.com/e-a-olowe/lamb) remote instrument server protocol. Supports async TCP communication with Lamb daemons.

::: pytestlab.instruments.backends.lamb.AsyncLambBackend

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

- The `simulate` flag (in code or `bench.yaml`)
- The instrument's `address` (e.g., `"sim"` triggers simulation)
- The `backend` or `backend_defaults` fields in your configuration

You can override backend selection by specifying `backend_type_hint` when creating an instrument.

---

## Extending Backends

To add support for a new hardware interface, subclass `InstrumentBackendBase` and implement the required async methods (`open`, `close`, `write`, `query`, etc.). See the source code and existing backends for examples.

---

For more details on simulation, see the [Simulation Guide](../user_guide/simulation.md).