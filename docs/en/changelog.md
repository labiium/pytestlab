---
hide:
  - toc
---

# Changelog <a href="https://keepachangelog.com/en/1.0.0/" class="external-link" target="_blank"> </a>

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

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

[Unreleased]: https://github.com/labiium/pytestlab/compare/v0.2.4...HEAD
[v0.2.4]: https://github.com/labiium/pytestlab/compare/v0.2.3...v0.2.4
[0.1.5]: https://github.com/labiium/pytestlab/releases/tag/v0.1.5
[0.1.0]: https://github.com/labiium/pytestlab/releases/tag/v0.1.0
