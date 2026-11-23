"""Acquire and plot a synthetic waveform; no instrument or SPICE required."""

from pathlib import Path

from pytestlab import AutoInstrument


def main():
    profile = Path(__file__).with_name("scope.yaml")
    scope = AutoInstrument.from_file(profile, simulate=True)
    try:
        result = scope.read_channels(1)
        print(result.values.head())
        result.plot().savefig("synthetic_scope.png")
    finally:
        scope.close()


if __name__ == "__main__":
    main()
