"""Inspect fixture flags, summarize a held impedance sweep and export it."""

from pathlib import Path


def main(bench, output: Path = Path("impedance_sweep.csv")) -> None:
    analyzer = bench.impedance
    correction = analyzer.get_fixture_correction()
    print(
        f"Programmed fixture corrections (not a calibration check): "
        f"open={correction.open_enabled}, short={correction.short_enabled}, "
        f"load={correction.load_enabled}"
    )
    curve = analyzer.read_impedance_sweep()
    minimum = min(curve.readings, key=lambda sample: sample.magnitude_ohm)
    print(
        f"Held sweep: minimum sampled |Z| = {minimum.magnitude_ohm:.3g} ohm "
        f"at {minimum.frequency_hz:g} Hz"
    )
    curve.to_csv(output)
    print(f"Saved {len(curve.readings)} points to {output}")
