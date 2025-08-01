#!/usr/bin/env python3
"""
Parallel Measurement Demo - PyTestLab Synchronous API
====================================================

This example demonstrates how to use the @session.task decorator to run
background operations in parallel with data acquisition. This is essential
for complex experiments where you need multiple things happening simultaneously.

Example scenarios:
- PSU ramping voltage while acquiring scope data
- Load cycling on/off while monitoring power consumption
- Temperature control while measuring device characteristics
- Stimulus generation while recording responses
"""

import time
import numpy as np
from pytestlab.measurements import MeasurementSession


def basic_parallel_example():
    """Basic example with PSU ramping while measuring voltage."""
    print("=== Basic Parallel Example ===")

    with MeasurementSession("PSU Ramp + Voltage Monitoring") as session:
        # Setup instruments
        psu = session.instrument("psu", "keysight/E36311A", simulate=True)
        dmm = session.instrument("dmm", "keysight/34470A", simulate=True)

        # Background task: Ramp PSU voltage continuously
        @session.task
        def voltage_ramp(psu, stop_event):
            """Continuously ramp PSU voltage between 1V and 5V."""
            print("🔄 Starting voltage ramp...")
            while not stop_event.is_set():
                # Ramp up
                for v in np.linspace(1.0, 5.0, 20):
                    if stop_event.is_set():
                        break
                    psu.channel(1).set_voltage(v)
                    time.sleep(0.1)

                # Ramp down
                for v in np.linspace(5.0, 1.0, 20):
                    if stop_event.is_set():
                        break
                    psu.channel(1).set_voltage(v)
                    time.sleep(0.1)
            print("🛑 Voltage ramp stopped")

        # Acquisition: Monitor voltage every 200ms
        @session.acquire
        def monitor_voltage(dmm):
            voltage = dmm.measure_voltage_dc()
            return {"measured_voltage": voltage.values}

        # Run for 10 seconds, acquire every 200ms
        print("🎯 Running parallel measurement for 10 seconds...")
        experiment = session.run(duration=10.0, interval=0.2)

        print(f"✅ Captured {len(experiment.data)} voltage measurements")
        print(f"📊 Voltage range: {experiment.data['measured_voltage'].min():.2f}V to {experiment.data['measured_voltage'].max():.2f}V")


def complex_parallel_example():
    """Complex example with multiple parallel tasks."""
    print("\n=== Complex Parallel Example ===")

    with MeasurementSession("Multi-Task Power Analysis") as session:
        # Setup instruments
        psu = session.instrument("psu", "keysight/E36311A", simulate=True)
        load = session.instrument("load", "keysight/EL34143A", simulate=True)
        scope = session.instrument("scope", "keysight/DSOX1204G", simulate=True)

        # Task 1: PSU voltage stepping
        @session.task
        def voltage_steps(psu, stop_event):
            """Step through different voltage levels."""
            voltages = [3.3, 5.0, 12.0, 5.0, 3.3]
            print("📈 Starting voltage stepping...")

            while not stop_event.is_set():
                for v in voltages:
                    if stop_event.is_set():
                        break
                    print(f"  Setting PSU to {v}V")
                    psu.channel(1).set_voltage(v)
                    time.sleep(2.0)  # Hold each voltage for 2 seconds
            print("🛑 Voltage stepping stopped")

        # Task 2: Load pulsing
        @session.task
        def load_pulsing(load, stop_event):
            """Pulse the electronic load on/off."""
            print("⚡ Starting load pulsing...")
            load.set_mode("CC")  # Constant current mode

            try:
                while not stop_event.is_set():
                    # High load for 1 second
                    load.set_current(1.0)
                    load.enable_input(True)
                    time.sleep(1.0)

                    if stop_event.is_set():
                        break

                    # Low load for 1 second
                    load.set_current(0.1)
                    time.sleep(1.0)
            finally:
                load.enable_input(False)
                print("🛑 Load pulsing stopped")

        # Task 3: Periodic scope trigger
        @session.task
        def scope_triggering(scope, stop_event):
            """Periodically trigger scope acquisitions."""
            print("📡 Starting periodic scope triggers...")
            scope.channel(1).setup(scale=1.0, coupling="DC").enable()
            scope.trigger.setup_edge(source="CH1", level=2.5)

            while not stop_event.is_set():
                try:
                    scope.trigger.single()
                    time.sleep(0.5)  # Trigger every 500ms
                except Exception as e:
                    if not stop_event.is_set():
                        print(f"  Scope trigger error: {e}")
                    time.sleep(0.1)
            print("🛑 Scope triggering stopped")

        # Acquisition: Monitor power consumption
        @session.acquire
        def power_monitoring(psu, scope):
            """Measure power consumption and capture scope data."""
            try:
                # Get PSU measurements
                voltage = psu.channel(1).get_voltage()
                current = psu.channel(1).get_current()
                power = voltage * current

                # Try to get scope measurement (may fail if no trigger)
                try:
                    scope_data = scope.read_channels(1)
                    scope_samples = len(scope_data) if scope_data is not None else 0
                except Exception:
                    scope_samples = 0

                return {
                    "supply_voltage": voltage,
                    "supply_current": current,
                    "power_consumption": power,
                    "scope_samples": scope_samples
                }
            except Exception as e:
                print(f"  Acquisition error: {e}")
                return {
                    "supply_voltage": 0,
                    "supply_current": 0,
                    "power_consumption": 0,
                    "scope_samples": 0
                }

        # Run for 15 seconds with all tasks in parallel
        print("🎯 Running complex parallel measurement for 15 seconds...")
        print("   • PSU voltage stepping")
        print("   • Load current pulsing")
        print("   • Scope periodic triggering")
        print("   • Power monitoring every 300ms")

        experiment = session.run(duration=15.0, interval=0.3)

        print(f"✅ Captured {len(experiment.data)} power measurements")
        avg_power = experiment.data['power_consumption'].mean()
        max_power = experiment.data['power_consumption'].max()
        print(f"📊 Power consumption - Average: {avg_power:.2f}W, Peak: {max_power:.2f}W")
        total_scope_samples = experiment.data['scope_samples'].sum()
        print(f"📡 Total scope samples captured: {total_scope_samples}")


def stress_test_example():
    """Stress test with rapid background operations."""
    print("\n=== Stress Test Example ===")

    with MeasurementSession("High-Speed Stress Test") as session:
        psu = session.instrument("psu", "keysight/E36311A", simulate=True)
        dmm = session.instrument("dmm", "keysight/34470A", simulate=True)

        # Rapid PSU switching
        @session.task
        def rapid_switching(psu, stop_event):
            """Rapidly switch PSU output on/off."""
            print("⚡ Starting rapid PSU switching...")
            count = 0
            while not stop_event.is_set():
                psu.channel(1).on()
                time.sleep(0.05)  # 50ms on
                if stop_event.is_set():
                    break
                psu.channel(1).off()
                time.sleep(0.05)  # 50ms off
                count += 1
            print(f"🛑 Completed {count} switch cycles")

        # High-speed voltage monitoring
        @session.acquire
        def fast_monitoring(dmm):
            voltage = dmm.measure_voltage_dc()
            return {"voltage": voltage.values}

        print("🎯 Running stress test for 5 seconds...")
        print("   • PSU switching every 100ms")
        print("   • Voltage monitoring every 50ms")

        experiment = session.run(duration=5.0, interval=0.05)

        print(f"✅ Captured {len(experiment.data)} rapid measurements")
        voltage_std = experiment.data['voltage'].std()
        print(f"📊 Voltage stability (std dev): {voltage_std:.4f}V")


def main():
    """Run all parallel measurement examples."""
    print("🧪 PyTestLab Parallel Measurement Demo")
    print("=" * 50)

    # Run examples
    basic_parallel_example()
    complex_parallel_example()
    stress_test_example()

    print("\n✨ All parallel measurement examples completed!")
    print("\nKey takeaways:")
    print("• Use @session.task for background operations that run during acquisition")
    print("• Tasks automatically receive instruments and stop_event parameters")
    print("• Multiple tasks can run simultaneously with data acquisition")
    print("• Perfect for stimulus generation, environmental control, and stress testing")
    print("• All synchronization and cleanup is handled automatically")


if __name__ == "__main__":
    main()
