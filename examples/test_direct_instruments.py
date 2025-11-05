"""
Direct instrument loading test for Smart Bench instruments.

This script demonstrates loading instruments directly without a bench configuration,
matching the user's original request:

    osc = await AutoInstrument.from_config("keysight/DSOX1204G")
    awg = await AutoInstrument.from_config("keysight/EDU33212A")
    psu = await AutoInstrument.from_config("keysight/EDU36311A")
    dmm = await AutoInstrument.from_config("keysight/EDU34450A")
"""

from pytestlab import AutoInstrument


def test_direct_instrument_loading():
    """Test loading all four instruments directly using AutoInstrument."""
    print("=" * 70)
    print("DIRECT INSTRUMENT LOADING TEST")
    print("=" * 70)

    # Load instruments in simulation mode
    print("\n1. Loading Oscilloscope (DSOX1204G)...")
    osc = AutoInstrument.from_config("keysight/DSOX1204G", simulate=True)
    print(f"   ✓ {osc.config.manufacturer} {osc.config.model}")
    print(f"   ID: {osc.id()}")

    print("\n2. Loading Waveform Generator (EDU33212A)...")
    awg = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
    print(f"   ✓ {awg.config.manufacturer} {awg.config.model}")
    print(f"   ID: {awg.id()}")

    print("\n3. Loading Power Supply (EDU36311A)...")
    psu = AutoInstrument.from_config("keysight/EDU36311A", simulate=True)
    print(f"   ✓ {psu.config.manufacturer} {psu.config.model}")
    print(f"   ID: {psu.id()}")

    print("\n4. Loading Multimeter (EDU34450A)...")
    dmm = AutoInstrument.from_config("keysight/EDU34450A", simulate=True)
    print(f"   ✓ {dmm.config.manufacturer} {dmm.config.model}")
    print(f"   ID: {dmm.id()}")

    print("\n" + "=" * 70)
    print("INSTRUMENT CAPABILITIES")
    print("=" * 70)

    # Oscilloscope
    print(f"\n📊 Oscilloscope: {osc.config.model}")
    print(f"   Channels: {len(osc.config.channels)}")
    print(f"   Bandwidth: {osc.config.bandwidth / 1e6} MHz")
    print(f"   Sampling Rate: {osc.config.sampling_rate / 1e9} GSa/s")
    print(f"   Memory Depth: {osc.config.memory}")

    # Waveform Generator
    print(f"\n🌊 Waveform Generator: {awg.config.model}")
    print(f"   Channels: {len(awg.config.channels)}")
    print(f"   Built-in Waveforms: {', '.join(awg.config.waveforms.built_in[:5])}...")
    ch1 = awg.config.channels[0]
    print(f"   Frequency Range: {ch1.frequency_range.min} - {ch1.frequency_range.max} Hz")
    print(f"   Amplitude Range: {ch1.amplitude_range.min} - {ch1.amplitude_range.max} V")

    # Power Supply
    print(f"\n⚡ Power Supply: {psu.config.model}")
    print(f"   Channels: {len(psu.config.channels)}")
    for i, ch in enumerate(psu.config.channels, 1):
        v_range = ch.voltage_range
        c_range = ch.current_limit_range
        v_min = getattr(v_range, "min", getattr(v_range, "min_val", 0))
        v_max = getattr(v_range, "max", getattr(v_range, "max_val", 0))
        c_min = getattr(c_range, "min", getattr(c_range, "min_val", 0))
        c_max = getattr(c_range, "max", getattr(c_range, "max_val", 0))
        print(f"   Channel {i}: {v_min}V to {v_max}V, {c_min}A to {c_max}A")

    # Multimeter
    print(f"\n📏 Multimeter: {dmm.config.model}")
    print(f"   Device Type: {dmm.config.device_type}")

    print("\n" + "=" * 70)
    print("✅ ALL INSTRUMENTS LOADED SUCCESSFULLY!")
    print("=" * 70)
    print("\nAll four instruments are ready for use:")
    print("  • osc: Oscilloscope for waveform capture")
    print("  • awg: Waveform generator for signal generation")
    print("  • psu: Power supply for DUT power")
    print("  • dmm: Multimeter for precision measurements")
    for inst in (osc, awg, psu, dmm):
        assert inst is not None


if __name__ == "__main__":
    # Run tests
    print("\n" + "█" * 70)
    print("█" + " " * 68 + "█")
    print("█" + "  SMART BENCH - DIRECT INSTRUMENT LOADING TEST".center(68) + "█")
    print("█" + " " * 68 + "█")
    print("█" * 70 + "\n")

    # Test: Direct loading
    instruments = test_direct_instrument_loading()

    print("\n" + "█" * 70)
    print("█" + " " * 68 + "█")
    print("█" + "  TEST COMPLETED SUCCESSFULLY!".center(68) + "█")
    print("█" + "  All instruments loaded and configured via simulation".center(68) + "█")
    print("█" + " " * 68 + "█")
    print("█" * 70 + "\n")
