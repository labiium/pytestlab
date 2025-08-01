#!/usr/bin/env python3
"""
PyTestLab Migration Example - BEFORE (Async Version)

This file demonstrates typical PyTestLab async patterns that need to be migrated
to the new synchronous API. See migration_example_after.py for the converted version.
"""

import numpy as np
import pytestlab
from pytestlab.instruments import AutoInstrument
from pytestlab.measurements import MeasurementSession
from pytestlab.exceptions import SafetyLimitError


def basic_instrument_usage():
    """Basic instrument connection and measurement."""

    # Connect to oscilloscope with simulation
    scope = AutoInstrument.from_config("keysight/DSOX1204G", simulate=True)
    scope.connect_backend()

    try:
        # Configure channels
        scope.channel(1).setup(scale=0.5, offset=0).enable()
        scope.channel(2).setup(scale=1.0, offset=0).enable()

        # Setup trigger
        await scope.trigger.setup_edge(source="CH1", level=0.2)

        # Acquire data
        await scope.trigger.single()
        trace_data = scope.read_channels([1, 2])

        print(f"Captured {len(trace_data)} samples")
        print(f"Channels: {trace_data.columns}")

    finally:
        scope.close()


def bench_configuration_example():
    """Using Bench with YAML configuration and safety limits."""

    with pytestlab.Bench.open("examples/bench_config.yaml") as bench:

        # Test safety limits
        try:
            bench.psu.channel(1).set_voltage(7.0)  # Above configured limit
        except SafetyLimitError as e:
            print(f"Safety limit enforced: {e}")

        # Safe operation
        bench.psu.channel(1).set_voltage(3.3)
        bench.psu.channel(1).set_current_limit(0.5)
        bench.psu.channel(1).enable()

        # Wait for settling
        asyncio.sleep(0.1)

        # Measure voltage and current
        voltage = bench.dmm.measure_voltage_dc()
        current = bench.psu.channel(1).measure_current()

        print(f"Output: {voltage.values:.3f} V, {current.values:.3f} A")

        # Power off
        bench.psu.channel(1).disable()


def parameter_sweep_measurement():
    """Complex measurement session with parameter sweeps."""

    with MeasurementSession("Diode I-V Characterization") as meas:

        # Configure instruments
        meas.instrument("psu", "keysight/EDU36311A", address="TCPIP0::192.168.1.100::INSTR")
        meas.instrument("dmm", "keysight/34470A", address="USB0::2391::9479::INSTR")

        # Define sweep parameters
        meas.parameter("voltage", np.linspace(0, 3.0, 31), unit="V")
        meas.parameter("temperature", [25, 50, 75], unit="°C")

        # Configure safety limits
        meas.safety_limit("voltage", max_value=3.5)
        meas.safety_limit("current", max_value=0.1)

        @meas.acquire
        def measure_iv_point(psu, dmm, voltage, temperature):
            """Acquire single I-V measurement point."""

            # Set voltage
            psu.channel(1).set_voltage(voltage)

            # Wait for settling
            asyncio.sleep(0.01)

            # Measure current
            current = dmm.measure_current_dc()

            # Additional measurements
            actual_voltage = dmm.measure_voltage_dc()

            return {
                'current': current.values,
                'voltage_measured': actual_voltage.values,
                'temperature': temperature,
            }

        # Run the measurement
        print("Starting parameter sweep...")
        results = meas.run()

        # Analyze results
        analysis = meas.analyze()
        print(f"Collected {len(results)} measurement points")
        print(f"Analysis complete: {analysis.summary}")

        # Save data
        meas.save("diode_iv_sweep.h5")


def advanced_measurement_patterns():
    """Advanced async patterns with error handling and parallel operations."""

    instruments = []

    try:
        # Connect multiple instruments
        scope = AutoInstrument.from_config("tek/MSO64", address="TCPIP0::192.168.1.10::INSTR")
        scope.connect_backend()
        instruments.append(scope)

        psu = AutoInstrument.from_config("keysight/EDU36311A", address="TCPIP0::192.168.1.11::INSTR")
        psu.connect_backend()
        instruments.append(psu)

        fgen = AutoInstrument.from_config("keysight/33500B", address="TCPIP0::192.168.1.12::INSTR")
        fgen.connect_backend()
        instruments.append(fgen)

        # Configure signal generator
        fgen.channel(1).setup_sine(frequency=1e3, amplitude=0.5)
        fgen.channel(1).enable()

        # Configure power supply
        psu.channel(1).set_voltage(5.0)
        psu.channel(1).enable()

        # Configure scope
        scope.channel(1).setup(scale=0.2, coupling="DC")
        scope.channel(2).setup(scale=1.0, coupling="DC")
        await scope.trigger.setup_edge(source="CH1", level=0.1)

        # Perform measurements with different trigger conditions
        measurements = []

        for trigger_level in [0.1, 0.2, 0.3]:
            await scope.trigger.setup_edge(source="CH1", level=trigger_level)
            await scope.trigger.single()

            # Wait for trigger with timeout
            try:
                asyncio.wait_for(scope.wait_for_trigger(), timeout=5.0)
                trace = scope.read_channels([1, 2])
                measurements.append({
                    'trigger_level': trigger_level,
                    'trace': trace
                })
            except asyncio.TimeoutError:
                print(f"Trigger timeout at level {trigger_level}")

        print(f"Completed {len(measurements)} measurements")

    except Exception as e:
        print(f"Measurement failed: {e}")

    finally:
        # Clean up all instruments
        for instr in instruments:
            try:
                instr.close()
            except Exception as e:
                print(f"Error closing instrument: {e}")


def measurement_with_data_processing():
    """Measurement with real-time data processing."""

    with MeasurementSession("FFT Analysis") as meas:

        meas.instrument("scope", "tek/MSO64", address="...")
        meas.instrument("fgen", "keysight/33500B", address="...")

        meas.parameter("frequency", np.logspace(2, 6, 50), unit="Hz")

        @meas.acquire
        def frequency_response(scope, fgen, frequency):
            """Measure frequency response at given frequency."""

            # Set stimulus frequency
            fgen.channel(1).setup_sine(frequency=frequency, amplitude=1.0)
            fgen.channel(1).enable()

            # Wait for settling
            asyncio.sleep(0.1)

            # Capture response
            await scope.trigger.single()
            trace = scope.read_channels([1, 2])

            # Calculate amplitude and phase
            input_signal = trace['CH1'].values
            output_signal = trace['CH2'].values

            # FFT processing
            input_fft = np.fft.fft(input_signal)
            output_fft = np.fft.fft(output_signal)

            # Find response at stimulus frequency
            freq_bins = np.fft.fftfreq(len(input_signal), d=1/scope.sample_rate)
            freq_idx = np.argmin(np.abs(freq_bins - frequency))

            amplitude = np.abs(output_fft[freq_idx]) / np.abs(input_fft[freq_idx])
            phase = np.angle(output_fft[freq_idx]) - np.angle(input_fft[freq_idx])

            return {
                'amplitude': amplitude,
                'phase': np.degrees(phase),
                'frequency': frequency
            }

        # Run measurement
        results = meas.run()

        # Generate Bode plot
        analysis = meas.analyze()
        analysis.plot_bode()

        return results


# Test functions for pytest
import pytest
def test_basic_connection():
    """Test basic instrument connection."""
    scope = AutoInstrument.from_config("keysight/DSOX1204G", simulate=True)
    scope.connect_backend()

    status = scope.get_status()
    assert status['connected'] is True

    scope.close()
def test_measurement_session():
    """Test measurement session functionality."""
    with MeasurementSession("Test Session") as meas:
        meas.instrument("dmm", "keysight/34470A", simulate=True)
        meas.parameter("voltage", [1.0, 2.0, 3.0])

        @meas.acquire
        def simple_measurement(dmm, voltage):
            return {'reading': voltage * 1.1}  # Simulated reading

        results = meas.run()
        assert len(results) == 3


def main():
    """Main function to run all examples."""

    print("Running PyTestLab async examples...")

    # Run all examples
    basic_instrument_usage()
    bench_configuration_example()
    parameter_sweep_measurement()
    advanced_measurement_patterns()
    measurement_with_data_processing()

    print("All examples completed!")


if __name__ == "__main__":
    main()
