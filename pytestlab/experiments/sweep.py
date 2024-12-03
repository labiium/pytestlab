import numpy as np
from tqdm import tqdm

# ==========================================
# Helper Functions (Moved to Top Level)
# ==========================================

def f_evaluate(params, f):
    return f(*params)

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
# Grid Sweep
# ==========================================

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
# Gradient-Weighted Adaptive Sampling
# ==========================================

def gwass(f, param_ranges, q_n, initial_percentage=0.1):
    """
    Gradient-weighted adaptive stochastic sampling for function evaluation.

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