# Waveform scientific contract

PyTestLab's oscilloscope workflow treats a waveform as a measurement result, not
just a numeric array.  The production contract is:

1. **Acquisition mode is explicit.** Read-only verification may adapt to the
   instrument's current state. Controlled acquisition may send setup commands but
   must record command intent and any state snapshot/restore status.
2. **Uncertainty is typed.** Internal waveform uncertainty uses
   `WaveformUncertaintyModel`, not unstructured metadata. Legacy metadata is
   accepted only at the I/O boundary and is converted immediately.
3. **Correlation is explicit.** Vertical gain, offset, and range terms are shared
   atoms across all samples. Quantization and independent noise are diagonal
   variance terms. Horizontal timebase/trigger terms are recorded and must be
   used by timing reductions before such reductions can be report-grade.
4. **Dense covariance is inspection-only.** Real waveform reductions propagate
   factored covariance directly; full covariance matrices are guarded for small
   diagnostic arrays only.
5. **Reductions resolve reportability.** Raw waveform arrays carry unresolved
   effective degrees of freedom; scalar reductions such as mean/RMS/Vpp resolve
   their own method or remain non-report-grade.
6. **Exports are evidence, not accreditation.** PyTestLab default XML is local
   software-validation evidence. DCC-named candidate output must fail loud until
   full pinned schema validation/signing exists outside this library.

This contract aligns the implementation with JCGM 100/101/102 and GUM-6 methods
while preserving the claim boundary that PyTestLab supports laboratory evidence
workflows but does not confer ISO/IEC 17025 accreditation or issue signed DCCs.
