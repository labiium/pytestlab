# Changelog

All notable changes to this project are documented in this file.

The format follows Keep a Changelog (https://keepachangelog.com/en/1.0.0/)
and the project adheres to Semantic Versioning (https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/labiium/pytestlab/compare/v0.2.4...HEAD
[v0.2.4]: https://github.com/labiium/pytestlab/compare/v0.2.3...v0.2.4
[v0.2.3]: https://github.com/labiium/pytestlab/compare/v0.2.1...v0.2.3
[v0.2.1]: https://github.com/labiium/pytestlab/compare/13b5439...v0.2.1
[0.1.3]: https://github.com/labiium/pytestlab/commit/13b5439
