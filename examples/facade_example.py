#!/usr/bin/env python3
"""
Example demonstrating the new chainable facade API for PyTestLab instruments.

This example shows how the refactored facade classes allow for clean, readable
instrument control code with method chaining and synchronous operation.
"""

import time
from pytestlab.instruments import AutoInstrument


def power_supply_example():
    """Demonstrate the new PSU facade API."""
    print("=== Power Supply Facade Example ===")

    # Load a power supply configuration
    psu = AutoInstrument.from_config(
        config_source="keysight/E36312A",  # Example PSU
        debug_mode=True
    )

    try:
        psu.connect_backend()

        # OLD WAY (before refactor) - required multiple separate statements:
        # channel1 = psu.channel(1)
        # channel1.set(voltage=5.0, current_limit=0.1)
        # channel1.slew(duration_s=1.0, enabled=True)
        # channel1.on()

        # NEW WAY - clean method chaining:
        psu.channel(1).set(voltage=5.0, current_limit=0.1).slew(duration_s=1.0).on()

        print("✓ Channel 1 configured: 5V, 0.1A limit, 1s slew, output ON")

        # You can also chain in separate statements:
        psu.channel(2).set(voltage=3.3, current_limit=0.05).on()
        print("✓ Channel 2 configured: 3.3V, 0.05A limit, output ON")

        # Turn off all channels with chaining:
        psu.channel(1).off()
        psu.channel(2).off()
        print("✓ All channels turned off")

    except Exception as e:
        print(f"Note: This example requires a real/simulated instrument: {e}")
    finally:
        psu.close()


def waveform_generator_example():
    """Demonstrate the new AWG facade API."""
    print("\n=== Waveform Generator Facade Example ===")

    # Load a waveform generator configuration
    awg = AutoInstrument.from_config(
        config_source="keysight/EDU33212A",  # Example AWG
        debug_mode=True
    )

    try:
        awg.connect_backend()

        # NEW WAY - setup and enable in one chain:
        awg.channel(1).setup_sine(frequency=1e3, amplitude=2.0, offset=0.5).enable()
        print("✓ Channel 1: 1kHz sine wave, 2V amplitude, 0.5V offset, enabled")

        # Different waveform types with chaining:
        awg.channel(2).setup_square(
            frequency=500,
            amplitude=1.0,
            duty_cycle=25.0
        ).set_load_impedance(50).enable()
        print("✓ Channel 2: 500Hz square wave, 25% duty cycle, 50Ω load, enabled")

        # Disable outputs:
        awg.channel(1).disable()
        awg.channel(2).disable()
        print("✓ All channels disabled")

    except Exception as e:
        print(f"Note: This example requires a real/simulated instrument: {e}")
    finally:
        awg.close()


def oscilloscope_example():
    """Demonstrate the new oscilloscope facade API."""
    print("\n=== Oscilloscope Facade Example ===")

    # Load an oscilloscope configuration
    scope = AutoInstrument.from_config(
        config_source="keysight/DSO1024A",  # Example scope
        debug_mode=True
    )

    try:
        scope.connect_backend()

        # Setup multiple channels with chaining:
        scope.channel(1).setup(
            scale=0.5,          # 500mV/div
            offset=0.0,         # No offset
            coupling="DC",      # DC coupling
            probe_attenuation=10  # 10x probe
        ).enable()
        print("✓ Channel 1: 500mV/div, DC coupled, 10x probe, enabled")

        scope.channel(2).setup(scale=1.0, coupling="AC").enable()
        print("✓ Channel 2: 1V/div, AC coupled, enabled")

        # Setup trigger with chaining:
        scope.trigger.setup_edge(
            source="CH1",
            level=0.0,
            slope="POSITIVE",
            coupling="DC"
        )
        print("✓ Trigger: Edge trigger on CH1, 0V level, positive slope")

        # Setup acquisition with chaining:
        scope.acquisition.set_acquisition_type("NORMAL").set_acquisition_mode("REAL_TIME")
        print("✓ Acquisition: Normal type, real-time mode")

        # Disable channels:
        scope.channel(1).disable()
        scope.channel(2).disable()
        print("✓ All channels disabled")

    except Exception as e:
        print(f"Note: This example requires a real/simulated instrument: {e}")
    finally:
        scope.close()


def complex_test_sequence():
    """Demonstrate a complex test sequence using chained facades."""
    print("\n=== Complex Test Sequence Example ===")
    print("This shows how the facade API makes complex test sequences more readable")

    try:
        # Load multiple instruments
        psu = AutoInstrument.from_config("keysight/E36312A", debug_mode=True)
        awg = AutoInstrument.from_config("keysight/EDU33212A", debug_mode=True)

        # Connect all instruments
        psu.connect_backend()
        awg.connect_backend()

        print("Setting up test environment...")

        # Setup power supplies for DUT
        psu.channel(1).set(voltage=5.0, current_limit=0.1).slew(duration_s=0.5).on()
        psu.channel(2).set(voltage=3.3, current_limit=0.05).on()

        # Setup stimulus signals
        awg.channel(1).setup_sine(frequency=1e6, amplitude=1.0).enable()
        awg.channel(2).setup_square(frequency=1e3, amplitude=0.5, duty_cycle=50).enable()

        print("✓ Test environment configured with chained API calls")
        print("  - PSU Ch1: 5V with 0.5s slew")
        print("  - PSU Ch2: 3.3V")
        print("  - AWG Ch1: 1MHz sine wave")
        print("  - AWG Ch2: 1kHz square wave")

        # Simulate test running...
        time.sleep(0.1)

        # Cleanup with chained calls
        awg.channel(1).disable()
        awg.channel(2).disable()
        psu.channel(1).off()
        psu.channel(2).off()

        print("✓ Test completed and instruments cleaned up")

        psu.close()
        awg.close()

    except Exception as e:
        print(f"Note: This example requires real/simulated instruments: {e}")


def main():
    """Run all facade examples."""
    print("PyTestLab Facade API Examples")
    print("=" * 40)
    print("These examples demonstrate the new chainable facade API that")
    print("resolves the 'coroutine was never awaited' issue while providing")
    print("clean, readable instrument control code.\n")

    def run_all_examples():
        power_supply_example()
        waveform_generator_example()
        oscilloscope_example()
        complex_test_sequence()

        print("\n" + "=" * 40)
        print("Key Benefits of the New Facade API:")
        print("✓ Method chaining: instrument.channel(1).set(5.0).on()")
        print("✓ Direct function calls - no async/await needed")
        print("✓ No 'coroutine never awaited' warnings")
        print("✓ More readable test sequences")
        print("✓ Backwards compatible with existing code")

    try:
        run_all_examples()
    except KeyboardInterrupt:
        print("\nExample interrupted by user")
    except Exception as e:
        print(f"\nExample error: {e}")
        print("Note: Most examples require instrument configurations and backends to be available")


if __name__ == "__main__":
    main()
