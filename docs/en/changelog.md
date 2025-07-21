---
hide:
  - toc
---

# Changelog <a href="https://keepachangelog.com/en/1.0.0/" class="external-link" target="_blank"> </a>

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added
- Initial migration to new documentation structure under `docs/en/`.
- Enhanced theme and navigation for multilingual and modern Material for MkDocs features.
- Improved simulation backend documentation and CLI reference.
- New API reference structure with detailed Pydantic model documentation.
- Bench descriptor and safety limit documentation improvements.

### Changed
- Home page and quick start rewritten for clarity and modern async-first focus.
- Installation instructions updated for clarity and VISA backend support.
- User guide reorganized for better onboarding and discoverability.
- Custom styles simplified for new theme.

### Fixed
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
- Async-first instrument API with facade pattern.
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

[Unreleased]: https://github.com/pytestlab/pytestlab/compare/v0.1.5...HEAD
[0.1.5]: https://github.com/pytestlab/pytestlab/releases/tag/v0.1.5
[0.1.0]: https://github.com/pytestlab/pytestlab/releases/tag/v0.1.0