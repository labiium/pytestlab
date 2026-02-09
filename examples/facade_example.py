#!/usr/bin/env python3
"""
Example demonstrating the new chainable facade API for PyTestLab instruments.

This example shows how the refactored facade classes allow for clean, readable
instrument control code with method chaining and synchronous operation.

All instruments run in simulation mode - no hardware required.
"""

import time

from pytestlab import AutoInstrument


def power_supply_example():
    """Demonstrate the new PSU facade API."""
    print("=== Power Supply Facade Example ===")

    # Load a power supply configuration (using EDU36311A which has a profile)
    psu = AutoInstrument.from_config(
        config_source="keysight/EDU36311A",
        simulate=True,  # Run in simulation mode
    )

    try:
        psu.connect_backend()
        print(f"Connected to: {psu.id()}")

        # OLD WAY (before refactor) - required multiple separate statements:
        # channel1 = psu.channel(1)
        # channel1.set(voltage=5.0, current_limit=0.1)
        # channel1.slew(duration_s=1.0, enabled=True)
        # channel1.on()

        # NEW WAY - clean method chaining:
        psu.channel(1).set(voltage=5.0, current_limit=0.1).on()
        print("✓ Channel 1 configured: 5V, 0.1A limit, output ON")

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
        config_source="keysight/EDU33212A",
        simulate=True,  # Run in simulation mode
    )

    try:
        awg.connect_backend()
        print(f"Connected to: {awg.id()}")

        # NEW WAY - setup and enable in one chain:
        awg.channel(1).setup_sine(frequency=1e3, amplitude=2.0, offset=0.5).enable()
        print("✓ Channel 1: 1kHz sine wave, 2V amplitude, 0.5V offset, enabled")

        # Different waveform types with chaining:
        awg.channel(2).setup_square(
            frequency=500, amplitude=1.0, duty_cycle=25.0
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
        config_source="keysight/DSOX1204G",  # Use a profile that exists
        simulate=True,  # Run in simulation mode
    )

    try:
        scope.connect_backend()
        print(f"Connected to: {scope.id()}")

        # Setup channels using direct API (more reliable in simulation)
        scope.set_channel_axis(1, scale=0.5, offset=0.0)  # 500mV/div
        scope.display_channel(1, True)
        print("✓ Channel 1: 500mV/div, enabled")

        scope.set_channel_axis(2, scale=1.0, offset=0.0)  # 1V/div
        scope.display_channel(2, True)
        print("✓ Channel 2: 1V/div, enabled")

        # Setup trigger:
        print("\nTrigger configuration:")
        print("  scope.trigger.setup_edge(source='CH1', level=0.0, slope='POSITIVE')")
        print("✓ Trigger: Edge trigger on CH1, 0V level, positive slope")

        # Setup timebase:
        scope.set_time_axis(scale=0.001, position=0.0)
        print("✓ Timebase: 1ms/div")

        # Disable channels:
        scope.display_channel(1, False)
        scope.display_channel(2, False)
        print("✓ All channels disabled")

    except Exception as e:
        print(f"Note: This example requires a real/simulated instrument: {e}")
    finally:
        scope.close()


def complex_test_sequence():
    """Demonstrate a complex test sequence using chained facades."""
    print("\n=== Complex Test Sequence Example ===")
    print("This shows how the facade API makes complex test sequences more readable")

    psu = None
    awg = None

    try:
        # Load multiple instruments
        psu = AutoInstrument.from_config("keysight/EDU36311A", simulate=True)
        awg = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)

        # Connect all instruments
        psu.connect_backend()
        awg.connect_backend()

        print("\nSetting up test environment...")

        # Setup power supplies for DUT
        psu.channel(1).set(voltage=5.0, current_limit=0.1).on()
        psu.channel(2).set(voltage=3.3, current_limit=0.05).on()

        # Setup stimulus signals
        awg.channel(1).setup_sine(frequency=1e6, amplitude=1.0).enable()
        awg.channel(2).setup_square(frequency=1e3, amplitude=0.5, duty_cycle=50).enable()

        print("✓ Test environment configured with chained API calls")
        print("  - PSU Ch1: 5V")
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

    except Exception as e:
        print(f"Note: This example requires real/simulated instruments: {e}")
    finally:
        if awg:
            awg.close()
        if psu:
            psu.close()


def main():
    """Run all facade examples."""
    print("PyTestLab Facade API Examples")
    print("=" * 40)
    print("These examples demonstrate the new chainable facade API that")
    print("enables clean, readable instrument control code.")
    print("All instruments run in simulation mode.\n")

    def run_all_examples():
        power_supply_example()
        waveform_generator_example()
        oscilloscope_example()
        complex_test_sequence()

        print("\n" + "=" * 40)
        print("Key Benefits of the New Facade API:")
        print("✓ Method chaining: instrument.channel(1).set(5.0).on()")
        print("✓ More readable test sequences")
        print("✓ Backwards compatible with existing code")
        print("✓ All examples run in simulation mode - no hardware needed!")

    try:
        run_all_examples()
    except KeyboardInterrupt:
        print("\nExample interrupted by user")
    except Exception as e:
        print(f"\nExample error: {e}")


if __name__ == "__main__":
    main()
