# Digital Twins and Oscilloscope Evidence

PyTestLab uses the term **digital twin** conservatively. A simulator or
known-truth harness is not automatically a twin of a physical instrument.
Evidence must say what produced the data and what claim the artifact supports.

## Three Evidence Classes

| Class | `data_origin` | `evidence_purpose` | What it can prove |
| --- | --- | --- | --- |
| Known-truth oracle | `twin_oracle` or `synthetic_known_truth` | `software_validation` | PyTestLab algorithms bracket a deterministic truth case. |
| Replay fixture | `replayed` | `replay_regression` | Decoder, reduction, hash, and evidence pipelines are stable in CI. |
| Characterized twin residual | `measured` or `replayed` | `twin_validation` | A declared model matches a declared instrument/domain within residual limits. |

Only the last class can support a `CharacterizedScopeTwin`, and even then the
claim is domain-limited validation evidence. It is not an ISO/IEC 17025
calibration certificate and not a signed DCC.

## Run the Scope Oracle

Use the oracle when you want a low-burden software validation check:

```bash
pytestlab twin oracle --output .omx/evidence/twin-oracle --mc-samples 3000 --check
```

This writes the same tamper-checkable known-truth artifacts as
`pytestlab evidence scope-twin`, but the CLI wording makes the claim boundary
clear: this validates waveform algorithms against synthetic truth; it does not
characterize an MXR404A or HD304MSO unit.

## Build a Residual Report From a Replay Fixture

Replay fixtures carry redacted instrument identity, command transcript hashes,
waveform hashes, expected metrics, fixture classification, and reduction
metrics. Convert a fixture to residual evidence with:

```bash
pytestlab twin residual-from-replay tests/fixtures/hardware_replay/hd304mso_lamb_capture.json \
  --output .omx/evidence/twin-residual \
  --check
```

If the fixture classification is `fixture_integrity`, PyTestLab labels the
report as `replay_regression`. That is intentional: self-consistency replay is
valuable CI evidence, but it must not be confused with a characterized hardware
twin.

A fixture classified as `independent_parity` can become `twin_validation`
evidence when its expected metrics come from a pinned known-truth source,
calibrated model, or characterized-twin prediction.

## Create Characterized Scope Evidence

A characterized scope twin requires a passing residual report whose purpose is
`twin_validation`:

```bash
pytestlab twin characterize-scope .omx/evidence/twin-residual/twin_residual_report.json \
  --output .omx/evidence/characterized-scope \
  --check
```

PyTestLab refuses to characterize from replay-regression evidence. This keeps a
common failure mode out of the user path: a self-consistency fixture cannot be
accidentally marketed as an instrument twin.

## Live LAMB Capture Residuals

The Python API can also turn a LAMB waveform-capture report into measured
hardware-vs-expected residual evidence when the caller supplies expected metrics.
The safe default is `evidence_purpose="replay_regression"`; that labels the
artifact as a reproducible software/hardware replay check and prevents accidental
characterized-twin claims.

```python
from pytestlab.twin import residual_report_from_lamb_capture

report = residual_report_from_lamb_capture(
    ".omx/evidence/lamb/lamb_scope_check.json",
    model="MXR404A",
    expected_metrics={
        "rms": {"nominal": 1.001, "standard_uncertainty": 0.01, "unit": "V"},
        "mean": {"nominal": 0.0, "standard_uncertainty": 0.01, "unit": "V"},
    },
)
assert report.evidence_purpose == "replay_regression"
```

Use `evidence_purpose="twin_validation"` only when the expected metrics are
independent of the capture under test: for example, a pinned known-truth source,
a calibrated reference model, or a previously characterized twin prediction.

```python
report = residual_report_from_lamb_capture(
    ".omx/evidence/lamb/lamb_scope_check.json",
    model="MXR404A",
    expected_metrics=independent_expected_metrics,
    evidence_purpose="twin_validation",
)
```

The resulting report is still validation evidence, not a calibration result or a
signed DCC.

## User-Facing API

For ordinary oscilloscope users, the ergonomic path stays short:

```python
wave = scope.acquire_waveform(1)
rms = wave.rms()
freq = wave.timing.frequency()

waves = scope.acquire_waveforms([1, 2])
skew = waves.skew(1, 2)

scope.twin.validate(".omx/evidence/twin-oracle", kind="oracle")
```

Underneath, those objects carry provenance, covariance atoms, evidence-purpose
labels, and reportability gates so users do not have to manually manage JCGM
bookkeeping for routine work.
