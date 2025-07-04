#!/usr/bin/env python3
"""
Advanced Sweep Strategies Example

This example demonstrates how to use both:
1. The built-in parameter sweep capabilities of MeasurementSession
2. The advanced sweep strategies from pytestlab.experiments.sweep

It shows three different approaches:
- Standard MeasurementSession grid sweep (built-in)
- Using grid_sweep from experiments.sweep
- Using gradient-weighted adaptive sampling (gwass)

Each approach has different advantages:
- MeasurementSession: Integrated with the experiment framework
- grid_sweep: More flexible parameter control
- gwass: Adaptively focuses measurements where they matter most
"""
import asyncio
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from typing import Callable, Dict, List, Tuple, Any

from pytestlab.measurements.session import MeasurementSession
from pytestlab.experiments.sweep import grid_sweep, gwass, monte_carlo_sweep
from pytestlab.instruments import AutoInstrument


# Define a sample function to test - a 2D sinusoidal pattern with peaks
def sample_function(x: float, y: float) -> float:
    """Sample function with interesting gradients for testing sweep strategies."""
    return np.sin(x * 3) * np.sin(y * 2) * np.exp(-((x - 2)**2 + (y - 2)**2) / 4)


async def run_measurement_session_sweep():
    """Demonstrate using the built-in MeasurementSession parameter sweep."""
    print("\n1. Using MeasurementSession's built-in grid sweep")
    print("=" * 50)
    
    # Create a measurement session
    async with MeasurementSession(name="Grid Sweep Test") as session:
        # Define parameters for the sweep - creates a grid of x,y points
        x_values = np.linspace(0, 4, 20)
        y_values = np.linspace(0, 4, 20)
        session.parameter("x", x_values, unit="units", notes="X coordinate")
        session.parameter("y", y_values, unit="units", notes="Y coordinate")
        
        # Define a measurement function
        @session.acquire
        async def measure_function(x: float, y: float):
            """Measure our sample function at the given coordinates."""
            # In a real scenario, this would interact with instruments
            result = sample_function(x, y)
            print(f"Measuring at x={x:.2f}, y={y:.2f}: result={result:.4f}")
            
            # Simulate some processing time
            await asyncio.sleep(0.01)
            
            return {"z": result}
        
        # Run the measurement sweep
        print("Running MeasurementSession sweep...")
        experiment = await session.run(show_progress=True)
        
        # Return the results for comparison
        return experiment.data.to_numpy()


async def run_grid_sweep():
    """Demonstrate using grid_sweep from experiments.sweep."""
    print("\n2. Using grid_sweep from experiments.sweep")
    print("=" * 50)
    
    # Define parameter ranges
    param_ranges = [(0, 4), (0, 4)]  # (x_min, x_max), (y_min, y_max)
    
    # Number of points in each dimension
    points_per_dim = 20
    
    # Create an async wrapper for our sample function
    async def async_sample_function(x: float, y: float) -> float:
        # Simulate some processing time
        await asyncio.sleep(0.01)
        return sample_function(x, y)
    
    # We need to wrap our async function to work with grid_sweep
    # which expects a synchronous function
    def wrapper_func(x: float, y: float) -> float:
        # Run the async function in the event loop
        result = asyncio.get_event_loop().run_until_complete(async_sample_function(x, y))
        print(f"Grid sweep measuring at x={x:.2f}, y={y:.2f}: result={result:.4f}")
        return result
    
    # Run the grid sweep
    print("Running grid_sweep...")
    results = grid_sweep(wrapper_func, param_ranges, points_per_dim)
    
    # Format results for comparison
    result_array = np.array([
        [x, y, z] for ([x, y], z) in results
    ])
    
    return result_array


async def run_gwass_sweep():
    """Demonstrate using gradient-weighted adaptive sampling from experiments.sweep."""
    print("\n3. Using gwass (Gradient-Weighted Adaptive Sampling)")
    print("=" * 50)
    
    # Define parameter ranges
    param_ranges = [(0, 4), (0, 4)]  # (x_min, x_max), (y_min, y_max)
    
    # Total number of sample points
    total_points = 400  # 20x20
    
    # Create an async wrapper for our sample function
    async def async_sample_function(x: float, y: float) -> float:
        await asyncio.sleep(0.01)
        return sample_function(x, y)
    
    # Wrapper function for gwass
    def wrapper_func(x: float, y: float) -> float:
        result = asyncio.get_event_loop().run_until_complete(async_sample_function(x, y))
        print(f"GWASS measuring at x={x:.2f}, y={y:.2f}: result={result:.4f}")
        return result
    
    # Run the gwass sweep
    print("Running gwass sweep...")
    results = gwass(wrapper_func, param_ranges, total_points)
    
    # Format results for comparison
    result_array = np.array([
        [x, y, z] for ([x, y], z) in results
    ])
    
    return result_array


def plot_results(
    grid_results: np.ndarray, 
    grid_sweep_results: np.ndarray, 
    gwass_results: np.ndarray
):
    """Plot and compare the results from different sweep strategies."""
    plt.figure(figsize=(18, 6))
    
    # Plot MeasurementSession results
    plt.subplot(131)
    x = grid_results[:, 0]
    y = grid_results[:, 1]
    z = grid_results[:, 2]
    plt.scatter(x, y, c=z, cmap='viridis', s=30)
    plt.colorbar(label='z value')
    plt.title('MeasurementSession Grid Sweep\n(Regular Grid)')
    plt.xlabel('x')
    plt.ylabel('y')
    
    # Plot grid_sweep results
    plt.subplot(132)
    x = grid_sweep_results[:, 0]
    y = grid_sweep_results[:, 1]
    z = grid_sweep_results[:, 2]
    plt.scatter(x, y, c=z, cmap='viridis', s=30)
    plt.colorbar(label='z value')
    plt.title('grid_sweep Results\n(Regular Grid)')
    plt.xlabel('x')
    plt.ylabel('y')
    
    # Plot gwass results
    plt.subplot(133)
    x = gwass_results[:, 0]
    y = gwass_results[:, 1]
    z = gwass_results[:, 2]
    plt.scatter(x, y, c=z, cmap='viridis', s=30)
    plt.colorbar(label='z value')
    plt.title('GWASS Results\n(Adaptive Sampling)')
    plt.xlabel('x')
    plt.ylabel('y')
    
    plt.tight_layout()
    plt.savefig('sweep_comparison.png')
    print("Results visualization saved to 'sweep_comparison.png'")
    
    # Create a figure for function visualization
    plt.figure(figsize=(10, 8))
    x = np.linspace(0, 4, 100)
    y = np.linspace(0, 4, 100)
    X, Y = np.meshgrid(x, y)
    Z = sample_function(X, Y)
    
    plt.contourf(X, Y, Z, 50, cmap='viridis')
    plt.colorbar(label='z value')
    plt.title('Sample Function Visualization')
    plt.xlabel('x')
    plt.ylabel('y')
    plt.savefig('function_visualization.png')
    print("Function visualization saved to 'function_visualization.png'")


async def main():
    # Run all three sweep strategies
    grid_results = await run_measurement_session_sweep()
    grid_sweep_results = await run_grid_sweep()
    gwass_results = await run_gwass_sweep()
    
    # Compare the results
    print("\nComparing Results")
    print("=" * 50)
    print(f"MeasurementSession: {len(grid_results)} points")
    print(f"grid_sweep: {len(grid_sweep_results)} points")
    print(f"gwass: {len(gwass_results)} points")
    
    # Plot the results
    plot_results(grid_results, grid_sweep_results, gwass_results)
    
    print("\nComparison Summary:")
    print("- MeasurementSession's built-in sweep is best for standard experiment workflows")
    print("- grid_sweep offers more control over parameter spacing")
    print("- gwass adaptively focuses measurements where gradients are high")
    print("  (Notice how points are concentrated in high-gradient regions)")


if __name__ == "__main__":
    print("PyTestLab Advanced Sweep Strategies Example")
    print("=" * 60)
    
    try:
        # Run the main function
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⚠️ Example interrupted by user.")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()