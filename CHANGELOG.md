# Changelog

All notable changes to this project are documented in this file.

The format follows Keep a Changelog (https://keepachangelog.com/en/1.0.0/)
and the project adheres to Semantic Versioning (https://semver.org/spec/v2.0.0.html).

## 0.3.0
### Added
- Store VNA, spectrum, RF power, and impedance results directly in experiments, the database, and ordinary sessions. Sessions with active compliance hooks do not support these results yet.
- Read saved trial captures with `experiment.measurements[name][0]`, including units, metadata, and any stored uncertainty.
- Support setup-specific VNA uncertainty budgets and conditional manufacturer uncertainty components for spectrum markers, RF power, and impedance. Unsupported conditions stay nominal.
- Reset supported bench instruments with `Bench.reset()` or opt into `reset_on_open`. CLI diagnostics skip startup resets.
- Add configurable averaging and triggering, diagnostics and guarded zeroing on U2000A and NRP18AN. Capture gated averages on U2000A and native buffers on NRP18AN.
- The six bundled Keysight scope profiles now bind `run_self_test()` to `*TST?` without changing its text result. Supported RF power sensors return a structured self-test result.
- Add RF input, detector, trigger and trace control, native marker and accumulation workflows, channel power and occupied bandwidth on N9000A and FSW26.
- Add held complex and scalar impedance-analyzer curves, tuning, drive readback and fixture correction status on E4990A and IM3570, with guarded fresh acquisition on E4990A.
- Read E5071C sweep settings, verify RF-off setup, and acquire one fresh linear or logarithmic stepped S-parameter sweep without enabling RF. Setup and acquisition are manual-backed and offline-tested, not hardware-qualified.
- Add manual-backed held complex trace readback for Copper Mountain C1209, plus named VNA traces, measured-bin lookup, and CSV export.
- Add grouped offline operation discovery, N9000A single- and multi-pair ACP, passive spectrum setup and aligned frames, RF sensor correction and trigger timing, staged NRP18AN readiness, impedance segment tables, fixture inspection, DataFrame/CSV export, and VNA segments, passive markers, and Touchstone export.
- Camera discovery does not require a manufacturer profile. Camera connections require the exact resource address even with one camera attached. USB resources identify the port.
- Transport-neutral camera, motion and robot capabilities, profile-driven probers, native switch matrices, and camera/motion/prober CLI commands.
- Native source-measure and multimeter profiles, and configurable transport framing and pacing.
- `ptl visa list` for optional local VISA discovery.
- ToupTek camera profile and native Agilent 3458A (DC voltage), HP 4142B/4084B and SUSS PA200 profiles; prior generic protocols remain available under explicit `_legacy` preset names.
- Digital-twin taxonomy and evidence tooling: validation-oracle labeling, characterized scope-twin gates, residual reports from replay/LAMB captures, and `pytestlab twin ...` CLI commands.
- Waveform timing uncertainty APIs for period, frequency, rise/fall time, duty cycle, delay, and shared-clock cross-channel skew.
- Quantity decision helpers (`compare`, `consistent_with`, `en_ratio`, `exceeds`, `below`, `within`) and report-grade convenience accessors.
- Set-bound `WaveformSetResult.channel(...)` views so natural cross-channel timing code preserves shared-clock covariance.
- Evidence bundle generation for JCGM/GUM rows, DCC/D-SI schema hashes, claim-boundary scans, and validation artifact indexes.
- QuantityArray oscilloscope waveform reductions with covariance-aware mean/RMS/Vpp helpers and D-SI / unsigned DCC-subset exports.
- Remote LAMB oscilloscope verification harness for MXR404A/HD304MSO, deterministic scope-twin known-truth evidence, and HD304MSO replay fixture parity checks.
- Citation metadata and explicit validation claim-boundary documentation.
- `ptl profile show --field` for compact JSON retrieval of nested YAML profile fields.

### Changed
- `ptl instrument full-test` accepts a bench alias and its configured limits. It does not sample writes; eligible reads may acquire data or consume diagnostics.
- Use `ptl motion position|move|status ALIAS` for shared motion operations, `ptl camera capture ALIAS` for capture, and `ptl prober contact|separate ALIAS` for prober-specific actions. Existing root motion routes remain callable.
- Results, persistence, accessories, power-supply, and DC-load paths now use
  PyTestLab's native uncertainty engine exclusively. Older serialized
  uncertainty payloads are migrated to native quantities when loaded.
- Advanced measurement tutorial notebook now passes Ruff's import-ordering and late-import checks.
- Scalar `Quantity` equality and ordering now use unit-aware nominal values for ordinary Python control flow. Use `same_representation(...)` for internal scalar-representation identity and the decision helpers for uncertainty-aware, guard-banded decisions.
- Missing measurement uncertainty metadata now returns an explicit nominal-only, non-report-grade `Quantity` instead of silently falling back to a bare float in normal acquisition paths; decision helpers warn on nominal-only non-report-grade values.
- Provenance now records data origin, evidence purpose, git SHA, profile/session hashes, and report-grade blockers for non-measured or incompatible evidence claims.
- Replay and session recording backends now preserve raw binary query payloads using base64 plus SHA-256 metadata.
- HD304MSO profile now includes read-only SCPI aliases required for LAMB validation.

### Fixed
- Read held Keysight E5071C S-parameter traces by verified instrument trace identity and actual frequency axis instead of assuming a combined trace buffer and reconstructed frequencies. The read-only path requires firmware A.09.60 or later in the A series and supported frequency/ASCII settings.
- Repair offline examples and preserve the profile when recording and replaying exported simulated benches.
- `ptl run --simulate` now forces supported built-in simulation for both bench entry formats or rejects the bench before loading the script. `ptl bench sim` exports a simulation-only descriptor. Neither is a Python sandbox.
- `ptl camera capture` requires an explicit bench alias; it no longer interprets an unknown alias as an output path.
- Register explicit GPIB addresses on LAMB without switching to a returned address; send research attribution only when enabled.
- Validate the final absolute destination for relative motion on bounded axes. The PA200 profile opts in for X and Y using same-home position readback; profiles without that declaration still reject bounded relative moves.
- `ptl bench validate --strict` checks bench validation rules and required LAMB camera addresses without opening hardware.
- Preserve deferred backend allocation across camera, motion and native instrument transports; capability inspection does not connect to hardware.
- MXR404A acquisition types now map normal/average to `AVERage OFF`/`ON`;
  peak detection is exposed through `ACQuire:MODE PDETect`, and the average-count
  helper checks semantic state instead of assuming a particular SCPI token.
- DSOX1202G, DSOX1204G, DSOX3054G and MSOX2024A waveform-generator
  output booleans now generate SCPI `ON`/`OFF` tokens.
- EDU33212A load impedance validates the documented 1–10000 ohm numeric
  range before I/O while preserving the explicit infinity and limit keywords.
- EDU34450A simulation now retains declared trigger-source settings, supports
  trigger-source readback, restores the immediate source on reset, and reports
  queued transport errors instead of a constant successful error response.
- EDU33212A simulation stores validated ASCII arbitrary-waveform samples, names,
  formats and point counts. Invalid samples leave previous state intact and
  remain in the native error queue until consumed; reset clears uploaded state.
- Scalar Quantity deserialization preserves explicitly null provenance without
  manufacturing a new identity; missing legacy provenance remains incomplete.

### Notes
- Camera, motion and prober APIs are reusable building blocks. Wafer-specific probing and GDS alignment workflows are not bundled, and these APIs do not imply physical prober qualification.
- PyTestLab validation artifacts are software-validation evidence, not accreditation certificates; issuing-lab DCC signing and ISO/IEC 17025 accreditation remain outside PyTestLab.


## [v0.2.4] - 2026-05-12
### Added
- Added `ptl` as the preferred short CLI entry point while keeping `pytestlab` as a compatibility alias.
- Added instrument profile verification utilities and CLI coverage for schema, connection, identity, SCPI, and safety-oriented probe checks.
- Added profile registry tests to lock built-in device type discovery.
- Added CLI smoke and benchmark scripts for startup and common command paths.

### Changed
- Split the heavy Typer CLI implementation into a lazy-loaded module so common CLI commands start faster.
- Updated documentation, examples, and scripts to use `ptl` by default.
- Lazy-loaded selected package exports in config, experiment, and instrument modules to reduce import-time overhead.
- Cleaned examples, compliance modules, and tests to pass the current Ruff and ty gates.

### Fixed
- Fixed CLI bootstrap dispatch so option-bearing commands such as `ptl profile show --help`, `ptl bench validate --help`, and `ptl profile list --profile-dir ...` fall through to Typer instead of being intercepted by fast paths.
- Fixed compliance typing issues around generic callables and configuration dictionaries.
- Removed the tracked `.DS_Store` artifact.

## [v0.2.3] - 2025-10-05
### Added
- Initial SCPI engine integration for instrument control.
- Comprehensive plotting utilities and examples.
- CLI enhancements for a better command-line experience.

### Changed
- Multimeter module overhaul with improved structure and behavior.
- Documentation site updates (MkDocs configuration and content).
- Type-checking and lint configuration refined (mypy and ruff) with project-wide cleanups.
- Pre-commit and CI adjustments to improve developer workflow and reliability.

### Fixed
- Type checking issues addressed across modules (targeted mypy fixes and cleaned ignores).
- Lint violations resolved with ruff adjustments.
- Release workflow corrections.

### Removed
- Full removal of legacy async code paths.

## [v0.2.1] - 2025-08-06
### Added
- Measurement sweeps and example workflows.
- Simulation v2 promoted and examples added.
- New instrument support and profiles (including MSOX2024A; PSU integration via SCPI).
- GUI and documentation site improvements; language support for docs/examples.

### Changed
- Significant test stabilization with “all tests passing” milestone and follow-up fixes.
- Documentation and notebooks improved; site build updated.
- Initial reduction/removal of legacy async components.

### Fixed
- Documentation site mobile menu behavior.
- CI workflows and packaging adjustments.
- Invalid or flaky tests removed/reworked.

## [0.1.3] - 2025-02-19
### Added
- DC Active Load instrument initial support and configuration scaffolding.

### Fixed
- Early integration fixes and stability improvements around DC Load support.

---

[v0.2.4]: https://github.com/labiium/pytestlab/compare/v0.2.3...v0.2.4
[v0.2.3]: https://github.com/labiium/pytestlab/compare/v0.2.1...v0.2.3
[v0.2.1]: https://github.com/labiium/pytestlab/compare/13b5439...v0.2.1
[0.1.3]: https://github.com/labiium/pytestlab/commit/13b5439
