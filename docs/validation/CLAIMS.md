# PyTestLab scientific validation claims

This document is the claim boundary for PyTestLab's metrology-facing evidence.
It separates validated software behavior from accreditation, certification, and
issuing-laboratory responsibilities.

## Validated software claims

PyTestLab may claim that its test suite currently validates these software
behaviors when the referenced evidence bundle was generated from a clean tree:

1. Scalar uncertainty arithmetic follows explicit first-order GUM propagation
   over a shared covariance atom space.
2. `QuantityArray` propagates waveform-scale diagonal and shared covariance for
   mean, RMS, integration, FFT, and explicit Monte Carlo peak-to-peak reduction.
3. Oscilloscope waveform reductions can export D-SI-compatible scalar payloads
   and an unsigned, locally validated PyTestLab DCC subset.
4. The cached schema baselines are DCC 3.3.0 and D-SI 2.2.1; their checksums are
   recorded in generated evidence manifests.
5. Remote LAMB hardware checks are opt-in and record command metadata, hashes,
   and skip/fail classification without silently turning hardware failures into
   scientific success.
6. Digital-twin and replay fixtures are validation evidence for software
   behavior and regression detection.

7. Oscilloscope waveform uncertainty follows the typed contract in
   `docs/validation/waveform_scientific_contract.md`: shared systematic atoms,
   diagonal independent terms, explicit acquisition mode, and fail-loud export
   boundaries.
8. Timing measurands such as period, frequency, rise/fall time, and duty cycle
   propagate voltage uncertainty through local edge slew rate and propagate
   horizontal timebase/trigger terms as explicit input quantities. Timing
   outputs without complete horizontal specifications remain labeled as
   non-report-grade candidates.

## Non-claims

PyTestLab is not an accredited calibration laboratory. PyTestLab evidence does not confer ISO/IEC 17025 accreditation, DCC certification, GUM certification, or legal metrological acceptance of a user's laboratory. Unsigned DCC XML emitted by
PyTestLab is a strict local subset for validation and data exchange experiments;
cryptographic signing, PKI, calibration authority, and final certificate issuance
remain the responsibility of the issuing laboratory.

## Required wording discipline

- Say "software-validation evidence" instead of "accreditation evidence".
- Say "unsigned DCC subset" instead of "DCC certificate" unless an issuing lab
  has signed and validated the full package with its own process.
- Say "D-SI-compatible payload" only when unit resolution succeeded.
- Say "report-grade candidate" only after provenance, traceability, model, unit,
  and uncertainty gates pass.
- Say "validation oracle" for synthetic known-truth twins unless a twin has a
  passing residual report and declared domain for a specific physical
  instrument identity.
