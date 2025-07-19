#!/usr/bin/env python3
"""
Comprehensive Bench + MeasurementSession + Sweep Example

Demonstrates:
- Loading a bench from YAML
- Creating a MeasurementSession using the bench
- Defining parameters and constraints
- Using built-in grid sweep, decorator-based grid sweep, Monte Carlo, and GWASS
- Collecting and visualizing results

Requires:
    - pytestlab
    - numpy
    - polars
    - matplotlib
    - tqdm

Edit the bench YAML path as needed for your setup.
"""

import asyncio
import numpy as np
import polars as pl
import matplotlib.pyplot as plt
from pathlib import Path

from pytestlab.bench import Bench
from pytestlab.measurements.session import MeasurementSession
from pytestlab.experiments.sweep import (
    grid_sweep,
    monte_carlo_sweep,
    gwass,
    ParameterSpace
)

# Path to your bench YAML file
BENCH_YAML = Path(__file__).parent / "session_bench.yaml"

def visualize_results(results_dict):
    """
    Visualize and compare results from different sweep strategies.
    """
    plt.figure(figsize=(18, 5))
    for i, (label, results) in enumerate(results_dict.items(), 1):
        if isinstance(results, pl.DataFrame):
            df = results
            vb = df['V_base'].to_numpy()
            vc = df['V_collector'].to_numpy()
            ic = df['I_collector'].to_numpy()
        else:
            vb = np.array([params[0] for params, _ in results])
            vc = np.array([params[1] for params, _ in results])
            ic = np.array([out for _, out in results])
        plt.subplot(1, len(results_dict), i)
        plt.scatter(vc, vb, c=ic, cmap='viridis', s=50)
        plt.colorbar(label='Collector Current (A)')
        plt.title(label)
        plt.xlabel('Collector Voltage (V)')
        plt.ylabel('Base Voltage (V)')
        plt.grid(True)
    plt.tight_layout()
    plt.savefig("bench_sweep_comparison.png", dpi=150)
    print("Visualization saved to 'bench_sweep_comparison.png'")

async def main():
    print("=== Bench + MeasurementSession + Sweep Example ===")
    async with await Bench.open(BENCH_YAML) as bench:
        print(f"Bench loaded: {bench.name}")

        # --- 1. Built-in MeasurementSession grid sweep ---
        async with MeasurementSession(bench=bench) as session:
            session.parameter("V_base", np.linspace(0.6, 1.0, 5), unit="V", notes="Base voltage")
            session.parameter("V_collector", np.linspace(0, 5, 10), unit="V", notes="Collector voltage")

            @session.acquire
            async def measure(V_base, V_collector, psu, dmm):
                await psu.set_voltage(1, V_base)
                await psu.set_current(1, 0.05)
                await psu.set_voltage(2, V_collector)
                await psu.set_current(2, 0.5)
                await psu.output(1, True)
                await psu.output(2, True)
                await asyncio.sleep(0.05)
                result = await dmm.measure_current_dc()
                await psu.output(1, False)
                await psu.output(2, False)
                return {
                    "I_collector": result.values.nominal_value,
                    "V_base": V_base,
                    "V_collector": V_collector,
                }

            print("Running built-in grid sweep...")
            experiment = await session.run(show_progress=True)
            built_in_results = experiment.data
            print(f"Built-in sweep: {len(built_in_results)} points")

        # --- 2. Decorator-based grid sweep with ParameterSpace and constraint ---
        def valid_region(params):
            # Only allow V_base > 0.7 and V_collector > 1.0
            return params["V_base"] > 0.7 and params["V_collector"] > 1.0

        param_space = ParameterSpace(
            {"V_base": (0.6, 1.0), "V_collector": (0, 5)},
            constraint=valid_region
        )

        @grid_sweep(param_space=param_space, points=6)
        def grid_measure(params):
            V_base, V_collector = params
            # Simulate a measurement (replace with real instrument code)
            I_collector = (V_base - 0.6) * (V_collector / 5) * 0.01
            return I_collector

        print("Running decorator-based grid sweep...")
        grid_results = grid_measure()

        # --- 3. Monte Carlo sweep ---
        @monte_carlo_sweep(param_space=param_space, samples=40)
        def mc_measure(params):
            V_base, V_collector = params
            I_collector = (V_base - 0.6) * (V_collector / 5) * 0.01
            return I_collector

        print("Running Monte Carlo sweep...")
        mc_results = mc_measure()

        # --- 4. GWASS adaptive sweep ---
        @gwass(param_space=param_space, budget=30, initial_percentage=0.2)
        def gwass_measure(params):
            V_base, V_collector = params
            I_collector = (V_base - 0.6) * (V_collector / 5) * 0.01
            return I_collector

        print("Running GWASS adaptive sweep...")
        gwass_results = gwass_measure()

        # --- Visualization ---
        visualize_results({
            "Built-in Grid": built_in_results,
            "Grid Sweep": grid_results,
            "Monte Carlo": mc_results,
            "GWASS": gwass_results,
        })

        print("All sweeps complete.")

if __name__ == "__main__":
    asyncio.run(main())
