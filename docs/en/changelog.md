---
hide:
  - toc
---

# Changelog <a href="https://keepachangelog.com/en/1.0.0/" class="external-link" target="_blank"> </a>

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## 0.3.0

- Store VNA, spectrum, RF power, and impedance results directly in experiments, the database, and ordinary sessions. Sessions with active compliance hooks do not support these results yet.
- Read saved trial captures with `experiment.measurements[name][0]`, including units, metadata, and any stored uncertainty.
- Support setup-specific VNA uncertainty budgets and conditional manufacturer uncertainty components for spectrum markers, RF power, and impedance. Unsupported conditions stay nominal.
- Add configurable averaging and triggering, diagnostics and guarded zeroing on U2000A and NRP18AN. Capture gated averages on U2000A and native buffers on NRP18AN.
- The six bundled Keysight scope profiles now bind `run_self_test()` to `*TST?` without changing its text result. Supported RF power sensors return a structured self-test result.
- Add RF input, detector, trigger and trace control, native marker and accumulation workflows, channel power and occupied bandwidth on N9000A and FSW26.
- Add held complex and scalar impedance-analyzer curves, tuning, drive readback and fixture correction status on E4990A and IM3570, with guarded fresh acquisition on E4990A.
- Read E5071C sweep settings, verify RF-off setup, and acquire one fresh linear or logarithmic stepped S-parameter sweep without enabling RF. Setup and acquisition are manual-backed and offline-tested, not hardware-qualified.
- Add manual-backed held complex trace readback for Copper Mountain C1209, plus named VNA traces, measured-bin lookup, and CSV export.
- Add grouped offline operation discovery, N9000A single- and multi-pair ACP, passive spectrum setup and aligned frames, RF sensor correction and trigger timing, staged NRP18AN readiness, impedance segment tables, fixture inspection, DataFrame/CSV export, and VNA segments, passive markers, and Touchstone export.
- Shared motion commands live under `ptl motion`. Camera capture, prober contact and separation, and motion commands use aliases from the bench. Existing root motion routes remain callable.
- Discover local VISA instruments with `ptl visa list` when using physical hardware.
- Configure cameras, motion devices, probers, switch matrices and instruments together through reusable Bench APIs. Camera access requires an exact resource address, regardless of how many cameras are attached.
- Use new native profiles for the Agilent 3458A (DC voltage), HP 4142B and HP4084B, SUSS PA200, and ToupTek camera. Profile inclusion is not a claim of physical qualification.
- On the PA200, relative XY moves use same-home position readback to check the final target against configured software travel limits before sending an absolute move. An acknowledgement still does not verify completion.
- Force built-in bench simulation with `ptl run --simulate` even when a device is configured as live. Unsupported entries or automation hooks are rejected; scripts are not sandboxed.
- Reset supported bench instruments with `Bench.reset()` or opt into `reset_on_open`. CLI diagnostics skip startup resets.
- `ptl instrument full-test` accepts a bench alias and its configured limits. It does not sample writes; eligible reads may acquire data or consume diagnostics.
- Inspect profile-declared operations and use native uncertainty, waveform timing and digital-twin evidence tools.
- Offline scope examples use a synthetic fixture or replay. Exported simulated benches can be recorded and replayed with their profile intact.
- Wafer-specific GDS, alignment and probing workflows are not bundled with the library.

## [v0.2.4] - 2026-05-12

### Added
- Added `ptl` as the preferred short CLI entry point while retaining the existing `pytestlab` command.
- Added instrument profile verification utilities and tests.
- Added CLI smoke and benchmark scripts for startup-sensitive command paths.
- Initial migration to new documentation structure under `docs/en/`.
- Enhanced theme and navigation for multilingual and modern Material for MkDocs features.
- Improved simulation backend documentation and CLI reference.
- New API reference structure with detailed Pydantic model documentation.
- Bench descriptor and safety limit documentation improvements.

### Changed
- Updated CLI documentation and examples to use `ptl` by default.
- Split the CLI into a lightweight bootstrap and lazy-loaded Typer implementation for faster common commands.
- Lazy-loaded selected package exports to reduce import-time overhead.
- Cleaned examples, compliance modules, and tests for Ruff and ty.
- Home page and quick start rewritten for clarity and improved onboarding.
- Installation instructions updated for clarity and VISA backend support.
- User guide reorganized for better onboarding and discoverability.
- Custom styles simplified for new theme.

### Fixed
- Fixed CLI help and option handling for bootstrap fast paths.
- Fixed compliance typing issues around generic callables and configuration dictionaries.
- Removed a tracked `.DS_Store` artifact.
- Navigation bugs and broken links in documentation.
- Outdated references to old profile and bench formats.

---

## [0.1.5] - 2024-06-01

### Added
- Support for YAML-driven simulation backend (SimBackend).
- Bench safety limits and automation hooks.
- CLI commands for profile and bench management.
- Initial support for uncertainty propagation using `uncertainties` package.

### Changed
- Simplified instrument API with facade pattern.
- Improved error handling and custom exception types.

### Fixed
- Various bugs in instrument connection and simulation logic.

---

## [0.1.0] - 2024-04-15

### Added
- First public release of PyTestLab.
- Core instrument drivers: Oscilloscope, PowerSupply, Multimeter, WaveformGenerator, DCActiveLoad.
- Profile-based configuration system.
- Database and experiment management modules.
- Basic simulation backend.

---

[v0.2.4]: https://github.com/labiium/pytestlab/compare/v0.2.3...v0.2.4
[0.1.5]: https://github.com/labiium/pytestlab/releases/tag/v0.1.5
[0.1.0]: https://github.com/labiium/pytestlab/releases/tag/v0.1.0
