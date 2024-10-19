import numpy as np
import time
from multiprocessing import Pool, cpu_count
from functools import partial
from skopt import gp_minimize
from skopt.space import Real
import dask
import dask.array as da
from dask.distributed import Client, progress
from scipy.stats import qmc
from matplotlib import pyplot as plt
# ==========================================
# Helper Functions (Moved to Top Level)
# ==========================================

def f_evaluate(params, f):
    return f(*params)

# ==========================================
# Adaptive Sweep Functions
# ==========================================

def adaptive_sweep(f, param_ranges, q_n, refinement_factor=1, tolerance=float('inf')):
    """
    Perform an adaptive sweep over the parameter space of a function `f`.
    Args:
        f (function): The function to be evaluated. It should take `n` parameters.
        param_ranges (list of tuples): A list of (min, max) for each parameter.
        q_n (int or list of ints): The number of points to sample along each parameter.
        refinement_factor (int): Set to 1 to avoid additional refinements.
        tolerance (float): Set to a high value to prevent refinements.
    Returns:
        results (list): A list of tuples containing parameter combinations and the corresponding function outputs.
    """
    num_params = len(param_ranges)
    if isinstance(q_n, int):
        q_n = [q_n] * num_params
    elif len(q_n) != num_params:
        raise ValueError("q_n must be an integer or a list with length equal to the number of parameters.")

    coarse_grid = [np.linspace(min_val, max_val, q_n[i]) for i, (min_val, max_val) in enumerate(param_ranges)]
    param_mesh = np.meshgrid(*coarse_grid, indexing='ij')
    param_combinations = np.array([p.flatten() for p in param_mesh]).T

    # Evaluate the function over the coarse grid
    coarse_results = [(params.tolist(), f(*params)) for params in param_combinations]

    # Since we are not refining, we return the coarse results
    return coarse_results

def adaptive_sweep_multiprocessing(f, param_ranges, q_n, refinement_factor=1, tolerance=float('inf'), max_depth=0):
    """
    Perform an adaptive sweep over the parameter space of a function `f` using multiprocessing.
    Args:
        f (function): The function to be evaluated. It should take `n` parameters.
        param_ranges (list of tuples): A list of (min, max) for each parameter.
        q_n (int or list of ints): The number of points to sample along each parameter.
        refinement_factor (int): Set to 1 to avoid additional refinements.
        tolerance (float): Set to a high value to prevent refinements.
        max_depth (int): Set to 0 to prevent recursion and refinements.
    Returns:
        results (list): A list of tuples containing parameter combinations and the corresponding function outputs.
    """
    num_params = len(param_ranges)
    if isinstance(q_n, int):
        q_n = [q_n] * num_params
    elif len(q_n) != num_params:
        raise ValueError("q_n must be an integer or a list with length equal to the number of parameters.")

    def recursive_refine(ranges, qn, depth):
        coarse_grids = [np.linspace(min_val, max_val, qn[i]) for i, (min_val, max_val) in enumerate(ranges)]
        param_mesh = np.meshgrid(*coarse_grids, indexing='ij')
        params_list = np.array([p.flatten() for p in param_mesh]).T

        # Evaluate the function in parallel
        with Pool(processes=cpu_count()) as pool:
            results_values = pool.map(partial(f_evaluate, f=f), params_list)

        return list(zip(params_list.tolist(), results_values))

    final_results = recursive_refine(param_ranges, q_n, depth=0)
    final_results = list(set([(tuple(res[0]), res[1]) for res in final_results]))
    final_results.sort(key=lambda x: x[0])

    # Convert tuples back to lists for consistency
    final_results = [(list(params), result) for params, result in final_results]

    return final_results

# ==========================================
# Gradient-Based Adaptive Sampling
# ==========================================

def gradient_based_sweep(f, param_ranges, q_n, refinement_factor=1, tolerance=float('inf')):
    """
    Perform a sweep over the parameter space based on gradient changes.
    Args:
        f (function): The function to evaluate.
        param_ranges (list of tuples): A list of (min, max) for each parameter.
        q_n (int or list of ints): Number of points to sample along each parameter.
        refinement_factor (int): Set to 1 to avoid additional refinements.
        tolerance (float): Set to a high value to prevent refinements.
    Returns:
        results (list): Parameter combinations and corresponding function values.
    """
    num_params = len(param_ranges)
    # Ensure q_n is a list of integers, one per parameter
    if isinstance(q_n, int):
        q_n = [q_n] * num_params
    elif len(q_n) != num_params:
        raise ValueError("q_n must be an integer or a list with length equal to the number of parameters.")

    coarse_grid = [np.linspace(min_val, max_val, q_n[i]) for i, (min_val, max_val) in enumerate(param_ranges)]
    param_mesh = np.meshgrid(*coarse_grid, indexing='ij')
    params_list = np.array([p.flatten() for p in param_mesh]).T

    # Evaluate the function over the coarse grid
    coarse_values = np.array([f(*params) for params in params_list])

    # Since we are not refining, we return the coarse results
    results = [(params.tolist(), value) for params, value in zip(params_list, coarse_values)]
    results.sort(key=lambda x: x[0])

    return results

# ==========================================
# Bayesian Optimization Sweep
# ==========================================

def bayesian_sweep(f, param_ranges, n_calls=50, n_initial_points=10):
    """
    Perform Bayesian optimization to explore the parameter space.
    Args:
        f (function): The function to be evaluated.
        param_ranges (list of tuples): A list of (min, max) for each parameter.
        n_calls (int): Total number of function evaluations.
        n_initial_points (int): Number of random initial samples.
    Returns:
        results (list): Parameter combinations and corresponding function outputs.
    """
    bounds = [Real(min_val, max_val) for min_val, max_val in param_ranges]

    def wrapper(params):
        return f(*params)

    res = gp_minimize(wrapper, bounds, n_calls=n_calls, n_initial_points=n_initial_points, random_state=42)

    results = [(list(res.x_iters[i]), res.func_vals[i]) for i in range(len(res.x_iters))]
    results.sort(key=lambda x: x[0])
    return results

# ==========================================
# Distributed Adaptive Sweep
# ==========================================

def distributed_adaptive_sweep(f, param_ranges, q_n, refinement_factor=1, tolerance=float('inf'), max_depth=0):
    """
    Distributed adaptive sweep using Dask for scaling computation.
    Args:
        f (function): Function to evaluate.
        param_ranges (list of tuples): A list of (min, max) for each parameter.
        q_n (int or list of ints): Number of points to sample along each parameter.
        refinement_factor (int): Set to 1 to avoid additional refinements.
        tolerance (float): Set to a high value to prevent refinements.
        max_depth (int): Set to 0 to prevent recursion and refinements.
    Returns:
        results (list): Parameter combinations and function outputs.
    """
    client = Client()

    num_params = len(param_ranges)
    # Ensure q_n is a list of integers, one per parameter
    if isinstance(q_n, int):
        q_n = [q_n] * num_params
    elif len(q_n) != num_params:
        raise ValueError("q_n must be an integer or a list with length equal to the number of parameters.")

    def recursive_refine(ranges, qn, depth):
        coarse_grids = [np.linspace(min_val, max_val, qn[i]) for i, (min_val, max_val) in enumerate(ranges)]
        param_mesh = np.meshgrid(*coarse_grids, indexing='ij')
        params_list = np.array([p.flatten() for p in param_mesh]).T

        # Delay function evaluation for distributed computation
        delayed_results = [dask.delayed(f)(*params) for params in params_list]
        coarse_values = dask.compute(*delayed_results)

        # Since we are not refining, we return the coarse results
        results = [(params.tolist(), value) for params, value in zip(params_list, coarse_values)]
        return results

    final_results = recursive_refine(param_ranges, q_n, depth=0)
    final_results = list(set([(tuple(res[0]), res[1]) for res in final_results]))
    final_results.sort(key=lambda x: x[0])

    # Convert tuples back to lists for consistency
    final_results = [(list(params), result) for params, result in final_results]

    client.close()
    return final_results

# ==========================================
# Uncertainty Quantification Sweep
# ==========================================

def uncertainty_quantification_sweep(f, param_ranges, q_n, n_samples=1):
    """
    Perform a parameter sweep with uncertainty quantification by sampling multiple times.
    Args:
        f (function): The function to be evaluated.
        param_ranges (list of tuples): A list of (min, max) for each parameter.
        q_n (int or list of ints): Number of points to sample along each parameter.
        n_samples (int): Number of samples for each parameter combination.
    Returns:
        results (list): Parameter combinations and corresponding mean and variance of outputs.
    """
    num_params = len(param_ranges)
    # Ensure q_n is a list of integers, one per parameter
    if isinstance(q_n, int):
        q_n = [q_n] * num_params
    elif len(q_n) != num_params:
        raise ValueError("q_n must be an integer or a list with length equal to the number of parameters.")

    grid = [np.linspace(min_val, max_val, q_n[i]) for i, (min_val, max_val) in enumerate(param_ranges)]
    param_mesh = np.meshgrid(*grid, indexing='ij')
    params_list = np.array([p.flatten() for p in param_mesh]).T

    results = []
    for params in params_list:
        samples = np.array([f(*params) for _ in range(n_samples)])
        mean = samples.mean()
        variance = samples.var()
        results.append((params.tolist(), mean, variance))

    return results

# ==========================================
# Monte Carlo Sweep
# ==========================================

def monte_carlo_sweep(f, param_ranges, n_samples):
    """
    Perform a Monte Carlo sweep by randomly sampling the parameter space.
    Args:
        f (function): The function to be evaluated.
        param_ranges (list of tuples): A list of (min, max) for each parameter.
        n_samples (int): Number of random samples to generate.
    Returns:
        results (list): Parameter combinations and corresponding function outputs.
    """
    num_params = len(param_ranges)
    samples = []
    for _ in range(n_samples):
        params = [np.random.uniform(min_val, max_val) for min_val, max_val in param_ranges]
        result = f(*params)
        samples.append((params, result))
    samples.sort(key=lambda x: x[0])
    return samples

# ==========================================
# Additional Relevant Functions
# ==========================================

def latin_hypercube_sweep(f, param_ranges, n_samples):
    """
    Perform a Latin Hypercube Sampling sweep over the parameter space.
    Args:
        f (function): The function to be evaluated.
        param_ranges (list of tuples): A list of (min, max) for each parameter.
        n_samples (int): Number of samples to generate.
    Returns:
        results (list): Parameter combinations and corresponding function outputs.
    """
    num_params = len(param_ranges)
    sampler = qmc.LatinHypercube(d=num_params)
    unit_lhs = sampler.random(n=n_samples)
    samples = []
    for i in range(n_samples):
        params = [unit_lhs[i][j] * (param_ranges[j][1] - param_ranges[j][0]) + param_ranges[j][0] for j in range(num_params)]
        result = f(*params)
        samples.append((params, result))
    samples.sort(key=lambda x: x[0])
    return samples

def sobol_sequence_sweep(f, param_ranges, n_samples):
    """
    Perform a Sobol sequence sampling sweep over the parameter space.
    Args:
        f (function): The function to be evaluated.
        param_ranges (list of tuples): A list of (min, max) for each parameter.
        n_samples (int): Number of samples to generate. Should be a power of 2.
    Returns:
        results (list): Parameter combinations and corresponding function outputs.
    """
    num_params = len(param_ranges)
    sampler = qmc.Sobol(d=num_params, scramble=False)
    # Adjust n_samples to the next power of 2
    m = int(np.ceil(np.log2(n_samples)))
    n_samples = 2 ** m
    unit_sobol = sampler.random_base2(m=m)
    samples = []
    for i in range(unit_sobol.shape[0]):
        params = [unit_sobol[i][j] * (param_ranges[j][1] - param_ranges[j][0]) + param_ranges[j][0] for j in range(num_params)]
        result = f(*params)
        samples.append((params, result))
    samples.sort(key=lambda x: x[0])
    return samples

def grid_sweep(f, param_ranges, q_n):
    """
    Perform a simple grid sweep over the parameter space.
    Args:
        f (function): The function to be evaluated.
        param_ranges (list of tuples): A list of (min, max) for each parameter.
        q_n (int or list of ints): Number of points to sample along each parameter.
    Returns:
        results (list): Parameter combinations and corresponding function outputs.
    """
    num_params = len(param_ranges)
    # Ensure q_n is a list of integers, one per parameter
    if isinstance(q_n, int):
        q_n = [q_n] * num_params
    elif len(q_n) != num_params:
        raise ValueError("q_n must be an integer or a list with length equal to the number of parameters.")

    grids = [np.linspace(min_val, max_val, q_n[i]) for i, (min_val, max_val) in enumerate(param_ranges)]
    param_mesh = np.meshgrid(*grids, indexing='ij')
    params_list = np.array([p.flatten() for p in param_mesh]).T

    results = [(params.tolist(), f(*params)) for params in params_list]
    results.sort(key=lambda x: x[0])
    return results

# ==========================================
# Example Usage
# ==========================================

if __name__ == "__main__":
    # Define a test function
    def example_function(x, y):
        return np.sin(x) * np.cos(y)

    # Define parameter ranges
    param_ranges = [(0, np.pi), (0, 2 * np.pi)]

    # Define q_n per parameter
    q_n = [10, 10]  # 10 points for x, 10 points for y

    # Calculate total number of function evaluations allowed
    total_evaluations = np.prod(q_n)
    print(f"Total allowed function evaluations: {total_evaluations}")

    # Example of adaptive sweep
    print("Performing sweeps...")
    results_adaptive = adaptive_sweep(
        example_function,
        param_ranges,
        q_n=q_n,
        refinement_factor=1,  # No refinement
        tolerance=float('inf')  # No refinement
    )

    print("Results:", len(results_adaptive))

    # Example of multiprocessing adaptive sweep
    results_multiprocessing = adaptive_sweep_multiprocessing(
        example_function,
        param_ranges,
        q_n=q_n,
        refinement_factor=1,  # No refinement
        tolerance=float('inf'),  # No refinement
        max_depth=0  # No refinement
    )
    print("Results (Multiprocessing):", len(results_multiprocessing))

    # Example of gradient-based adaptive sampling
    results_gradient = gradient_based_sweep(
        example_function,
        param_ranges,
        q_n=q_n,
        refinement_factor=1,  # No refinement
        tolerance=float('inf')  # No refinement
    )

    print("Results (Gradient):", len(results_gradient))

    # Example of Bayesian optimization sweep
    results_bayesian = bayesian_sweep(
        example_function,
        param_ranges,
        n_calls=total_evaluations,
        n_initial_points=min(10, total_evaluations)
    )
    print("Results (Bayesian):", len(results_bayesian))

    # Example of distributed adaptive sweep
    results_distributed = distributed_adaptive_sweep(
        example_function,
        param_ranges,
        q_n=q_n,
        refinement_factor=1,  # No refinement
        tolerance=float('inf'),  # No refinement
        max_depth=0  # No refinement
    )

    print("Results (Distributed):", len(results_distributed))

    # Example of uncertainty quantification sweep
    results_uncertainty = uncertainty_quantification_sweep(
        example_function,
        param_ranges,
        q_n=q_n,
        n_samples=1  # Only one sample to keep total evaluations equal to grid size
    )

    print("Results (Uncertainty):", len(results_uncertainty))

    # Example of Monte Carlo sweep
    results_monte_carlo = monte_carlo_sweep(
        example_function,
        param_ranges,
        n_samples=total_evaluations
    )
    print("Results (Monte Carlo):", len(results_monte_carlo))

    # Example of Latin Hypercube sweep
    results_latin_hypercube = latin_hypercube_sweep(
        example_function,
        param_ranges,
        n_samples=total_evaluations
    )

    print("Results (Latin Hypercube):", len(results_latin_hypercube))

    # Example of Sobol sequence sweep
    results_sobol_sequence = sobol_sequence_sweep(
        example_function,
        param_ranges,
        n_samples=total_evaluations
    )

    print("Results (Sobol Sequence):", len(results_sobol_sequence))

    # Example of grid sweep
    results_grid = grid_sweep(
        example_function,
        param_ranges,
        q_n=q_n
    )

    print("Results (Grid):", len(results_grid))

    # Print a summary of results
    print("Adaptive Sweep Results:", len(results_adaptive))
    print("Multiprocessing Adaptive Sweep Results:", len(results_multiprocessing))
    print("Gradient-Based Sweep Results:", len(results_gradient))
    print("Bayesian Sweep Results:", len(results_bayesian))
    print("Distributed Adaptive Sweep Results:", len(results_distributed))
    print("Uncertainty Quantification Sweep Results:", len(results_uncertainty))
    print("Monte Carlo Sweep Results:", len(results_monte_carlo))
    print("Latin Hypercube Sweep Results:", len(results_latin_hypercube))
    print("Sobol Sequence Sweep Results:", len(results_sobol_sequence))
    print("Grid Sweep Results:", len(results_grid))


     # Generate a grid for plotting the contour
    x_vals = np.linspace(param_ranges[0][0], param_ranges[0][1], 100)
    y_vals = np.linspace(param_ranges[1][0], param_ranges[1][1], 100)
    X, Y = np.meshgrid(x_vals, y_vals)
    Z = example_function(X, Y)

    # Create a figure
    plt.figure(figsize=(12, 8))

    # Plot the contour
    contour = plt.contourf(X, Y, Z, levels=50, cmap='viridis')
    plt.colorbar(contour)

    # Now, for each method, extract the sample points and plot them
    methods = {
        'Adaptive': results_adaptive,
        'Multiprocessing Adaptive': results_multiprocessing,
        'Gradient-Based': results_gradient,
        'Bayesian': results_bayesian,
        'Distributed Adaptive': results_distributed,
        'Uncertainty Quantification': results_uncertainty,
        'Monte Carlo': results_monte_carlo,
        'Latin Hypercube': results_latin_hypercube,
        'Sobol Sequence': results_sobol_sequence,
        'Grid': results_grid
    }

    markers = ['o', '^', 's', 'p', '*', 'x', '+', 'd', 'v', '<']
    colors = ['red', 'blue', 'green', 'orange', 'purple', 'brown', 'pink', 'gray', 'olive', 'cyan']

    for (method_name, method_results), marker, color in zip(methods.items(), markers, colors):
        xs = []
        ys = []
        for item in method_results:
            params = item[0]
            xs.append(params[0])
            ys.append(params[1])
        plt.scatter(xs, ys, label=method_name, marker=marker, color=color, alpha=0.6)

    plt.xlabel('x')
    plt.ylabel('y')
    plt.title('Comparison of Sampling Methods')
    plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
    plt.tight_layout()
    plt.savefig('sampling_methods_comparison.png')