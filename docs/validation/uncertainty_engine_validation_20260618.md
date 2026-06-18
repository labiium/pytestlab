# PyTestLab Uncertainty Engine Validation Snapshot — 2026-06-18

This artifact records the validation boundary for the covariance-aware waveform
uncertainty work. It is a software-validation record, not an accreditation certificate. PyTestLab does not confer ISO/IEC 17025 accreditation.

## Framework pins

- JCGM 100:2008 and JCGM 102:2011 for GUM first-order and multivariate covariance propagation.
- JCGM 101:2008 for Monte Carlo propagation of nonlinear waveform reductions.
- JCGM 106:2012 and ILAC G8:09/2019 for uncertainty-aware conformity decision records.
- JCGM GUM-6:2020 for measurement-model adequacy and explicit model records.
- DCC schema baseline: PTB DCC 3.3.0, cached at `schemas/metrology/dcc-3.3.0/dcc.xsd`.
- D-SI schema baseline: D-SI 2.2.1, cached at `schemas/metrology/d-si-2.2.1/SI_Format.xsd`.

## Cached schema hashes

- DCC 3.3.0 `dcc.xsd`: `b8872150500d2d8bdd66817d27e7ee16b4df7037e803cf316483b98174a7f73f`
- D-SI 2.2.1 `SI_Format.xsd`: `10c3415fa1194357e3b181d5bd2413bf894594c01e3fa9e76c3b482db6c3d617`

## Validated software claims

1. `QuantityArray` stores waveform covariance as diagonal variance plus shared atom sensitivities.
2. Small waveform covariance matrices match a dense scalar-oracle construction.
3. Linear reductions emit scalar `Quantity` results with measurement-model metadata.
4. Peak-to-peak first-order propagation is explicitly marked non-report-grade unless Monte Carlo propagation is used.
5. Monte Carlo waveform reduction can draw from the factored covariance model and emit a `method="monte_carlo"` result.
6. `ChannelReadingResult.quantity(channel)` lazily constructs a `QuantityArray` without changing default `read_channels()` DataFrame behavior.
7. DCC/D-SI exports are unsigned and locally profile-validated; full issuing-lab XSD/signature validation remains outside PyTestLab.
8. Report-grade helpers block SI traceability claims unless provenance, model, unit, and traceability gates pass.

## Known limitations / non-claims

- PyTestLab is not an accredited calibration laboratory.
- Cached schema files are pinned for offline version/checksum/profile checks; complete DCC package validation may require additional imported XSD files and issuing-lab tooling.
- Real-hardware oscilloscope validation is optional and must be recorded separately for a specific lab/instrument/profile.
- Manufacturer datasheet uncertainty alone does not establish SI traceability.
- DCC XML emitted by PyTestLab is unsigned; signing and PKI are the issuing laboratory's responsibility.

## Required verification commands

```bash
uv run pytest tests/uncertainty/test_quantity_array_compliance.py tests/uncertainty/test_oscilloscope_quantity_array.py -q
uv run pytest tests/ -m 'not requires_real_hw' -q
uv run ruff check .
uv run ruff format --check pytestlab/ tests/ scripts/
uv run ty check
```
