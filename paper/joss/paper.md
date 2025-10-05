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
    affiliation: 1
  - name: Danial Chitnis
    affiliation: 1
affiliations:
  - name: The University of Edinburgh, UK
    index: 1
date: 4 October 2025
bibliography: paper.bib
---

# Summary

Modern hardware characterization workflows involve coordinating multiple laboratory instruments (power supplies, oscilloscopes, multimeters, electronic loads, signal sources), executing structured sweeps or time-based acquisition routines, persisting results, and ensuring traceability. These activities are often implemented via ad‑hoc Python scripts mixing raw SCPI commands with unstructured data handling and little or no provenance or compliance support.
PyTestLab is an extensible Python framework that unifies:

1. Bench configuration (YAML [@YAML-1.2.2]) with safety limits, automation hooks, calibration & DUT traceability.
2. A high-level `MeasurementSession` builder for declarative parameter sweeps or timed parallel acquisition loops with background stimulus tasks.
3. Pluggable instrument backends: VISA [@VPP-4_3; @VPP-4_3_2] and Lamb [@labiium_i2mtc_2025], advanced deterministic simulation, session recording, and strict replay (sequence validation).
4. Structured experiment and measurement data stored in Polars DataFrames [@polars] for efficient analytics and plotting.
5. A compliance layer providing cryptographic signing (ECDSA P‑256 [@FIPS-186-5; @SECG-SEC2-v2]), linked timestamp chains (ISO 18014-3 style [@ISOIEC-18014-3-2009; @HaberStornetta1991; @RFC3161]), audit trail logging, and persistent signature envelopes.
6. Lightweight plotting and FFT / frequency-response helpers for rapid feedback.

The framework enables reproducible, testable, and audit-ready measurement workflows suitable for both exploratory R&D and regulated environments. Step‑by‑step tutorials from basic to advanced are linked from the README.

# Statement of Need

PyTestLab addresses these gaps by coupling declarative bench specification (enabling infrastructural reproducibility) with a high-level acquisition API, while embedding compliance and integrity features by design rather than as afterthought plugins. Researchers, test engineers, and reliability or validation teams can therefore move from exploratory scripting to production-grade, provenance-rich pipelines without re‑architecting code.

Existing Python tooling—e.g., PyVISA [@pyvisa] and vendor SDKs—focuses on transport-level communication, leaving users to implement experiment orchestration, safety enforcement, provenance capture, and deterministic regression testing manually. Higher-level packages such as PyMeasure [@pymeasure] provide drivers and experiment scaffolding but typically do not offer deterministic command sequence replay coupled with integrated compliance primitives. In regulated or quality‑critical contexts (medical, aerospace, energy), requirements extend to tamper evidence, auditability of measurement changes, and controlled replay of prior sessions. No widely adopted open-source library in the instrumentation space currently integrates: (a) enforceable safety envelopes, (b) deterministic command sequence replay for validation, and (c) cryptographic measurement signing plus chained timestamp audit primitives — while also offering an ergonomic experiment builder and simulation layer.

# Features

- Bench System & Safety: YAML-defined instrument ensembles; per-channel limits (voltage, current, amplitude, frequency) enforced at runtime by a `SafeInstrumentWrapper`; pre/post automation hooks map directly to shell/Python commands and instrument “macros” executed by the Bench automation engine.
- Instrument Abstraction: Automatic profile-based instantiation; SCPI engine [@SCPI-1999]; command logging; backend polymorphism (VISA [@VPP-4_3; @VPP-4_3_2], Lamb [@labiium_i2mtc_2025], simulation, recording, replay).
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
  * Linked timestamp authority (hash chain) [@ISOIEC-18014-3-2009; @HaberStornetta1991]
  * Audit trail (SQLite [@SQLite]) binding envelopes to actions
  * Database persistence of envelopes for post‑hoc verification
- Extensibility: Clear boundaries (config, backends, drivers, compliance patching); user override path for simulation profiles; minimal monkey patch surface.
- Reproducibility & CI: Deterministic simulation plus replay => hardware‑free continuous integration, easier debugging of instrumentation logic.

# Design & Architecture

PyTestLab’s layered architecture separates “what to measure” from “how to communicate”:

1. Configuration Layer: Pydantic-backed models [@pydantic] parse bench YAML [@YAML-1.2.2], ensuring structural validation and enabling rich metadata (traceability, measurement plan, calibration references). Bench-defined safety limits are applied via a `SafeInstrumentWrapper` proxy, and automation hooks correspond to shell/Python commands and instrument macros that the bench executes in defined pre/post phases.
2. Instrument Core: A generic `Instrument` base encapsulates SCPI operations [@SCPI-1999], error queue handling, logging, communication timeouts, and binary block parsing; driver instances are created via an `AutoInstrument` factory selecting appropriate backend.
3. Backend Layer:
   - Simulation backend compiles SCPI dispatch tables (O(1) exact match + ordered regex fallback) and executes sandboxed state mutations.
   - Recording backend appends interaction logs and produces reproducible simulation profiles.
   - Replay backend enforces strict sequence determinism, supporting regression and audit scenarios.
4. Measurement Layer: `MeasurementSession` orchestrates cartesian parameter sweeps or interval-timed loops with parallel threads for stimulus tasks (e.g. PSU ramping, load pulsing). Acquisition functions return mapping objects merged into a growing structured dataset.
5. Data & Compliance: `MeasurementResult` is monkey‑patched at import to emit a signed envelope for every result. The envelope contains: the SHA‑256 [@FIPS-180-4] of a canonicalized payload (sorted‑key JSON of instrument, measurement_type, units, values_sha256, timestamp), an ECDSA P‑256 signature [@FIPS-186-5; @SECG-SEC2-v2] over that hash, the PEM‑encoded public key, an algorithm identifier, and a signature timestamp. Envelopes are persisted as JSON sidecars and in the database. A minimal linked time‑stamp authority maintains an append‑only hash chain (tsa.json) where each token stores idx, ts, sha_prev, sha_data, and sha_cum, enabling ISO 18014‑3–style verification [@ISOIEC-18014-3-2009; @HaberStornetta1991]. An append‑only audit trail (SQLite [@SQLite]) binds actor/action to each envelope hash and token index.
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
            scope.set_acquisition_time(1e-3)
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
- Cryptographic Envelopes: Each measurement result is hashed (SHA‑256 [@FIPS-180-4]) and signed (ECDSA P‑256 [@FIPS-186-5; @SECG-SEC2-v2]); envelopes include public key, signature, algorithm, and timestamp.
- Linked Time-Stamp Chain: Hash chaining of envelope digests produces a tamper-evident chronological ledger [@ISOIEC-18014-3-2009; @HaberStornetta1991; @RFC3161].
- Audit Trail: Append-only records (SQLite [@SQLite]) link actor, action, and envelope hash; chain verification supports compliance audits.

## Quality Assurance

PyTestLab emphasizes reliability and maintainability. Deterministic simulation and strict replay enable hardware-free continuous integration and regression testing of instrumentation logic. The codebase is type-annotated and checked with a static type checker; a linter enforces style and common bug patterns. Unit and smoke tests exercise configuration parsing, backends (simulation, recording, replay), core drivers, the measurement session builder, and compliance primitives. The minimum supported Python version is 3.11. Examples in the README run against the simulation backend and the replay harness to ensure they remain executable across releases. Releases are tagged with a changelog, and optional plotting dependencies are isolated behind an extra to keep the core lightweight.

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

## Related Work

Transport libraries such as PyVISA [@pyvisa] focus on low-level communication with instruments, leaving orchestration and provenance to users. Higher-level ecosystems like PyMeasure [@pymeasure] provide drivers and experiment scaffolding; however, deterministic command sequence replay and integrated compliance primitives (cryptographic signing plus a linked timestamp audit chain) remain uncommon. PyTestLab complements this landscape by combining declarative bench configuration, an ergonomic acquisition API, and compliance-by-design features with CI-friendly simulation and replay.

## Availability

PyTestLab is released under the Apache-2.0 license and targets Python ≥ 3.11. For reproducible installs at submission time, install from source:
pip install -e .
Optional plotting extras:
pip install -e '.[plot]'
When a published package is available, it can be installed via:
pip install pytestlab
Optional extras:
pip install 'pytestlab[plot]'
The command-line entry point (pytestlab) exposes utilities for profile inspection and record/replay workflows. Source code, issue tracking, and documentation are referenced from the project README.

# Citations

Inline citations refer to instrumentation, scientific Python, progress bars, uncertainty propagation, cryptography, DataFrame processing, and instrumentation tooling [@harris2020numpy; @hunter2007matplotlib; @tqdm2019; @uncertainties; @cryptography; @polars; @pyvisa; @pymeasure].

# Limitations & Future Work

- Expansion to more instrument support is planned for future releases.

# Acknowledgements

We acknowledge the open-source communities behind NumPy, Polars, Matplotlib, tqdm, uncertainties, and cryptography libraries whose foundational work enabled this project.

This work was produced under work funded by Keysight Technologies.

# References
