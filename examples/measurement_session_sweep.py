#!/usr/bin/env python3
"""
MeasurementSession Parameter Sweep Example

This example demonstrates how to use the built-in parameter sweep capabilities
of the MeasurementSession class for automated testing:

1. Creating a session
2. Defining multiple parameters with different values
3. Setting up measurement functions
4. Running parameter sweeps (creates a Cartesian product of all parameter values)
5. Analyzing the results

The MeasurementSession class automatically:
- Creates all parameter combinations
- Passes instruments to measurement functions
- Collects and organizes results
- Creates an Experiment object with the data
"""
import time
import numpy as np
import matplotlib.pyplot as plt
from typing import Dict, Any

from pytestlab.measurements.session import MeasurementSession
from pytestlab.instruments import AutoInstrument


def run_transistor_iv_sweep():
    """Run a transistor IV curve sweep with MeasurementSession."""
    # Create a measurement session
    with MeasurementSession(
        name="Transistor IV Characterization",
        description="Measure IV curves of a transistor at different base currents"
    ) as session:
        print(f"📊 Session created: {session.name}")

        # Define multiple parameters for the sweep
        # 1. Base currents - logarithmically spaced for better curve visualization
        session.parameter(
            "I_base",
            np.logspace(-6, -3, 5),  # 1µA to 1mA in 5 steps
            unit="A",
            notes="Base current"
        )

        # 2. Collector-emitter voltages - linear spacing
        session.parameter(
            "V_ce",
            np.linspace(0, 5, 11),  # 0V to 5V in 0.5V steps
            unit="V",
            notes="Collector-emitter voltage"
        )

        # 3. Temperature points - discrete values
        session.parameter(
            "temperature",
            [25, 50, 75],  # 25°C, 50°C, and 75°C
            unit="°C",
            notes="Ambient temperature"
        )

        print(f"Parameters defined: I_base, V_ce, temperature")
        total_combinations = 5 * 11 * 3  # 165 combinations
        print(f"Total parameter combinations: {total_combinations}")

        # Get instruments (in simulation mode)
        psu1 = session.instrument("psu_base", "keysight/EDU36311A", simulate=True)
        psu2 = session.instrument("psu_collector", "keysight/EDU36311A", simulate=True)
        dmm = session.instrument("dmm", "keysight/EDU34450A", simulate=True)

        # Define a measurement function using the @session.acquire decorator
        @session.acquire
        def measure_collector_current(I_base: float, V_ce: float, temperature: float,
                                           psu_base, psu_collector, dmm):
            """Measure transistor collector current with the given parameters."""
            # In a real scenario, we might also control a temperature chamber here
            print(f"Setting: I_base={I_base*1e6:.2f}µA, V_ce={V_ce:.1f}V, T={temperature}°C")

            # 1. Set up the base current with psu_base
            # We use V=I_base*R where R is a fixed resistor value (simulated)
            base_resistor = 10000  # 10kΩ resistor to set base current
            V_base = I_base * base_resistor
            V_base = min(V_base, 10.0)  # Clamp to PSU max voltage

            psu_base.set_voltage(1, V_base)
            psu_base.set_current(1, 0.01)  # 10mA current limit

            # 2. Set up collector voltage with psu_collector
            psu_collector.set_voltage(1, V_ce)
            psu_collector.set_current(1, 0.5)  # 500mA current limit

            # 3. Turn on power supplies
            psu_base.output(1, True)
            psu_collector.output(1, True)

            # 4. Wait for circuit to stabilize
            time.sleep(0.01)  # 10ms in real test would be longer

            # 5. Measure collector current
            # In simulation mode this will return random values
            # In a real setup, the DMM would measure the actual current
            measurement = dmm.measure_current_dc()

            # Simulate a realistic transistor response in simulation mode
            # For NPN transistor: Ic ≈ β × Ib × (1 - exp(-V_ce / V_thermal))
            # where β is the current gain (hFE)
            beta = 100 * (1 - 0.005 * (temperature - 25))  # gain decreases with temperature
            V_thermal = 0.026 * (temperature + 273.15) / 300  # thermal voltage

            # Collector current calculation with some randomness for simulation
            I_collector = beta * I_base * (1 - np.exp(-V_ce / V_thermal))
            I_collector *= (0.9 + 0.2 * np.random.random())  # Add ±10% randomness

            # 6. Turn off power supplies
            psu_base.output(1, False)
            psu_collector.output(1, False)

            # 7. Return results as a dictionary
            return {
                "I_collector": I_collector,
                "hFE": I_collector / I_base if I_base > 0 else 0,
                "power": I_collector * V_ce
            }

        # Run the measurement sweep with a progress bar
        print("\nRunning parameter sweep...")
        start_time = time.time()
        experiment = session.run(show_progress=True)
        elapsed_time = time.time() - start_time

        print(f"\n✅ Sweep completed in {elapsed_time:.1f} seconds")
        print(f"Data shape: {experiment.data.shape}")

        return experiment


def analyze_results(experiment):
    """Analyze and visualize the sweep results."""
    print("\n📊 Analyzing results...")

    # Convert to pandas for easier analysis
    df = experiment.data.to_pandas()

    # Group by temperature and base current to calculate statistics
    grouped = df.groupby(["temperature", "I_base"])
    max_collector = grouped["I_collector"].max()
    max_gain = grouped["hFE"].max()

    print("\nMaximum collector current by temperature and base current:")
    print(max_collector)

    print("\nMaximum gain (hFE) by temperature and base current:")
    print(max_gain)

    # Create visualizations
    plt.figure(figsize=(15, 10))

    # 1. Plot IV curves for different base currents at 25°C
    plt.subplot(221)
    for i_base in sorted(df["I_base"].unique()):
        data = df[(df["temperature"] == 25) & (df["I_base"] == i_base)]
        plt.plot(data["V_ce"], data["I_collector"] * 1000,
                 marker='o', label=f'Ib={i_base*1e6:.1f}µA')

    plt.title("Transistor IV Curves at 25°C")
    plt.xlabel("Collector-Emitter Voltage (V)")
    plt.ylabel("Collector Current (mA)")
    plt.grid(True)
    plt.legend()

    # 2. Plot IV curves for highest base current at different temperatures
    plt.subplot(222)
    max_i_base = max(df["I_base"].unique())
    for temp in sorted(df["temperature"].unique()):
        data = df[(df["I_base"] == max_i_base) & (df["temperature"] == temp)]
        plt.plot(data["V_ce"], data["I_collector"] * 1000,
                 marker='o', label=f'T={temp}°C')

    plt.title(f"Temperature Effect (Ib={max_i_base*1e6:.1f}µA)")
    plt.xlabel("Collector-Emitter Voltage (V)")
    plt.ylabel("Collector Current (mA)")
    plt.grid(True)
    plt.legend()

    # 3. Plot gain vs collector current for different temperatures
    plt.subplot(223)
    for temp in sorted(df["temperature"].unique()):
        data = df[df["temperature"] == temp]
        plt.semilogx(data["I_collector"] * 1000, data["hFE"],
                    marker='.', linestyle='none', label=f'T={temp}°C')

    plt.title("Transistor Gain vs Collector Current")
    plt.xlabel("Collector Current (mA)")
    plt.ylabel("Current Gain (hFE)")
    plt.grid(True)
    plt.legend()

    # 4. Plot max power vs base current for different temperatures
    plt.subplot(224)
    for temp in sorted(df["temperature"].unique()):
        power_data = df[df["temperature"] == temp].groupby("I_base")["power"].max() * 1000
        plt.plot(power_data.index * 1e6, power_data,
                marker='o', label=f'T={temp}°C')

    plt.title("Maximum Power vs Base Current")
    plt.xlabel("Base Current (µA)")
    plt.ylabel("Maximum Power (mW)")
    plt.grid(True)
    plt.legend()

    plt.tight_layout()
    plt.savefig("transistor_sweep_results.png")
    print("\nResults visualization saved to 'transistor_sweep_results.png'")


def main():
    """Main function to run the example."""
    print("PyTestLab MeasurementSession Parameter Sweep Example")
    print("=" * 60)

    # Run the transistor IV sweep
    experiment = run_transistor_iv_sweep()

    # Analyze and visualize the results
    analyze_results(experiment)

    print("\nSweep Summary:")
    print("- MeasurementSession handled 165 parameter combinations automatically")
    print("- All parameter combinations were systematically explored")
    print("- Results were collected into a structured Experiment object")
    print("- The Experiment data includes all parameters and measurements")
    print("- Results can be easily analyzed, visualized, and exported")


if __name__ == "__main__":
    # Run the main function
    main()
