from __future__ import annotations

import numpy as np
from tqdm import tqdm
from typing import Callable, List, Tuple, Any, Dict

# ==========================================
# Helper Functions (Moved to Top Level)
# ==========================================

def f_evaluate(params: Tuple[Any, ...], f: Callable[..., Any]) -> Any:
    return f(*params)

# ==========================================
# Monte Carlo Sweep
# ==========================================

def monte_carlo_sweep(f: Callable[..., Any], param_ranges: List[Tuple[float, float]], n_samples_list: List[int]) -> List[Tuple[List[float], Any]]:
    """
    Perform a Monte Carlo sweep by randomly sampling the parameter space.
    
    Args:
        f (Callable): The function to be evaluated.
        param_ranges (List[Tuple[float, float]]): A list of (min, max) for each parameter.
        n_samples_list (List[int]): Number of random samples for each parameter.
        
    Returns:
        List[Tuple[List[float], Any]]: Parameter combinations and corresponding function outputs.
    """
    if len(param_ranges) != len(n_samples_list):
        raise ValueError("Each parameter range should have a corresponding number of samples in n_samples_list.")
    
    samples: List[Tuple[List[float], Any]] = []
    
    # Sample for each parameter independently according to its specified number of samples
    param_samples_list: List[np.ndarray] = []
    for (min_val, max_val), n_samples in zip(param_ranges, n_samples_list):
        param_samples_list.append(np.random.uniform(min_val, max_val, n_samples))
    
    # Create a Cartesian product of the sampled parameters to form all parameter combinations
    # Ensure param_samples_list is not empty before passing to meshgrid
    if not param_samples_list:
        return [] # Or handle as an error if appropriate

    param_combinations: np.ndarray = np.array(np.meshgrid(*param_samples_list)).T.reshape(-1, len(param_ranges))
    
    # Evaluate the function for each parameter combination
    for params_np in param_combinations:
        params_list_float: List[float] = params_np.tolist()
        result = f(*params_list_float)
        samples.append((params_list_float, result))
    
    # Sort by the function output (assuming output is sortable)
    try:
        samples.sort(key=lambda x: x[1])
    except TypeError:
        # If output is not sortable, skip sorting or sort by params
        samples.sort(key=lambda x: x[0])
    return samples


# ==========================================
# Grid Sweep
# ==========================================

def grid_sweep(f: Callable[..., Any], param_ranges: List[Tuple[float, float]], q_n: Union[int, List[int]]) -> List[Tuple[List[float], Any]]:
    """
    Perform a simple grid sweep over the parameter space.
    Args:
        f (Callable): The function to be evaluated.
        param_ranges (List[Tuple[float, float]]): A list of (min, max) for each parameter.
        q_n (Union[int, List[int]]): Number of points to sample along each parameter.
    Returns:
        List[Tuple[List[float], Any]]: Parameter combinations and corresponding function outputs.
    """
    num_params = len(param_ranges)
    q_n_list: List[int]
    # Ensure q_n is a list of integers, one per parameter
    if isinstance(q_n, int):
        q_n_list = [q_n] * num_params
    elif isinstance(q_n, list) and len(q_n) == num_params and all(isinstance(item, int) for item in q_n):
        q_n_list = q_n
    else:
        raise ValueError("q_n must be an integer or a list of integers with length equal to the number of parameters.")

    grids: List[np.ndarray] = [np.linspace(min_val, max_val, q_n_list[i]) for i, (min_val, max_val) in enumerate(param_ranges)]
    if not grids: # Handle empty param_ranges
        return []

    param_mesh: List[np.ndarray] = np.meshgrid(*grids, indexing='ij')
    params_list_np: np.ndarray = np.array([p.flatten() for p in param_mesh]).T

    results: List[Tuple[List[float], Any]] = []
    for params_np_row in params_list_np:
        params_list_float_row: List[float] = params_np_row.tolist()
        results.append((params_list_float_row, f(*params_list_float_row)))
        
    results.sort(key=lambda x: x[0])
    return results


# ==========================================
# Gradient-Weighted Adaptive Sampling
# ==========================================

def gwass(f: Callable[..., Any], param_ranges: List[Tuple[float, float]], q_n: int, initial_percentage: float = 0.1) -> List[Tuple[List[float], Any]]:
    """
    Gradient-weighted adaptive stochastic sampling for function evaluation.

    Args:
        f (Callable): The function to evaluate.
        param_ranges (List[Tuple[float, float]]): A list of (min, max) for each parameter.
        q_n (int): Total number of evaluations allowed.
        initial_percentage (float): Percentage of q_n to use for initial coarse grid.

    Returns:
        List[Tuple[List[float], Any]]: Parameter combinations and function outputs.
    """
    num_params = len(param_ranges)
    if num_params == 0:
        return [] # No parameters to sweep

    evaluated_points: Dict[Tuple[float, ...], Any] = {}
    total_evaluations = 0

    n_initial = max(int(initial_percentage * q_n), num_params + 1)

    def compute_n_points_per_dim_local(n_init: int, n_params: int) -> int: # Renamed to avoid conflict
        n_points = max(2, int(n_init ** (1 / n_params)))
        while n_points ** n_params > n_init and n_points > 2:
            n_points -= 1
        return n_points

    n_points_per_dim_val = compute_n_points_per_dim_local(n_initial, num_params)
    # total_initial_points = n_points_per_dim_val ** num_params # Unused

    grids_list: List[np.ndarray] = [np.linspace(r[0], r[1], n_points_per_dim_val) for r in param_ranges]
    param_mesh_gwass: List[np.ndarray] = np.meshgrid(*grids_list, indexing='ij') # Renamed
    initial_params_np: np.ndarray = np.array([p.flatten() for p in param_mesh_gwass]).T # Renamed

    for params_row_np in initial_params_np:
        key_tuple: Tuple[float, ...] = tuple(params_row_np)
        if key_tuple not in evaluated_points:
            evaluated_points[key_tuple] = f(*params_row_np)
            total_evaluations += 1

    shape_list: List[int] = [len(g) for g in grids_list] # Renamed
    values_np: np.ndarray = np.array([evaluated_points[tuple(p)] for p in initial_params_np]).reshape(*shape_list) # Renamed
    spacing_list: List[float] = [g[1] - g[0] if len(g) > 1 else 1.0 for g in grids_list] # Renamed, ensure float
    
    gradients_list: Union[np.ndarray, List[np.ndarray]] # Renamed
    if num_params == 1: # np.gradient returns a single array if only one variable
        gradients_list = np.gradient(values_np, spacing_list[0], edge_order=2)
    else: # Returns a list of arrays for multiple variables
        gradients_list = np.gradient(values_np, *spacing_list, edge_order=2)


    grad_magnitude_np: np.ndarray # Renamed
    if num_params == 1:
        grad_magnitude_np = np.abs(gradients_list) # gradients_list is already an ndarray here
    else:
        # Ensure gradients_list is treated as a list of ndarrays for sum
        grad_magnitude_np = np.sqrt(sum([g**2 for g in gradients_list])) # type: ignore

    cell_shape_list: List[int] = [s - 1 for s in shape_list] # Renamed
    if any(s < 0 for s in cell_shape_list): # Check for invalid cell shapes (e.g. if n_points_per_dim_val was 1)
        # This case means no cells can be formed, likely due to too few initial points.
        # Fallback to random sampling for remaining evaluations.
        results_list: List[Tuple[List[float], Any]] = [(list(k), v) for k, v in evaluated_points.items()]
        while len(results_list) < q_n:
            params_rand = [np.random.uniform(r[0], r[1]) for r in param_ranges]
            key_rand = tuple(params_rand)
            if key_rand not in evaluated_points:
                evaluated_points[key_rand] = f(*params_rand)
                results_list.append((params_rand, evaluated_points[key_rand]))
        results_list.sort(key=lambda x: x[0])
        return results_list[:q_n]


    cell_indices_list: List[Tuple[int, ...]] = list(np.ndindex(*cell_shape_list)) # Renamed
    cell_gradients_list: List[float] = [] # Renamed
    for idx_tuple in cell_indices_list: # Renamed
        corner_indices_nd: List[Tuple[int, ...]] = list(np.ndindex(*([2]*num_params))) # Renamed
        corner_gradients_vals: List[float] = [] # Renamed
        for corner_tuple in corner_indices_nd: # Renamed
            corner_idx_tuple: Tuple[int, ...] = tuple(idx_tuple[d] + corner_tuple[d] for d in range(num_params)) # Renamed
            corner_grad_val: float = grad_magnitude_np[corner_idx_tuple] # Renamed
            corner_gradients_vals.append(corner_grad_val)
        cell_grad_val: float = np.mean(corner_gradients_vals) # Renamed
        cell_gradients_list.append(cell_grad_val)

    cell_gradients_np: np.ndarray = np.array(cell_gradients_list) # Renamed
    total_gradient_val: float = np.sum(cell_gradients_np) # Renamed
    
    cell_probabilities_np: np.ndarray # Renamed
    if total_gradient_val == 0 or len(cell_gradients_np) == 0:
        if len(cell_indices_list) > 0: # Check if there are cells to assign probability to
             cell_probabilities_np = np.ones(len(cell_indices_list)) / len(cell_indices_list)
        else: # No cells, no probabilities to assign (e.g. if n_points_per_dim_val was 1)
             cell_probabilities_np = np.array([])
    else:
        cell_probabilities_np = cell_gradients_np / total_gradient_val

    remaining_evaluations = q_n - total_evaluations
    
    allocations_np: np.ndarray # Renamed
    if remaining_evaluations > 0 and len(cell_probabilities_np) > 0:
        allocations_np = np.random.multinomial(remaining_evaluations, cell_probabilities_np)
    else:
        allocations_np = np.array([])


    for alloc_val, idx_tuple_alloc in zip(allocations_np, cell_indices_list): # Renamed
        if alloc_val > 0:
            cell_ranges_list: List[Tuple[float, float]] = [] # Renamed
            for d_idx in range(num_params): # Renamed
                min_val_cell = grids_list[d_idx][idx_tuple_alloc[d_idx]] # Renamed
                max_val_cell = grids_list[d_idx][idx_tuple_alloc[d_idx] + 1] # Renamed
                cell_ranges_list.append((min_val_cell, max_val_cell))
            for _ in range(int(alloc_val)): # Ensure alloc_val is int for range
                params_alloc: List[float] = [np.random.uniform(low, high) for (low, high) in cell_ranges_list] # Renamed
                key_alloc: Tuple[float, ...] = tuple(params_alloc) # Renamed
                if key_alloc not in evaluated_points:
                    evaluated_points[key_alloc] = f(*params_alloc)
                    total_evaluations += 1
                    if total_evaluations >= q_n: break # Stop if q_n reached
            if total_evaluations >= q_n: break


    results_final: List[Tuple[List[float], Any]] = [(list(k), v) for k, v in evaluated_points.items()] # Renamed

    if len(results_final) < q_n:
        # Add more samples randomly if q_n not reached
        pbar = tqdm(total=q_n, initial=len(results_final), desc="GWASS Random Fill")
        while len(results_final) < q_n:
            params_rand_fill = [np.random.uniform(r[0], r[1]) for r in param_ranges] # Renamed
            key_rand_fill = tuple(params_rand_fill) # Renamed
            if key_rand_fill not in evaluated_points:
                evaluated_points[key_rand_fill] = f(*params_rand_fill)
                results_final.append((params_rand_fill, evaluated_points[key_rand_fill]))
                pbar.update(1)
        pbar.close()


    results_final.sort(key=lambda x: x[0])
    return results_final[:q_n] # Ensure exactly q_n results if oversampled