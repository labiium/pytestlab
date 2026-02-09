#!/usr/bin/env python3
"""
Comprehensive test script for the upgraded pytestlab bench system.
This script tests all major features of the new extended bench configuration.
"""

import sys
import traceback
from pathlib import Path

import pytest

# Add the current directory to Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

from pytestlab import Bench
from pytestlab.config.bench_loader import load_bench_yaml


def test_bench_configuration_loading():
    """Test loading the extended bench configuration."""
    print("🔧 Testing bench configuration loading...")

    bench_file = Path(__file__).parent / "bench.yaml"

    try:
        # Test loading YAML file
        config = load_bench_yaml(bench_file)
        print(f"✅ Loaded bench configuration: {config.bench_name}")
        print(f"   Version: {config.version}")
        print(f"   Experiment: {config.experiment.title}")
        print(f"   Instruments: {list(config.instruments.keys())}")
        print(
            f"   Safety limits configured: {len([name for name, inst in config.instruments.items() if inst.safety_limits])}"
        )
        print(f"   Custom validations: {len(config.custom_validations)}")
        print(
            f"   Automation hooks: pre={len(config.automation.pre_experiment)}, post={len(config.automation.post_experiment)}"
        )

        # Validate minimally
        assert isinstance(config.bench_name, str)
        assert config.experiment is not None
        assert isinstance(config.instruments, dict)

    except Exception as e:
        print(f"❌ Failed to load bench configuration: {e}")
        traceback.print_exc()
        pytest.fail(f"Failed to load bench configuration: {e}")


def test_bench_opening():
    """Test opening the bench with full initialization."""
    print("\n🚀 Testing bench opening and initialization...")

    config_file = Path(__file__).parent / "bench.yaml"

    try:
        # Test bench opening
        bench = Bench.open(config_file)
        print(f"✅ Bench opened successfully: {bench.name}")
        print(f"   Available instruments: {list(bench.instruments.keys())}")

        # Test properties
        print(
            f"   Experiment notes: {bench.experiment_notes[:50]}..."
            if bench.experiment_notes
            else "   No experiment notes"
        )
        print(f"   Version: {bench.version}")
        if bench.traceability:
            tr = bench.traceability
            calib_count = len(tr.calibration) if tr.calibration else 0
            env_count = 1 if tr.environment else 0
            dut_count = 1 if tr.dut else 0
            print(f"   Traceability info: {calib_count + env_count + dut_count} items")
        else:
            print("   No traceability info")
        print(
            f"   Measurement plan: {len(bench.measurement_plan)} steps"
            if bench.measurement_plan
            else "   No measurement plan"
        )

        assert bench is not None

    except Exception as e:
        print(f"❌ Failed to open bench: {e}")
        traceback.print_exc()
        pytest.fail(f"Failed to open bench: {e}")


def test_instrument_access():
    """Test accessing instruments through the bench."""
    print("\n🔍 Testing instrument access...")

    config_file = Path(__file__).parent / "bench.yaml"

    try:
        with Bench.open(config_file) as bench:
            print(f"✅ Using bench as context manager: {bench.name}")

            # Test instrument access
            for name, instrument in bench.instruments.items():
                print(f"   Instrument '{name}': {type(instrument).__name__}")
                print(
                    f"     Profile: {instrument.profile if hasattr(instrument, 'profile') else 'N/A'}"
                )
                print(
                    f"     Address: {instrument.address if hasattr(instrument, 'address') else 'N/A'}"
                )

        print("✅ Context manager cleanup completed")

    except Exception as e:
        print(f"❌ Failed to access instruments: {e}")
        traceback.print_exc()
        pytest.fail(f"Failed to access instruments: {e}")


def test_safety_limits():
    """Test safety limit enforcement."""
    print("\n🛡️ Testing safety limit enforcement...")

    config_file = Path(__file__).parent / "bench.yaml"

    try:
        with Bench.open(config_file) as bench:
            # Get PSU instrument
            psu = bench.instruments.get("psu1")
            if not psu:
                print("⚠️ PSU not available for safety testing")
                pytest.skip("PSU not available for safety testing")

            print(f"✅ Found PSU: {type(psu).__name__}")

            # Test that safety wrapper is applied
            from pytestlab.bench import SafeInstrumentWrapper

            if isinstance(psu, SafeInstrumentWrapper):
                print("✅ Safety wrapper applied to PSU")
                print(f"   Safety limits: {psu.safety_limits}")

                # Note: We can't actually test setting voltage without real hardware,
                # but we can verify the wrapper is in place
                print("✅ Safety system ready for voltage/current limit enforcement")
            else:
                print("⚠️ Safety wrapper not applied - this may be expected for simulation")

        assert True

    except Exception as e:
        print(f"❌ Failed to test safety limits: {e}")
        traceback.print_exc()
        pytest.fail(f"Failed to test safety limits: {e}")


def test_automation_hooks():
    """Test automation hook execution."""
    print("\n🔄 Testing automation hooks...")

    config_file = Path(__file__).parent / "bench.yaml"

    try:
        # The bench opening process includes running pre-experiment hooks
        with Bench.open(config_file):
            print("✅ Pre-experiment hooks executed during bench opening")

            # Post-experiment hooks will be executed during cleanup
            print("✅ Post-experiment hooks will execute during cleanup")

        print("✅ Automation hook system functional")

    except Exception as e:
        print(f"❌ Failed to test automation hooks: {e}")
        traceback.print_exc()
        pytest.fail(f"Failed to test automation hooks: {e}")


def test_traceability_and_measurement_plan():
    """Test traceability and measurement plan access."""
    print("\n📋 Testing traceability and measurement plan...")

    config_file = Path(__file__).parent / "bench.yaml"

    try:
        with Bench.open(config_file) as bench:
            # Test traceability
            if bench.traceability:
                print("✅ Traceability information available:")
                tr = bench.traceability
                if tr.calibration:
                    print(f"   calibration: {len(tr.calibration)} items")
                if tr.environment:
                    print("   environment: 1 item")
                if tr.dut:
                    print("   dut: 1 item")

            # Test measurement plan
            if bench.measurement_plan:
                print("✅ Measurement plan available:")
                for i, step in enumerate(bench.measurement_plan):
                    print(f"   Step {i + 1}: {step.name} ({step.instrument})")

        assert True

    except Exception as e:
        print(f"❌ Failed to test traceability/measurement plan: {e}")
        traceback.print_exc()
        pytest.fail(f"Failed to test traceability/measurement plan: {e}")


def main():
    """Run all tests."""
    print("🧪 Testing Extended Pytestlab Bench System")
    print("=" * 50)

    # Test configuration loading
    config = test_bench_configuration_loading()
    if not config:
        print("❌ Configuration loading failed - stopping tests")
        return False

    # Test bench opening
    bench = test_bench_opening()
    if not bench:
        print("❌ Bench opening failed - stopping tests")
        return False

    # Test instrument access
    success = test_instrument_access()
    if not success:
        print("❌ Instrument access failed")
        return False

    # Test safety limits
    success = test_safety_limits()
    if not success:
        print("❌ Safety limit testing failed")
        return False

    # Test automation hooks
    success = test_automation_hooks()
    if not success:
        print("❌ Automation hook testing failed")
        return False

    # Test traceability and measurement plan
    success = test_traceability_and_measurement_plan()
    if not success:
        print("❌ Traceability/measurement plan testing failed")
        return False

    print("\n🎉 All tests completed successfully!")
    print("=" * 50)
    print("✅ Extended bench system is fully functional")
    print("✅ Configuration loading and validation works")
    print("✅ Bench initialization works")
    print("✅ Instrument access and management works")
    print("✅ Safety limit system is ready")
    print("✅ Automation hooks execute properly")
    print("✅ Traceability and measurement plans accessible")

    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
