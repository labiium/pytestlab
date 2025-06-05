#!/usr/bin/env python3
"""
Example usage of the new PyTestLab Bench system.

This script demonstrates:
- Loading a bench configuration with extended features
- Accessing instruments through the bench
- Safety limit enforcement
- Accessing experiment metadata and traceability
- Using automation hooks
"""

import asyncio
from pathlib import Path
from pytestlab.bench import Bench, SafetyLimitError

async def main():
    """Main example function."""
    bench_file = Path(__file__).parent / "bench.yaml"
    
    try:
        # Open the bench configuration asynchronously
        # This will:
        # 1. Load and validate the YAML configuration
        # 2. Run custom validations
        # 3. Initialize all instruments
        # 4. Run pre-experiment automation hooks
        async with await Bench.open(bench_file) as bench:
            print(f"✅ Bench '{bench.config.bench_name}' loaded successfully")
            print(f"📋 Experiment: {bench.config.experiment.title}")
            print(f"👤 Operator: {bench.config.experiment.operator}")
            print(f"🔬 DUT: {bench.config.traceability.dut.description}")
            print()
            
            # Access experiment metadata
            print("📊 Experiment Notes:")
            print(bench.experiment_notes)
            print()
            
            # Access traceability information
            print("🔍 Calibration Status:")
            for instrument, cal_info in bench.traceability.calibration.items():
                print(f"  {instrument}: {cal_info}")
            print()
            
            # Access measurement plan
            print("📋 Measurement Plan:")
            for i, step in enumerate(bench.measurement_plan, 1):
                print(f"  {i}. {step.name} ({step.instrument})")
                if step.notes:
                    print(f"     Notes: {step.notes}")
            print()
            
            # Demonstrate instrument access
            print("🔧 Instrument Operations:")
            
            # Access instruments by their aliases
            print("  Getting instrument IDs...")
            try:
                vna_id = await bench.vna.id()
                print(f"  VNA ID: {vna_id}")
            except Exception as e:
                print(f"  VNA (simulated): {e}")
            
            try:
                dmm_id = await bench.dmm.id()
                print(f"  DMM ID: {dmm_id}")
            except Exception as e:
                print(f"  DMM (simulated): {e}")
            
            # Demonstrate safety limit enforcement
            print("\n⚠️  Safety Limit Testing:")
            try:
                # This should work (within safety limits)
                await bench.psu1.set_voltage(1, 5.0)
                print("  ✅ Set PSU channel 1 to 5.0V (within safety limit)")
            except SafetyLimitError as e:
                print(f"  ❌ Safety limit violation: {e}")
            except Exception as e:
                print(f"  ℹ️  PSU operation (simulated): {e}")
            
            try:
                # This should fail (exceeds safety limits)
                await bench.psu1.set_voltage(1, 6.0)
                print("  ❌ This should not have worked!")
            except SafetyLimitError as e:
                print(f"  ✅ Safety limit enforced: {e}")
            except Exception as e:
                print(f"  ℹ️  PSU operation (simulated): {e}")
            
            # List available instruments
            print(f"\n🎛️  Available instruments: {list(bench._instrument_instances.keys())}")
            
            # Demonstrate measurement plan access
            if bench.measurement_plan:
                first_measurement = bench.measurement_plan[0]
                print(f"\n📊 First measurement: {first_measurement.name}")
                print(f"   Instrument: {first_measurement.instrument}")
                print(f"   Settings: {first_measurement.settings}")
        
        # When exiting the async context manager, post-experiment hooks run
        # and all instruments are closed automatically
        print("\n✅ Bench closed successfully. Post-experiment hooks executed.")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    print("🧪 PyTestLab Bench System Example")
    print("=" * 40)
    asyncio.run(main())
