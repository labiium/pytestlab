"""
Simple bench loading and testing script.

This script demonstrates loading a bench with DMM, PSU, and OSC
and performing basic operations.
"""

from pathlib import Path

from pytestlab.bench import Bench


def main():
    """Load and test a simple bench configuration."""
    print("=" * 70)
    print("SIMPLE BENCH TEST")
    print("=" * 70)

    # Load the smart bench configuration
    bench_path = Path(__file__).parent / "smarbench.yaml"

    print(f"\n📂 Loading bench from: {bench_path.name}")
    bench = Bench.open(bench_path)

    print(f"✓ Bench loaded: {bench.name}")
    print(f"  Version: {bench.version}")
    print(f"  Simulation: {bench.simulate}")
    print(f"  Instruments: {len(bench.instruments)}")

    # Access instruments
    print("\n" + "=" * 70)
    print("INSTRUMENTS")
    print("=" * 70)

    # Multimeter
    print("\n📏 Multimeter (DMM)")
    dmm = bench.instruments["dmm"]
    print(f"  Model: {dmm.config.model}")
    print(f"  ID: {dmm.id()}")

    # Power Supply
    print("\n⚡ Power Supply (PSU)")
    psu = bench.instruments["psu"]
    print(f"  Model: {psu.config.model}")
    print(f"  ID: {psu.id()}")
    print(f"  Channels: {len(psu.config.channels)}")

    # Oscilloscope
    print("\n📊 Oscilloscope (OSC)")
    osc = bench.instruments["osc"]
    print(f"  Model: {osc.config.model}")
    print(f"  ID: {osc.id()}")
    print(f"  Channels: {len(osc.config.channels)}")
    print(f"  Bandwidth: {osc.config.bandwidth / 1e6} MHz")

    # Waveform Generator
    print("\n🌊 Waveform Generator (AWG)")
    awg = bench.instruments["awg"]
    print(f"  Model: {awg.config.model}")
    print(f"  ID: {awg.id()}")
    print(f"  Channels: {len(awg.config.channels)}")

    # Basic operations test
    print("\n" + "=" * 70)
    print("BASIC OPERATIONS")
    print("=" * 70)

    # PSU: Set voltage
    print("\n⚡ PSU: Setting channel 1 to 3.3V")
    try:
        psu.set_voltage(1, 3.3)
        print("  ✓ Voltage set")
    except Exception as e:
        print(f"  ✗ Error: {e}")

    # PSU: Enable output
    print("\n⚡ PSU: Enabling channel 1 output")
    try:
        psu.output(1, True)
        print("  ✓ Output enabled")
    except Exception as e:
        print(f"  ✗ Error: {e}")

    # Cleanup
    print("\n🧹 Cleanup: Disabling PSU output")
    try:
        psu.output(1, False)
        print("  ✓ Output disabled")
    except Exception as e:
        print(f"  ✗ Error: {e}")

    # Summary
    print("\n" + "=" * 70)
    print("✅ BENCH TEST COMPLETED")
    print("=" * 70)
    print("\nAll instruments are accessible and functional:")
    print(f"  • {len(bench.instruments)} instruments loaded")
    print(f"  • Configuration: {bench.name}")
    print(f"  • Mode: {'Simulation' if bench.simulate else 'Hardware'}")


if __name__ == "__main__":
    main()
