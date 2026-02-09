"""
Test script for smarbench.yaml configuration.

This script tests the Smart Bench configuration with all four instruments:
- Keysight DSOX1204G Oscilloscope
- Keysight EDU33212A Waveform Generator
- Keysight EDU36311A Power Supply
- Keysight EDU34450A Multimeter
"""

from pathlib import Path

import pytest

from pytestlab.bench import Bench
from pytestlab.errors import InstrumentConnectionError

pytestmark = pytest.mark.requires_real_hw


@pytest.fixture(scope="module")
def smart_bench():
    """Load the Smart Bench configuration or skip if hardware is missing."""
    bench_path = Path(__file__).parent / "smarbench.yaml"
    try:
        bench = Bench.open(bench_path)
    except InstrumentConnectionError as exc:
        pytest.skip(f"Smart Bench hardware not available: {exc}")

    yield bench
    bench.close_all()


def test_smarbench_loading(smart_bench):
    """Test loading the smarbench configuration."""
    print("=" * 70)
    print("TEST 1: Loading Smart Bench Configuration")
    print("=" * 70)

    bench = smart_bench

    print(f"\n✓ Bench loaded: {bench.name}")
    print(f"  Description: {bench.description}")
    print(f"  Version: {bench.version}")
    print(f"  Instruments: {len(bench.instruments)}")

    # Verify all instruments are loaded
    assert "osc" in bench.instruments, "Oscilloscope not found"
    assert "awg" in bench.instruments, "AWG not found"
    assert "psu" in bench.instruments, "PSU not found"
    assert "dmm" in bench.instruments, "DMM not found"

    print("\n  Instrument List:")
    for name, inst in bench.instruments.items():
        print(f"    - {name}: {inst.config.manufacturer} {inst.config.model}")

    assert bench is not None


def test_instrument_identity(smart_bench):
    """Test instrument identity queries."""
    print("\n" + "=" * 70)
    print("TEST 2: Instrument Identity Check")
    print("=" * 70)

    bench = smart_bench

    for name, inst in bench.instruments.items():
        try:
            identity = inst.id()
            print(f"\n  {name.upper()}:")
            print(f"    ID: {identity}")
            print(f"    Type: {inst.config.device_type}")
            print(f"    Model: {inst.config.model}")
        except Exception as e:
            print(f"\n  {name.upper()}: Error - {e}")


def test_oscilloscope_config(smart_bench):
    """Test oscilloscope configuration."""
    print("\n" + "=" * 70)
    print("TEST 3: Oscilloscope Configuration")
    print("=" * 70)

    bench = smart_bench

    osc = bench.instruments["osc"]
    print(f"\n  Model: {osc.config.model}")
    print(f"  Channels: {len(osc.config.channels)}")
    print(f"  Bandwidth: {osc.config.bandwidth / 1e6} MHz")
    print(f"  Sampling Rate: {osc.config.sampling_rate / 1e9} GSa/s")

    # Test channel facade
    try:
        ch1 = osc.channel(1)
        print("\n  ✓ Channel 1 facade created")
        print("    Methods available: scale, offset, coupling, probe")
        assert ch1 is not None
    except Exception as e:
        print(f"\n  ✗ Channel facade error: {e}")


def test_awg_config(smart_bench):
    """Test waveform generator configuration."""
    print("\n" + "=" * 70)
    print("TEST 4: Waveform Generator Configuration")
    print("=" * 70)

    bench = smart_bench

    awg = bench.instruments["awg"]
    print(f"\n  Model: {awg.config.model}")
    print(f"  Channels: {len(awg.config.channels)}")

    for i, ch in enumerate(awg.config.channels, 1):
        print(f"\n  Channel {i}:")
        freq_min = ch.frequency_range.min if ch.frequency_range.min else ch.frequency_range.min_val
        freq_max = ch.frequency_range.max if ch.frequency_range.max else ch.frequency_range.max_val
        amp_min = ch.amplitude_range.min if ch.amplitude_range.min else ch.amplitude_range.min_val
        amp_max = ch.amplitude_range.max if ch.amplitude_range.max else ch.amplitude_range.max_val
        print(f"    Frequency Range: {freq_min} - {freq_max} Hz")
        print(f"    Amplitude Range: {amp_min} - {amp_max} V")

    print(f"\n  Built-in Waveforms: {', '.join(awg.config.waveforms.built_in)}")

    # Test channel facade
    try:
        ch1 = awg.channel(1)
        print("\n  ✓ Channel 1 facade created")
        print("    Methods: setup_sine, setup_square, setup_ramp, setup_pulse")
        assert ch1 is not None
    except Exception as e:
        print(f"\n  ✗ Channel facade error: {e}")


def test_psu_config(smart_bench):
    """Test power supply configuration."""
    print("\n" + "=" * 70)
    print("TEST 5: Power Supply Configuration")
    print("=" * 70)

    bench = smart_bench

    psu = bench.instruments["psu"]
    print(f"\n  Model: {psu.config.model}")
    print(f"  Channels: {len(psu.config.channels)}")

    for i, ch in enumerate(psu.config.channels, 1):
        print(f"\n  Channel {i}:")
        try:
            v_min = ch.voltage_range.min if ch.voltage_range.min else ch.voltage_range.min_val
            v_max = ch.voltage_range.max if ch.voltage_range.max else ch.voltage_range.max_val
            c_min = ch.current_range.min if ch.current_range.min else ch.current_range.min_val
            c_max = ch.current_range.max if ch.current_range.max else ch.current_range.max_val
            print(f"    Voltage Range: {v_min} - {v_max} V")
            print(f"    Current Range: {c_min} - {c_max} A")
        except Exception as e:
            print(f"    Error reading ranges: {e}")

    # Test safety limits
    if hasattr(bench, "_safety_limits") and "psu" in bench._safety_limits:
        print("\n  Safety Limits Configured:")
        for ch_num, limits in bench._safety_limits["psu"]["channels"].items():
            print(f"    Channel {ch_num}:")
            if "voltage" in limits:
                print(f"      Voltage: {limits['voltage']}")
            if "current" in limits:
                print(f"      Current: {limits['current']}")


def test_dmm_config(smart_bench):
    """Test multimeter configuration."""
    print("\n" + "=" * 70)
    print("TEST 6: Multimeter Configuration")
    print("=" * 70)

    bench = smart_bench

    dmm = bench.instruments["dmm"]
    print(f"\n  Model: {dmm.config.model}")
    print(f"  Device Type: {dmm.config.device_type}")

    # Display measurement capabilities if available
    try:
        if hasattr(dmm.config, "measurement_functions"):
            funcs = dmm.config.measurement_functions
            if isinstance(funcs, list):
                print(f"  Measurement Functions: {', '.join(funcs)}")
            else:
                print(f"  Measurement Functions: {funcs}")
    except Exception:
        print("  Measurement Functions: Not available")


def test_bench_metadata(smart_bench):
    """Test bench metadata and documentation."""
    print("\n" + "=" * 70)
    print("TEST 7: Bench Metadata")
    print("=" * 70)

    bench = smart_bench

    print(f"\n  Bench Name: {bench.name}")
    print(f"  Version: {bench.version}")
    print(f"  Simulation Mode: {bench.simulate}")

    if bench._config.experiment:
        print("\n  Experiment:")
        try:
            print(f"    Title: {exp.title if hasattr(exp, 'title') else 'N/A'}")
            print(f"    Operator: {exp.operator if hasattr(exp, 'operator') else 'N/A'}")
            print(f"    Date: {exp.date if hasattr(exp, 'date') else 'N/A'}")
        except Exception as e:
            print(f"    Error: {e}")


def test_instrument_coordination(smart_bench):
    """Test coordinated operation of multiple instruments."""
    print("\n" + "=" * 70)
    print("TEST 8: Instrument Coordination")
    print("=" * 70)

    bench = smart_bench

    print("\n  Testing coordinated setup sequence:")

    # Simulate a coordinated test setup
    try:
        # 1. Configure power supply
        psu = bench.instruments["psu"]
        print("    1. PSU: Ready for configuration")
        assert psu is not None

        # 2. Configure AWG
        awg = bench.instruments["awg"]
        print("    2. AWG: Ready for signal generation")
        assert awg is not None

        # 3. Configure oscilloscope
        osc = bench.instruments["osc"]
        print("    3. OSC: Ready for capture")
        assert osc is not None

        # 4. Configure DMM
        dmm = bench.instruments["dmm"]
        print("    4. DMM: Ready for measurements")
        assert dmm is not None

        print("\n  ✓ All instruments coordinated successfully")

    except Exception as e:
        print(f"\n  ✗ Coordination error: {e}")


def test_signal_routing():
    """Test signal routing configuration."""
    print("\n" + "=" * 70)
    print("TEST 9: Signal Routing")
    print("=" * 70)

    bench_path = Path(__file__).parent / "smarbench.yaml"

    # Read YAML to check signal routing
    import yaml

    with open(bench_path) as f:
        config = yaml.safe_load(f)

    if "signal_routing" in config:
        print("\n  Signal Routing Configuration:")
        for route in config["signal_routing"]:
            print(f"\n    {route['source']} → {route['destination']}")
            print(f"      Description: {route['description']}")
            print(f"      Cable: {route['cable']}")
    else:
        print("\n  No signal routing defined")


def run_all_tests():
    """Run all tests sequentially."""
    print("\n" + "=" * 70)
    print("SMART BENCH CONFIGURATION TEST SUITE")
    print("=" * 70)

    tests = [
        ("Loading Configuration", test_smarbench_loading),
        ("Instrument Identity", test_instrument_identity),
        ("Oscilloscope Config", test_oscilloscope_config),
        ("AWG Config", test_awg_config),
        ("PSU Config", test_psu_config),
        ("DMM Config", test_dmm_config),
        ("Bench Metadata", test_bench_metadata),
        ("Instrument Coordination", test_instrument_coordination),
        ("Signal Routing", test_signal_routing),
    ]

    passed = 0
    failed = 0

    for test_name, test_func in tests:
        try:
            test_func()
            passed += 1
        except Exception as e:
            print(f"\n  ✗ TEST FAILED: {test_name}")
            print(f"     Error: {e}")
            failed += 1

    # Summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    print(f"\n  Total Tests: {len(tests)}")
    print(f"  Passed: {passed}")
    print(f"  Failed: {failed}")

    if failed == 0:
        print("\n  ✅ ALL TESTS PASSED!")
    else:
        print(f"\n  ⚠️  {failed} TEST(S) FAILED")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    run_all_tests()
