---
title: 'PyTestLab: A Reproducible, Compliance-Aware Python Framework for Electronic Test & Measurement'
tags:
  - Python
  - instrumentation
  - laboratory automation
  - data provenance
  - reproducibility
  - compliance
authors:
  - name: Emmanuel A. Olowe
    orcid: 0009-0005-3172-1948
    corresponding: true
    affiliation: "1"
  - name: Danial Chitnis
    affiliation: "2"
affiliations:
  - name: The University of Edinburgh, UK
    index: 1
date: 16 August 2025
bibliography: paper.bib
---

# Summary

Modern hardware characterization workflows involve coordinating multiple laboratory instruments (power supplies, oscilloscopes, multimeters, electronic loads, signal sources), executing structured sweeps or time-based acquisition routines, persisting results, and ensuring traceability. These activities are often implemented via ad‑hoc Python scripts mixing raw SCPI commands with unstructured data handling and little or no provenance or compliance support.
PyTestLab is an extensible Python framework that unifies:

1. Bench configuration (YAML) with safety limits, automation hooks, calibration & DUT traceability.
2. A high-level `MeasurementSession` builder for declarative parameter sweeps or timed parallel acquisition loops with background stimulus tasks.
3. Pluggable instrument backends: real (VISA or vendor), advanced deterministic simulation, session recording, and strict replay (sequence validation).
4. Structured experiment and measurement data stored in Polars DataFrames for efficient analytics and plotting.
5. A compliance layer providing cryptographic signing (ECDSA P‑256), linked timestamp chains (ISO 18014-3 style), audit trail logging, and persistent signature envelopes.
6. Lightweight plotting and FFT / frequency-response helpers for rapid feedback.

The framework enables reproducible, testable, and audit-ready measurement workflows suitable for both exploratory R&D and regulated environments.

# Statement of Need

Existing Python tooling (e.g. PyVISA, vendor SDKs) focuses on transport-level communication, leaving users to implement experiment orchestration, safety enforcement, provenance capture, and deterministic regression testing manually. In regulated or quality‑critical contexts (medical, aerospace, energy), requirements extend to tamper evidence, auditability of measurement changes, and controlled replay of prior sessions. No widely adopted open-source library in the instrumentation space currently integrates: (a) enforceable safety envelopes, (b) deterministic command sequence replay for validation, and (c) cryptographic measurement signing plus chained timestamp audit primitives — while also offering an ergonomic experiment builder and simulation layer.

PyTestLab addresses these gaps by coupling declarative bench specification (enabling infrastructural reproducibility) with a high-level acquisition API, while embedding compliance and integrity features by design rather than as afterthought plugins. Researchers, test engineers, and reliability or validation teams can therefore move from exploratory scripting to production-grade, provenance-rich pipelines without re‑architecting code.

# Features

- Bench System & Safety: YAML-defined instrument ensembles; per-channel limits (voltage, current, amplitude, frequency); pre/post automation macros (shell, Python, instrument “macros”).
- Instrument Abstraction: Automatic profile-based instantiation; SCPI engine; command logging; backend polymorphism (simulation, recording, replay, live).
- Simulation Backend: YAML-driven state machine with regex/glob dispatch, sandboxed expressions, error queue emulation, artificial timing, deterministic behavior for CI.
- Recording & Replay: Recording backend generates enriched simulation profile; replay backend enforces exact SCPI sequence (raises on divergence) ensuring regression fidelity.
- MeasurementSession Builder:
  * Declarative parameter registration
  * Decorator-based acquisition functions
  * Parallel background tasks (stimulus) + foreground acquisition loop
  * Automatic Experiment aggregation (Polars DataFrame)
- Data & Analysis: `MeasurementResult` objects (scalar, array, waveform, DataFrame) with FFT and plotting convenience; experiment-level plotting.
- Compliance Layer:
  * Measurement hashing and ECDSA signing
  * Linked timestamp authority (hash chain)
  * Audit trail (SQLite) binding envelopes to actions
  * Database persistence of envelopes for post‑hoc verification
- Extensibility: Clear boundaries (config, backends, drivers, compliance patching); user override path for simulation profiles; minimal monkey patch surface.
- Reproducibility & CI: Deterministic simulation plus replay => hardware‑free continuous integration, easier debugging of instrumentation logic.

# Design & Architecture

PyTestLab’s layered architecture separates “what to measure” from “how to communicate”:

1. Configuration Layer: Pydantic-backed models parse bench YAML, ensuring structural validation and enabling rich metadata (traceability, measurement plan, calibration references).
2. Instrument Core: A generic `Instrument` base encapsulates SCPI operations, error queue handling, logging, communication timeouts, and binary block parsing; driver instances are created via an `AutoInstrument` factory selecting appropriate backend.
3. Backend Layer:
   - Simulation backend compiles SCPI dispatch tables (O(1) exact match + ordered regex fallback) and executes sandboxed state mutations.
   - Recording backend appends interaction logs and produces reproducible simulation profiles.
   - Replay backend enforces strict sequence determinism, supporting regression and audit scenarios.
4. Measurement Layer: `MeasurementSession` orchestrates cartesian parameter sweeps or interval-timed loops with parallel threads for stimulus tasks (e.g. PSU ramping, load pulsing). Acquisition functions return mapping objects merged into a growing structured dataset.
5. Data & Compliance: `MeasurementResult` instances are transparently patched at import time to generate cryptographic envelopes; the database layer stores signed artifacts. The audit trail uses a linked hash chain of timestamp tokens enabling tamper detection.
6. Analytics & Plotting: Lightweight wrappers centralize plotting semantics while deferring heavy analytics to established libraries.

# Example Usage (Conceptual)

```text
with Bench.open("bench.yaml") as bench:
    with Measurement(bench=bench) as session:
        session.parameter("voltage", [1.0, 2.0, 3.3], unit="V")
        session.parameter("frequency", [10e3, 50e3], unit="Hz")

        @session.acquire
        def capture(psu, scope, voltage, frequency):
            psu.channel(1).set(voltage=voltage)
            scope.set_timebase(1e-3)
            waveform = scope.read_channels(1)
            vpp = scope.measure_voltage_peak_to_peak(1)
            return {"vpp": vpp.values, "waveform": waveform.values}

        experiment = session.run()
        experiment.plot(title="Vpp vs Parameters")
```

Replay-mode regression test (abbreviated):

```text
psu = AutoInstrument.from_config("keysight/EDU36311A",
                                 backend_override=ReplayBackend(session_log, "psu"))
psu.connect_backend()
psu.set_voltage(1, 5.0)  # Raises if sequence diverges.
```

# Reproducibility & Integrity

- Deterministic Replay: Ensures that test scripts remain protocol-stable; any deviation indicates unintentional behavioral drift.
- Cryptographic Envelopes: Each measurement result is hashed and signed; envelopes include public key, signature, algorithm, and timestamp.
- Linked Time-Stamp Chain: Hash chaining of envelope digests produces a tamper-evident chronological ledger.
- Audit Trail: Append-only records link actor, action, and envelope hash; chain verification supports compliance audits.

# Comparison to Existing Tools

| Aspect | PyTestLab | PyVISA / Low-level Drivers | Ad-hoc Scripts | Proprietary Lab Suites |
|--------|-----------|----------------------------|---------------|------------------------|
| Declarative Bench Config | Yes | No | No | Partial |
| Deterministic Replay | Yes | No | No | Rare |
| Cryptographic Signing | Built-in | No | No | Rare / add-on |
| Linked Timestamping | Built-in | No | No | Rare |
| Simulation (Declarative) | Advanced YAML state machine | Minimal | Manual mocks | Varies |
| Parallel Acquisition Tasks | Yes | Manual threads | Manual threads | Varies |
| Structured Data (Polars) | Native | External | Optional | Varies |

# Citations

Inline citations refer to instrumentation, scientific Python, progress bars, uncertainty propagation, cryptography, and DataFrame processing [@harris2020numpy; @hunter2007matplotlib; @tqdm; @uncertainties; @cryptography; @polars].

# Limitations & Future Work

- Expansion to more instrument support is planned for future releases.

# Acknowledgements

We acknowledge the open-source communities behind NumPy, Polars, Matplotlib, tqdm, uncertainties, and cryptography libraries whose foundational work enabled this project.

This work was produced under work funded by Keysight Technologies.

# References
