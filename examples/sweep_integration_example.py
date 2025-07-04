#!/usr/bin/env python3
"""
Sweep Integration Example

This example demonstrates the improved integration between:
- MeasurementSession's built-in parameter sweep
- The advanced sweep strategies in pytestlab.experiments.sweep
- Automatic parameter extraction from MeasurementSession

Three different approaches are demonstrated:
1. MeasurementSession's built-in parameter grid sweep (complete Cartesian product)
2. Grid sweep decorator with auto parameter extraction
3. Gradient-weighted adaptive sampling (GWASS) for efficiency
"""
import asyncio
import time
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime

from pytestlab.measurements.session import MeasurementSession
from pytestlab.experiments.sweep import (
    grid_sweep,
    gwass,
    monte_carlo_sweep,
    ParameterSpace
)
from pytestlab.instruments import AutoInstrument


async def example_1_built_in_sweep():
    """
    Example 1: Using MeasurementSession's built-in grid sweep.
    
    This is the standard approach that creates a complete Cartesian product
    of all parameter values.
    """
    print("\n1. MeasurementSession's Built-in Grid Sweep")
    print("=" * 50)
    
    # Create a measurement session
    async with MeasurementSession(
        name="Transistor Characterization", 
        description="Standard parameter sweep"
    ) as session:
        # Define sweep parameters
        session.parameter(
            "base_voltage", 
            np.linspace(0.6, 0.8, 5), 
            unit="V", 
            notes="Transistor base voltage"
        )
        session.parameter(
            "collector_voltage", 
            np.linspace(0, 5, 6), 
            unit="V", 
            notes="Transistor collector voltage"
        )
        
        # Set up simulated instruments
        psu_base = await session.instrument("psu_base", "keysight/EDU36311A", simulate=True)
        psu_collector = await session.instrument("psu_collector", "keysight/EDU36311A", simulate=True)
        dmm = await session.instrument("dmm", "keysight/EDU34450A", simulate=True)
        
        # Define measurement function with session.acquire
        @session.acquire
        async def measure_collector_current(base_voltage, collector_voltage, psu_base, psu_collector, dmm):
            """Measure transistor collector current."""
            print(f"Measuring at Vb={base_voltage:.2f}V, Vc={collector_voltage:.2f}V")
            
            # Set voltages
            await psu_base.set_voltage(1, base_voltage)
            await psu_collector.set_voltage(1, collector_voltage)
            
            # Turn on outputs
            await psu_base.output(1, True)
            await psu_collector.output(1, True)
            
            # Small delay to simulate settling time
            await asyncio.sleep(0.01)
            
            # Simulate a measurement
            # In a real scenario, we'd use dmm.measure_current_dc()
            
            # Simulate transistor behavior: Ic = β * Ib * (1 - exp(-Vc/Vt))
            beta = 100  # Current gain
            Rb = 10000  # Base resistor in ohms
            Ib = (base_voltage - 0.6) / Rb if base_voltage > 0.6 else 0
            Vt = 0.026  # Thermal voltage
            
            Ic = beta * Ib * (1 - np.exp(-collector_voltage / Vt))
            Ic *= (0.9 + 0.2 * np.random.random())  # Add randomness
            
            # Turn off outputs
            await psu_base.output(1, False)
            await psu_collector.output(1, False)
            
            return {
                "collector_current": Ic,
                "base_current": Ib,
                "gain": Ic / Ib if Ib > 0 else 0
            }
        
        # Run the sweep and measure execution time
        print(f"Running built-in sweep with {5 * 6} parameter combinations...")
        start_time = time.time()
        experiment = await session.run(show_progress=True)
        elapsed = time.time() - start_time
        
        print(f"✓ Built-in sweep completed in {elapsed:.2f} seconds")
        print(f"  Data points collected: {len(experiment.data)}")
        
        return experiment


async def example_2_grid_sweep():
    """
    Example 2: Using the grid_sweep_decorator with auto parameter extraction.
    
    This uses the same parameter grid as the built-in sweep but demonstrates
    how to use the grid_sweep_decorator with auto parameter extraction.
    """
    print("\n2. Grid Sweep Decorator with Auto Parameter Extraction")
    print("=" * 50)
    
    # Create a measurement session
    async with MeasurementSession(
        name="Transistor Grid Sweep", 
        description="Grid sweep with decorator"
    ) as session:
        # Define the same parameters as in example 1
        session.parameter(
            "base_voltage", 
            np.linspace(0.6, 0.8, 5), 
            unit="V", 
            notes="Transistor base voltage"
        )
        session.parameter(
            "collector_voltage", 
            np.linspace(0, 5, 6), 
            unit="V", 
            notes="Transistor collector voltage"
        )
        
        # Set up simulated instruments
        psu_base = await session.instrument("psu_base", "keysight/EDU36311A", simulate=True)
        psu_collector = await session.instrument("psu_collector", "keysight/EDU36311A", simulate=True)
        dmm = await session.instrument("dmm", "keysight/EDU34450A", simulate=True)
        
        # Create a wrapper around the sync measurement function
        # Use grid_sweep_decorator with "auto" parameter extraction
        # q_n=10 means 10 points per dimension - using a sparser grid than the built-in sweep
        # Define a constraint function for valid parameter combinations
        def valid_parameters(params):
            """Only measure points where collector voltage > 5 * (base voltage - 0.6)"""
            vb = params["base_voltage"]
            vc = params["collector_voltage"]
            return vc > 5 * (vb - 0.6) if vb > 0.6 else True
        
        # Create parameter space with constraint
        param_space = ParameterSpace("auto", constraint=valid_parameters)
        
        # Use cleaner grid_sweep decorator with parameter space
        # points=10 means 10 points per dimension
        @grid_sweep(param_space=param_space, points=10)
        def measure_transistor(base_voltage, collector_voltage):
            """Synchronous measurement function that will be swept."""
            print(f"Grid sweep measuring at Vb={base_voltage:.2f}V, Vc={collector_voltage:.2f}V")
            
            # Simulate transistor behavior (synchronous version)
            beta = 100  # Current gain
            Rb = 10000  # Base resistor in ohms
            Ib = (base_voltage - 0.6) / Rb if base_voltage > 0.6 else 0
            Vt = 0.026  # Thermal voltage
            
            Ic = beta * Ib * (1 - np.exp(-collector_voltage / Vt))
            Ic *= (0.9 + 0.2 * np.random.random())  # Add randomness
            
            # Pause to simulate measurement time
            time.sleep(0.01)
            
            # Return a single value (the collector current)
            return Ic
        
        # Execute the grid sweep and time it
        print(f"Running grid_sweep with auto parameter extraction...")
        start_time = time.time()
        results = measure_transistor(session)  # Pass session to extract parameters
        elapsed = time.time() - start_time
        
        print(f"✓ Grid sweep completed in {elapsed:.2f} seconds")
        print(f"  Data points collected: {len(results)}")
        
        return results


async def example_3_gwass_sweep():
    """
    Example 3: Using the gwass_decorator for adaptive sampling.
    
    This demonstrates how to use the Gradient-Weighted Adaptive Sampling
    strategy to efficiently explore the parameter space by focusing on
    regions with high gradients.
    """
    print("\n3. Gradient-Weighted Adaptive Sampling (GWASS)")
    print("=" * 50)
    
    # Create a measurement session
    async with MeasurementSession(
        name="Transistor Adaptive Sampling", 
        description="GWASS adaptive sampling"
    ) as session:
        # Define the same parameters as in previous examples
        session.parameter(
            "base_voltage", 
            np.linspace(0.6, 0.8, 5), 
            unit="V", 
            notes="Transistor base voltage"
        )
        session.parameter(
            "collector_voltage", 
            np.linspace(0, 5, 6), 
            unit="V", 
            notes="Transistor collector voltage"
        )
        
        # Set up simulated instruments
        psu_base = await session.instrument("psu_base", "keysight/EDU36311A", simulate=True)
        psu_collector = await session.instrument("psu_collector", "keysight/EDU36311A", simulate=True)
        dmm = await session.instrument("dmm", "keysight/EDU34450A", simulate=True)
        
        # Directly specify parameter ranges as a dictionary
        param_ranges = {
            "base_voltage": (0.6, 0.8),
            "collector_voltage": (0, 5)
        }
        
        # Use cleaner gwass decorator with explicit parameter ranges
        # budget=30 means 30 total evaluation points (instead of a full grid)
        # initial_percentage=0.3 means 30% of points are used for initial grid
        @gwass(param_ranges, budget=30, initial_percentage=0.3)
        def measure_transistor(base_voltage, collector_voltage):
            """Synchronous measurement function that will be adaptively sampled."""
            print(f"GWASS measuring at Vb={base_voltage:.2f}V, Vc={collector_voltage:.2f}V")
            
            # Simulate transistor behavior (synchronous version)
            beta = 100  # Current gain
            Rb = 10000  # Base resistor in ohms
            Ib = (base_voltage - 0.6) / Rb if base_voltage > 0.6 else 0
            Vt = 0.026  # Thermal voltage
            
            # Create a non-linear response with a "knee" region
            # to demonstrate GWASS's ability to focus on high-gradient areas
            if collector_voltage < 0.7:
                Ic = beta * Ib * (collector_voltage / 0.7)**2
            else:
                Ic = beta * Ib * (1 - 0.3*np.exp(-(collector_voltage-0.7) / Vt))
            
            Ic *= (0.95 + 0.1 * np.random.random())  # Add slight randomness
            
            # Pause to simulate measurement time
            time.sleep(0.01)
            
            # Return a single value (the collector current)
            return Ic
        
        # Execute the GWASS sweep and time it
        print(f"Running GWASS with auto parameter extraction...")
        print(f"Using only 30 points instead of the full {5 * 6} grid")
        start_time = time.time()
        results = measure_transistor(session)  # Pass session to extract parameters
        elapsed = time.time() - start_time
        
        print(f"✓ GWASS sweep completed in {elapsed:.2f} seconds")
        print(f"  Data points collected: {len(results)}")
        
        return results


def visualize_results(standard_results, grid_results, gwass_results):
    """
    Visualize and compare the results from the different sweep methods.
    
    Args:
        standard_results: Result from built-in MeasurementSession sweep
        grid_results: Result from grid_sweep_decorator
        gwass_results: Result from gwass_decorator
    """
    plt.figure(figsize=(18, 12))
    
    # 1. Extract data from standard MeasurementSession results
    df = standard_results.data.to_pandas()
    vb_std = df['base_voltage'].values
    vc_std = df['collector_voltage'].values
    ic_std = df['collector_current'].values
    
    # 2. Process grid sweep results
    vb_grid = np.array([params[0] for params, result in grid_results])
    vc_grid = np.array([params[1] for params, result in grid_results])
    ic_grid = np.array([result for params, result in grid_results])
    
    # 3. Process GWASS results
    vb_gwass = np.array([params[0] for params, result in gwass_results])
    vc_gwass = np.array([params[1] for params, result in gwass_results])
    ic_gwass = np.array([result for params, result in gwass_results])
    
    # Plot 1: Standard sweep - scatter points
    plt.subplot(2, 3, 1)
    plt.scatter(vc_std, vb_std, c=ic_std, cmap='viridis', s=50)
    plt.colorbar(label='Collector Current (A)')
    plt.title('Standard Sweep\nParameter Points')
    plt.xlabel('Collector Voltage (V)')
    plt.ylabel('Base Voltage (V)')
    plt.grid(True)
    
    # Plot 2: Grid sweep - scatter points
    plt.subplot(2, 3, 2)
    plt.scatter(vc_grid, vb_grid, c=ic_grid, cmap='viridis', s=50)
    plt.colorbar(label='Collector Current (A)')
    plt.title('Grid Sweep\nParameter Points')
    plt.xlabel('Collector Voltage (V)')
    plt.ylabel('Base Voltage (V)')
    plt.grid(True)
    
    # Plot 3: GWASS - scatter points (notice clustering in high-gradient areas)
    plt.subplot(2, 3, 3)
    plt.scatter(vc_gwass, vb_gwass, c=ic_gwass, cmap='viridis', s=50)
    plt.colorbar(label='Collector Current (A)')
    plt.title('GWASS\nAdaptive Parameter Points')
    plt.xlabel('Collector Voltage (V)')
    plt.ylabel('Base Voltage (V)')
    plt.grid(True)
    
    # Plot 4: Standard sweep - 3D surface
    ax = plt.subplot(2, 3, 4, projection='3d')
    ax.scatter(vc_std, vb_std, ic_std, c=ic_std, cmap='viridis')
    ax.set_title('Standard Sweep\n3D Visualization')
    ax.set_xlabel('Collector Voltage (V)')
    ax.set_ylabel('Base Voltage (V)')
    ax.set_zlabel('Collector Current (A)')
    
    # Plot 5: Grid sweep - 3D surface
    ax = plt.subplot(2, 3, 5, projection='3d')
    ax.scatter(vc_grid, vb_grid, ic_grid, c=ic_grid, cmap='viridis')
    ax.set_title('Grid Sweep\n3D Visualization')
    ax.set_xlabel('Collector Voltage (V)')
    ax.set_ylabel('Base Voltage (V)')
    ax.set_zlabel('Collector Current (A)')
    
    # Plot 6: GWASS - 3D surface
    ax = plt.subplot(2, 3, 6, projection='3d')
    ax.scatter(vc_gwass, vb_gwass, ic_gwass, c=ic_gwass, cmap='viridis')
    ax.set_title('GWASS\n3D Visualization')
    ax.set_xlabel('Collector Voltage (V)')
    ax.set_ylabel('Base Voltage (V)')
    ax.set_zlabel('Collector Current (A)')
    
    # Adjust layout and save
    plt.tight_layout()
    plt.savefig('sweep_comparison_visualization.png', dpi=150)
    print("Visualization saved to 'sweep_comparison_visualization.png'")


async def main():
    """Main function to run all examples and compare results."""
    print("PyTestLab Sweep Integration Example")
    print("=" * 60)
    
    # Run all three examples
    standard_results = await example_1_built_in_sweep()
    grid_results = await example_2_grid_sweep()
    gwass_results = await example_3_gwass_sweep()
    
    # Visualize and compare results
    print("\nVisualizing results...")
    visualize_results(standard_results, grid_results, gwass_results)
    
    print("\nSummary:")
    print("1. Standard MeasurementSession sweep:")
    print("   - Complete Cartesian product of parameter values")
    print("   - Best for comprehensive parameter coverage")
    print("   - Integrates directly with experiment data")
    
    print("\n2. Grid sweep with auto parameter extraction:")
    print("   - Uses the same parameter ranges but can use different grid density")
    print("   - Flexible parameter control via decorator")
    print("   - Can be used with both sync and async measurement functions")
    
    print("\n3. GWASS with adaptive sampling:")
    print("   - Efficient exploration of parameter space")
    print("   - Focuses sampling on high-gradient regions")
    print("   - Uses fewer points while capturing important features")
    
    print("\nAdvantages of the new integration:")
    print("- Parameter ranges can be automatically extracted from MeasurementSession")
    print("- Sweep strategies can be applied as decorators on measurement functions")
    print("- Compatible with both synchronous and asynchronous functions")
    print("- Offers multiple sampling strategies for different measurement needs")
    print("- Supports parameter constraints for defining valid measurement regions")
    print("- Provides a flexible ParameterSpace class for advanced parameter control")


if __name__ == "__main__":
    try:
        # Run the main function
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⚠️ Example interrupted by user.")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()