"""Read a synthetic scope capture through the CLI's strict replay backend."""


def main(bench):
    scope = bench.scope
    print(scope.id())
    print("Waveform preamble:", scope.query(":WAVeform:PREamble?"))
    trace = scope.query_raw(":WAVeform:DATA?")
    if not trace.startswith(b"#18") or len(trace) != 11:
        raise ValueError("Expected an IEEE 488.2 binblock carrying eight byte samples")
    print("Recorded ADC samples:", list(trace[3:]))
