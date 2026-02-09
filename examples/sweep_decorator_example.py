#!/usr/bin/env python3
"""
Sweep Decorator API Example
===========================

This example demonstrates the proper usage of the sweep decorators:
- @grid_sweep
- @monte_carlo_sweep
- @gwass

Key Points:
-----------
1. Decorated functions must accept keyword arguments matching parameter names
2. Parameter names are defined in ParameterSpace
3. Decorators handle the parameter sweep automatically

Example:
    param_space = ParameterSpace({"V_base": (0.6, 1.0), "V_collector": (0, 5)})

    @grid_sweep(param_space=param_space, points=10)
    def measure(V_base, V_collector):  # <-- Must use keyword args!
        I_collector = (V_base - 0.6) * (V_collector / 5) * 0.01
        return I_collector
"""

import matplotlib.pyplot as plt
import numpy as np
import polars as pl

from pytestlab.experiments.sweep import grid_sweep
from pytestlab.experiments.sweep import gwass
from pytestlab.experiments.sweep import monte_carlo_sweep
from pytestlab.experiments.sweep import ParameterSpace


def example_1_basic_grid_sweep():
    """Example 1: Basic grid sweep with keyword arguments."""
    print("\n=== Example 1: Basic Grid Sweep ===")

    # Define parameter space with meaningful names
    param_space = ParameterSpace(
        {
            "frequency": (1000, 10000),  # Hz
            "amplitude": (0.1, 2.0),  # V
        }
    )

    # Define measurement function with keyword arguments
    @grid_sweep(param_space=param_space, points=5)
    def measure_response(frequency, amplitude):
        """
        Measure circuit response.

        Args:
            frequency: Input frequency in Hz
            amplitude: Input amplitude in V

        Returns:
            Output power in mW
        """
        # Simulate a resonant circuit response
        f0 = 5000  # Resonant frequency
        Q = 10  # Quality factor

        # Lorentzian response
        response = 1 / (1 + Q**2 * (frequency / f0 - f0 / frequency) ** 2)
        power = amplitude**2 * response * 100  # mW

        return power

    # Run the sweep
    results = measure_response()

    print(f"Grid sweep completed: {len(results)} points")
    print(f"Frequency range: {param_space.ranges[0]}")
    print(f"Amplitude range: {param_space.ranges[1]}")

    return results


def example_2_with_constraint():
    """Example 2: Grid sweep with parameter constraints."""
    print("\n=== Example 2: Grid Sweep with Constraints ===")

    # Define valid operating region
    def valid_operating_region(params):
        """Only measure where power < 100 mW (safe operating area)."""
        voltage = params["voltage"]
        current = params["current"]
        power = voltage * current
        return power < 100  # mW limit

    param_space = ParameterSpace(
        {"voltage": (0, 10), "current": (0, 20)}, constraint=valid_operating_region
    )

    @grid_sweep(param_space=param_space, points=8)
    def measure_device(voltage, current):
        """Measure device efficiency."""
        input_power = voltage * current
        # Simulate 85% efficiency
        output_power = input_power * 0.85
        # Return efficiency as scalar
        return output_power / input_power * 100 if input_power > 0 else 0

    results = measure_device()

    # Filter out NaN results (invalid points)
    valid_results = [(p, r) for p, r in results if not isinstance(r, float) or not np.isnan(r)]

    print(f"Total points: {len(results)}")
    print(f"Valid points (within constraint): {len(valid_results)}")
    print(f"Invalid points: {len(results) - len(valid_results)}")

    return valid_results


def example_3_monte_carlo():
    """Example 3: Monte Carlo random sampling."""
    print("\n=== Example 3: Monte Carlo Sampling ===")

    param_space = ParameterSpace(
        {
            "temperature": (-40, 85),  # °C
            "voltage": (3.0, 5.5),  # V
        }
    )

    @monte_carlo_sweep(param_space=param_space, samples=50)
    def test_over_corners(temperature, voltage):
        """Test circuit over random temperature/voltage corners."""
        # Simulate temperature coefficient
        temp_coeff = 0.001  # 0.1% per °C
        temp_error = 1 + temp_coeff * (temperature - 25)

        # Simulate voltage sensitivity
        voltage_error = 1 + 0.01 * (voltage - 3.3)

        total_error = temp_error * voltage_error - 1  # % error
        return total_error * 100  # Convert to percentage

    results = test_over_corners()

    errors = [r for _, r in results]
    print(f"Monte Carlo samples: {len(results)}")
    print(f"Error range: {min(errors):.2f}% to {max(errors):.2f}%")
    print(f"Mean error: {np.mean(errors):.2f}%")

    return results


def example_4_gwass_adaptive():
    """Example 4: GWASS adaptive sampling for high-gradient regions."""
    print("\n=== Example 4: GWASS Adaptive Sampling ===")

    param_space = ParameterSpace(
        {
            "frequency": (1000, 10000),
            "load_resistance": (10, 1000),
        }
    )

    @gwass(param_space=param_space, budget=40, initial_percentage=0.3)
    def measure_ripple(frequency, load_resistance):
        """Measure output ripple with adaptive sampling."""
        # Simulate a complex frequency response
        f0 = 5000
        response = 1 / (1 + (frequency / f0) ** 4)  # Sharp rolloff

        # Load dependence
        load_factor = np.log10(load_resistance / 10)

        ripple = response * load_factor * 100  # mV
        return ripple

    results = measure_ripple()

    print(f"GWASS budget: 40 points")
    print(f"Actual samples: {len(results)}")

    return results


def visualize_results(results_dict):
    """Visualize results from different sweep strategies."""
    fig, axes = plt.subplots(2, 2, figsize=(12, 10))
    axes = axes.flatten()

    for idx, (title, results) in enumerate(results_dict.items()):
        ax = axes[idx]

        if isinstance(results, list):
            # Extract parameters and values
            x = [p[0] for p, _ in results]
            y = [p[1] for p, _ in results]
            values = [r for _, r in results]

            scatter = ax.scatter(x, y, c=values, cmap="viridis", s=50, alpha=0.6)
            plt.colorbar(scatter, ax=ax, label="Measurement Value")
        else:
            ax.text(0.5, 0.5, "See console output", ha="center", va="center")

        ax.set_title(title)
        ax.set_xlabel("Parameter 1")
        ax.set_ylabel("Parameter 2")
        ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig("sweep_decorator_examples.png", dpi=150)
    print("\n✓ Visualization saved to 'sweep_decorator_examples.png'")


def main():
    """Run all decorator examples."""
    print("Sweep Decorator API Examples")
    print("=" * 60)

    # Run examples
    grid_results = example_1_basic_grid_sweep()
    constraint_results = example_2_with_constraint()
    mc_results = example_3_monte_carlo()
    gwass_results = example_4_gwass_adaptive()

    # Visualize
    results_dict = {
        "Grid Sweep": grid_results,
        "With Constraints": constraint_results,
        "Monte Carlo": mc_results,
        "GWASS Adaptive": gwass_results,
    }

    visualize_results(results_dict)

    print("\n" + "=" * 60)
    print("✅ All decorator examples completed!")
    print("=" * 60)
    print("\nKey takeaways:")
    print("  1. Use keyword arguments matching ParameterSpace names")
    print("  2. @grid_sweep for uniform grid coverage")
    print("  3. @monte_carlo_sweep for random sampling")
    print("  4. @gwass for adaptive sampling in high-gradient regions")


if __name__ == "__main__":
    main()
