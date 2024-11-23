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
from tqdm import tqdm

# class Sweep:

#     def __call__(f, param_range, q_n):



# ==========================================
# Helper Functions (Moved to Top Level)
# ==========================================

def f_evaluate(params, f):
    return f(*params)


def aggressive_adaptive_gradient_sampling(f, param_ranges, q_n, grad_threshold_factor=1.5, max_depth=3):
    """
    Aggressively perform adaptive sampling based on gradient magnitude within a parameter space,
    concentrating sampling in regions with the highest rates of change.
    
    Args:
        f (function): The function to evaluate.
        param_ranges (list of tuples): A list of (min, max) for each parameter.
        q_n (int): Total number of evaluations allowed.
        grad_threshold_factor (float): Factor to adjust threshold for identifying high-gradient regions.
        max_depth (int): Maximum recursion depth for refinement.
        
    Returns:
        list: Parameter combinations and function outputs.
    """
    num_params = len(param_ranges)
    initial_points = max(5, int(np.floor(q_n ** (1 / num_params) / 1.5)))  # Denser initial grid
    grids = [np.linspace(r[0], r[1], initial_points) for r in param_ranges]
    param_mesh = np.meshgrid(*grids, indexing='ij')
    initial_params = np.array([p.flatten() for p in param_mesh]).T
    evaluated_points = {}
    total_evaluations = 0

    # Initial coarse evaluation
    for params in initial_params:
        key = tuple(params)
        if key not in evaluated_points and total_evaluations < q_n:
            evaluated_points[key] = f(*params)
            total_evaluations += 1

    #
    # l grid
    shape = [len(g) for g in grids]
    values = np.array([evaluated_points[tuple(p)] for p in initial_params]).reshape(*shape)
    spacing = [g[1] - g[0] if len(g) > 1 else 1 for g in grids]
    gradients = np.gradient(values, *spacing, edge_order=2)
    grad_magnitude = np.sqrt(sum([g**2 for g in gradients])) if num_params > 1 else np.abs(gradients)
    
    # Set threshold based on mean gradient magnitude
    mean_grad = grad_magnitude.mean()
    grad_threshold = mean_grad * grad_threshold_factor

    def recursive_refine(cell_index, ranges, depth):
        nonlocal total_evaluations

        # Stop conditions
        if depth > max_depth or total_evaluations >= q_n:
            return

        # Calculate gradient in this cell
        sub_x_vals = [np.linspace(r[0], r[1], 3) for r in ranges]
        sub_param_mesh = np.meshgrid(*sub_x_vals, indexing='ij')
        sub_params_list = np.array([p.flatten() for p in sub_param_mesh]).T
        sub_values = np.array([f(*params) if tuple(params) not in evaluated_points else evaluated_points[tuple(params)]
                               for params in sub_params_list])
        sub_values = sub_values.reshape([3] * num_params)
        sub_spacing = [(r[1] - r[0]) / 2 for r in ranges]
        sub_gradients = np.gradient(sub_values, *sub_spacing, edge_order=2)
        sub_grad_magnitude = np.sqrt(sum([g**2 for g in sub_gradients])) if num_params > 1 else np.abs(sub_gradients)
        
        # Average gradient within this cell
        cell_grad_magnitude = sub_grad_magnitude.mean()

        # If the cell's gradient exceeds the threshold, subdivide further
        if cell_grad_magnitude > grad_threshold:
            mid_points = [(r[0] + r[1]) / 2 for r in ranges]
            refined_ranges = []
            for i in range(len(ranges)):
                refined_ranges.append([(ranges[i][0], mid_points[i]), (mid_points[i], ranges[i][1])])
            
            # Recurse into each subcell
            for sub_range in np.array(np.meshgrid(*refined_ranges)).T.reshape(-1, num_params, 2):
                recursive_refine(cell_index, sub_range, depth + 1)
        else:
            # Allocate remaining evaluations based on gradient magnitude
            num_samples = min(int((cell_grad_magnitude / mean_grad) * 10), q_n - total_evaluations)
            for _ in range(num_samples):
                sample = [np.random.uniform(low, high) for low, high in ranges]
                key = tuple(sample)
                if key not in evaluated_points:
                    evaluated_points[key] = f(*sample)
                    total_evaluations += 1
                    if total_evaluations >= q_n:
                        break

    # Begin recursive refinement from the initial grid cells
    cell_indices = np.ndindex(*[len(g) - 1 for g in grids])
    for cell_idx in cell_indices:
        if total_evaluations >= q_n:
            break
        cell_ranges = [(grids[d][cell_idx[d]], grids[d][cell_idx[d] + 1]) for d in range(num_params)]
        recursive_refine(cell_idx, cell_ranges, depth=0)

    # Collect results, ensuring exactly `q_n` samples
    results = [(list(key), value) for key, value in evaluated_points.items()]
    if len(results) > q_n:
        results = results[:q_n]  # Trim excess if any
    elif len(results) < q_n:
        while len(results) < q_n:
            results.append(results[-1])  # Duplicate last sample if short

    results.sort(key=lambda x: x[0])
    return results
    
# ==========================================
# Adaptive Sweep Functions
# ==========================================

def adaptive_gradient_sampling(f, param_ranges, q_n):
    """
    Perform adaptive sampling based on gradient magnitude within a parameter space.
    Concentrates sampling in regions with higher function change rates.
    
    Args:
        f (function): The function to evaluate.
        param_ranges (list of tuples): A list of (min, max) for each parameter.
        q_n (int): Total number of evaluations allowed.
        
    Returns:
        list: Parameter combinations and function outputs.
    """
    # Set up initial sampling density and parameters
    num_params = len(param_ranges)
    initial_points = max(3, int(np.floor(q_n ** (1 / num_params) / 1.5)))  # Initial grid density
    grids = [np.linspace(r[0], r[1], initial_points) for r in param_ranges]
    param_mesh = np.meshgrid(*grids, indexing='ij')
    initial_params = np.array([p.flatten() for p in param_mesh]).T
    evaluated_points = {}
    total_evaluations = 0

    # Initial coarse evaluation
    for params in initial_params:
        key = tuple(params)
        if key not in evaluated_points and total_evaluations < q_n:
            evaluated_points[key] = f(*params)
            total_evaluations += 1

    # Calculate gradients
    shape = [len(g) for g in grids]
    values = np.array([evaluated_points[tuple(p)] for p in initial_params]).reshape(*shape)
    spacing = [g[1] - g[0] if len(g) > 1 else 1 for g in grids]
    gradients = np.gradient(values, *spacing, edge_order=2)
    grad_magnitude = np.sqrt(sum([g**2 for g in gradients])) if num_params > 1 else np.abs(gradients)
    
    # Normalize and allocate further samples based on gradient magnitudes
    grad_magnitude = grad_magnitude.flatten()
    remaining_evals = q_n - total_evaluations
    allocation = np.round((grad_magnitude / grad_magnitude.sum()) * remaining_evals).astype(int)

    # Adjust allocation if it exceeds remaining evaluations
    if allocation.sum() > remaining_evals:
        allocation = np.floor((allocation / allocation.sum()) * remaining_evals).astype(int)
    
    # Refine sampling within high-gradient cells
    for i, alloc in enumerate(allocation):
        if total_evaluations >= q_n:
            break
        if alloc > 0:
            index = np.unravel_index(i, shape)
            ranges = [(grids[j][index[j]], grids[j][index[j]+1]) for j in range(num_params)]
            for _ in range(alloc):
                if total_evaluations >= q_n:
                    break
                sample = [np.random.uniform(low, high) for low, high in ranges]
                key = tuple(sample)
                if key not in evaluated_points:
                    evaluated_points[key] = f(*sample)
                    total_evaluations += 1

    # Collect results, ensuring exactly `q_n` samples
    results = [(list(key), value) for key, value in evaluated_points.items()]
    if len(results) > q_n:
        results = results[:q_n]  # Trim excess if any
    elif len(results) < q_n:
        # Add extra points if under the target (unlikely, but for completeness)
        while len(results) < q_n:
            results.append(results[-1])  # Duplicate last sample if short
            
    results.sort(key=lambda x: x[0])
    return results

def adaptive_sweep(f, param_ranges, q_n, refinement_factor=2, tolerance=0.1, max_depth=3):
    """
    Perform an adaptive sweep over the parameter space of a function `f`.
    Args:
        f (function): The function to be evaluated. It should take `n` parameters.
        param_ranges (list of tuples): A list of (min, max) for each parameter.
        q_n (int or list of ints): The number of initial points to sample along each parameter.
        refinement_factor (int): Factor by which to increase the number of points during refinement.
        tolerance (float): Threshold for the function variation to trigger refinement.
        max_depth (int): Maximum depth of recursion for refinement.
    Returns:
        results (list): A list of tuples containing parameter combinations and the corresponding function outputs.
    """
    num_params = len(param_ranges)
    if isinstance(q_n, int):
        q_n = [q_n] * num_params
    elif len(q_n) != num_params:
        raise ValueError("q_n must be an integer or a list with length equal to the number of parameters.")

    evaluated_points = {}

    def recursive_refine(ranges, qn, depth):
        grids = [np.linspace(min_val, max_val, qn[i]) for i, (min_val, max_val) in enumerate(ranges)]
        param_mesh = np.meshgrid(*grids, indexing='ij')
        params_list = np.array([p.flatten() for p in param_mesh]).T

        # Evaluate the function at grid points
        for params in params_list:
            key = tuple(params) if num_params > 1 else (params[0],)
            if key not in evaluated_points:
                evaluated_points[key] = f(*params)

        if depth >= max_depth:
            return

        # For each cell, check if the function variation exceeds the tolerance
        cell_ranges_list = []
        if num_params == 1:
            cell_indices = range(len(grids[0]) - 1)
            for i in cell_indices:
                # Get the corner points of the cell
                idx_list = [i, i + 1]
                corner_params = [grids[0][idx] for idx in idx_list]
                corner_values = [evaluated_points[(p,)] for p in corner_params]
                # Compute function variation within the cell
                variation = max(corner_values) - min(corner_values)
                if variation > tolerance:
                    # Subdivide the cell
                    min_val = grids[0][i]
                    max_val = grids[0][i + 1]
                    new_range = [(min_val, max_val)]
                    new_qn = [refinement_factor + 1]
                    recursive_refine(new_range, new_qn, depth + 1)
        else:
            cell_indices = np.ndindex(*[len(grid) - 1 for grid in grids])
            for cell_idx in cell_indices:
                # Get the corner points of the cell
                corner_indices = list(np.ndindex(*([2] * num_params)))
                corner_params = []
                corner_values = []
                for ci in corner_indices:
                    idx = tuple(cell_idx[d] + ci[d] for d in range(num_params))
                    params = [grids[d][idx[d]] for d in range(num_params)]
                    key = tuple(params)
                    corner_params.append(params)
                    corner_values.append(evaluated_points[key])

                # Compute function variation within the cell
                variation = max(corner_values) - min(corner_values)

                # If variation exceeds tolerance, refine the cell
                if variation > tolerance:
                    # Subdivide the cell
                    new_ranges = []
                    for d in range(num_params):
                        min_val = grids[d][cell_idx[d]]
                        max_val = grids[d][cell_idx[d] + 1]
                        new_ranges.append((min_val, max_val))
                    new_qn = [refinement_factor + 1] * num_params
                    recursive_refine(new_ranges, new_qn, depth + 1)

    recursive_refine(param_ranges, q_n, depth=0)

    # Collect all evaluated points
    results = [(list(key), value) for key, value in evaluated_points.items()]
    results.sort(key=lambda x: x[0])
    return results



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

def gradient_based_sweep(f, param_ranges, q_n):
    """
    Perform a sweep over the parameter space based on gradient changes,
    focusing sampling in regions with high gradient, and ensuring the total
    number of function evaluations is q_n.

    Args:
        f (function): The function to evaluate.
        param_ranges (list of tuples): A list of (min, max) for each parameter.
        q_n (int): Total number of function evaluations allowed.

    Returns:
        results (list): Parameter combinations and corresponding function values.
    """

    num_params = len(param_ranges)
    evaluated_points = {}
    total_evaluations = 0

    q_n = np.array(q_n)
    # Start with an initial coarse grid
    initial_points_per_dim = max(2, int(np.floor(q_n ** (1 / num_params) / 2)))
    grids = [np.linspace(min_val, max_val, initial_points_per_dim) for min_val, max_val in param_ranges]
    param_mesh = np.meshgrid(*grids, indexing='ij')
    initial_params_list = np.array([p.flatten() for p in param_mesh]).T

    # Evaluate the function at initial points
    for params in initial_params_list:
        key = tuple(params)
        if key not in evaluated_points:
            evaluated_points[key] = f(*params)
            total_evaluations += 1

    # Estimate gradients between neighboring points
    shape = [len(g) for g in grids]
    values = np.array([evaluated_points[tuple(p)] for p in initial_params_list]).reshape(*shape)
    spacing = [g[1] - g[0] if len(g) > 1 else 1 for g in grids]
    gradients = np.gradient(values, *spacing, edge_order=2)

    # Compute gradient magnitudes
    if num_params == 1:
        grad_magnitude = np.abs(gradients)
    else:
        grad_magnitude = np.sqrt(sum([g**2 for g in gradients]))

    # Flatten gradient magnitudes and corresponding cell indices
    grad_magnitude_flat = grad_magnitude.flatten()
    cell_indices = list(np.ndindex(*[s - 1 for s in shape]))  # Cells defined by grid points

    # Assign gradient magnitudes to cells
    cell_gradients = {}
    for idx in cell_indices:
        cell_gradients[idx] = grad_magnitude[idx]

    # Compute total gradient
    total_gradient = sum(cell_gradients.values())

    # Allocate remaining evaluations based on gradient magnitudes
    remaining_evaluations = q_n - total_evaluations
    allocations = {}
    for idx in cell_indices:
        if total_gradient > 0:
            alloc = int(np.ceil((cell_gradients[idx] / total_gradient) * remaining_evaluations))
        else:
            alloc = 0
        allocations[idx] = alloc

    # Adjust allocations to not exceed remaining evaluations
    total_allocated = sum(allocations.values())
    if total_allocated > remaining_evaluations:
        scaling_factor = remaining_evaluations / total_allocated
        for idx in allocations:
            allocations[idx] = int(np.floor(allocations[idx] * scaling_factor))

    # Sample additional points in cells based on allocations
    for idx, alloc in allocations.items():
        if alloc > 0:
            # Determine cell boundaries
            cell_ranges = []
            for dim in range(num_params):
                min_val = grids[dim][idx[dim]]
                max_val = grids[dim][idx[dim] + 1]
                cell_ranges.append((min_val, max_val))

            # Sample points within the cell
            for _ in range(alloc):
                params = [np.random.uniform(low, high) for low, high in cell_ranges]
                key = tuple(params)
                if key not in evaluated_points:
                    evaluated_points[key] = f(*params)
                    total_evaluations += 1
                    if total_evaluations >= q_n:
                        break
            if total_evaluations >= q_n:
                break

    # Collect all evaluated points
    results = [(list(key), value) for key, value in evaluated_points.items()]
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

def monte_carlo_sweep(f, param_ranges, n_samples_list):
    """
    Perform a Monte Carlo sweep by randomly sampling the parameter space.
    
    Args:
        f (function): The function to be evaluated.
        param_ranges (list of tuples): A list of (min, max) for each parameter.
        n_samples_list (list of int): Number of random samples for each parameter.
        
    Returns:
        results (list): Parameter combinations and corresponding function outputs.
    """
    if len(param_ranges) != len(n_samples_list):
        raise ValueError("Each parameter range should have a corresponding number of samples in n_samples_list.")
    
    samples = []
    
    # Sample for each parameter independently according to its specified number of samples
    param_samples = []
    for (min_val, max_val), n_samples in zip(param_ranges, n_samples_list):
        param_samples.append(np.random.uniform(min_val, max_val, n_samples))
    
    # Create a Cartesian product of the sampled parameters to form all parameter combinations
    param_combinations = np.array(np.meshgrid(*param_samples)).T.reshape(-1, len(param_ranges))
    
    # Evaluate the function for each parameter combination
    for params in param_combinations:
        result = f(*params)
        samples.append((params.tolist(), result))
    
    # Sort by the function output
    samples.sort(key=lambda x: x[1])
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

    results = [(params.tolist(), f(*params)) for params in tqdm(params_list)]
    results.sort(key=lambda x: x[0])
    return results

def coarse_adaptive_sweep(f, param_range, q_n):


    num_params = len(param_ranges)
    if isinstance(q_n, int):
        q_n = [q_n] * num_params
    elif len(q_n) != num_params:
        raise ValueError("q_n must be an integer or a list with length equal to the number of parameters.")

    coarse_grid = [np.linspace(min_val, max_val, q_n[i]) for i, (min_val, max_val) in enumerate(param_ranges)]

def aggro_stochastic(f, param_ranges, q_n, initial_percentage=0.1):
    """
    Aggressive stochastic sampling focused on regions with high gradients.

    Args:
        f (function): The function to evaluate.
        param_ranges (list of tuples): A list of (min, max) for each parameter.
        q_n (int): Total number of evaluations allowed.
        initial_percentage (float): Percentage of q_n to use for initial coarse grid.

    Returns:
        list: Parameter combinations and function outputs.
    """
    num_params = len(param_ranges)
    evaluated_points = {}
    total_evaluations = 0

    # Step 1: Compute initial number of evaluations
    n_initial = max(int(initial_percentage * q_n), num_params + 1)  # Ensure at least one point per dimension

    # Step 2: Compute number of grid points per dimension
    def compute_n_points_per_dim(n_initial, num_params):
        n_points_per_dim = max(2, int(n_initial ** (1 / num_params)))
        while n_points_per_dim ** num_params > n_initial and n_points_per_dim > 2:
            n_points_per_dim -= 1
        return n_points_per_dim

    n_points_per_dim = compute_n_points_per_dim(n_initial, num_params)
    total_initial_points = n_points_per_dim ** num_params

    # Create grids
    grids = [np.linspace(r[0], r[1], n_points_per_dim) for r in param_ranges]
    param_mesh = np.meshgrid(*grids, indexing='ij')
    initial_params = np.array([p.flatten() for p in param_mesh]).T

    # Evaluate function at grid points
    for params in initial_params:
        key = tuple(params)
        if key not in evaluated_points:
            evaluated_points[key] = f(*params)
            total_evaluations += 1

    # Compute gradients
    shape = [len(g) for g in grids]
    values = np.array([evaluated_points[tuple(p)] for p in initial_params]).reshape(*shape)
    spacing = [g[1] - g[0] if len(g) > 1 else 1 for g in grids]
    gradients = np.gradient(values, *spacing, edge_order=2)

    # Compute gradient magnitudes at grid points
    if num_params == 1:
        grad_magnitude = np.abs(gradients)
    else:
        grad_magnitude = np.sqrt(sum([g**2 for g in gradients]))

    # Assign gradient magnitudes to cells
    # Cells are defined between grid points, so for each cell, we can take average of gradients at its corners

    # For each cell, compute average gradient magnitude
    cell_shape = [s - 1 for s in shape]
    cell_indices = list(np.ndindex(*cell_shape))
    cell_gradients = []
    for idx in cell_indices:
        # Get the gradient magnitudes at the corners of the cell
        corner_indices = list(np.ndindex(*([2]*num_params)))
        corner_gradients = []
        for corner in corner_indices:
            corner_idx = tuple(idx[d] + corner[d] for d in range(num_params))
            corner_grad = grad_magnitude[corner_idx]
            corner_gradients.append(corner_grad)
        # Average gradient magnitude in the cell
        cell_grad = np.mean(corner_gradients)
        cell_gradients.append(cell_grad)

    # Normalize gradient magnitudes to get probabilities
    cell_gradients = np.array(cell_gradients)
    total_gradient = np.sum(cell_gradients)
    if total_gradient == 0:
        # If all gradients are zero, assign equal probability to all cells
        cell_probabilities = np.ones(len(cell_gradients)) / len(cell_gradients)
    else:
        cell_probabilities = cell_gradients / total_gradient

    # Remaining evaluations
    remaining_evaluations = q_n - total_evaluations

    # Allocate samples to cells according to probabilities
    allocations = np.random.multinomial(remaining_evaluations, cell_probabilities)

    # For each cell, sample the allocated number of points within the cell
    for alloc, idx in zip(allocations, cell_indices):
        if alloc > 0:
            # Get cell ranges
            cell_ranges = []
            for d in range(num_params):
                min_val = grids[d][idx[d]]
                max_val = grids[d][idx[d] + 1]
                cell_ranges.append((min_val, max_val))
            # Sample points within the cell
            for _ in range(alloc):
                params = [np.random.uniform(low, high) for (low, high) in cell_ranges]
                key = tuple(params)
                if key not in evaluated_points:
                    evaluated_points[key] = f(*params)
                    total_evaluations += 1

    # Collect results
    results = [(list(key), value) for key, value in evaluated_points.items()]

    # If total evaluations exceed q_n due to rounding errors, trim the results
    if len(results) > q_n:
        results = results[:q_n]
    elif len(results) < q_n:
        # Add more samples randomly if needed
        while len(results) < q_n:
            # Sample random point in parameter space
            params = [np.random.uniform(r[0], r[1]) for r in param_ranges]
            key = tuple(params)
            if key not in evaluated_points:
                evaluated_points[key] = f(*params)
                results.append((list(key), evaluated_points[key]))
                total_evaluations +=1

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