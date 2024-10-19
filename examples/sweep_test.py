import numpy as np
import time
from multiprocessing import Pool
from functools import partial

# Original adaptive sweep function (unchanged)
def adaptive_sweep(f, param_ranges, q_n, refinement_factor=2, tolerance=0.1):
    # ... (same as your original code)
    pass  # Keep the original implementation

# Moved f_evaluate to the top level and modified it
def f_evaluate(params, f):
    return f(*params)

# Multiprocessing version of adaptive sweep (fixed)
def adaptive_sweep_multiprocessing(f, param_ranges, q_n, refinement_factor=2, tolerance=0.1, max_depth=2):
    num_params = len(param_ranges)

    def recursive_refine(ranges, qn, depth, f):
        coarse_grids = [np.linspace(min_val, max_val, qn) for min_val, max_val in ranges]
        param_mesh = np.meshgrid(*coarse_grids, indexing='ij')
        grid_shape = param_mesh[0].shape
        params_list = np.array([p.ravel() for p in param_mesh]).T

        with Pool() as pool:
            results_values = pool.map(partial(f_evaluate, f=f), params_list)

        results_array = np.array(results_values).reshape(grid_shape)
        gradients = np.gradient(results_array, *[grid[1]-grid[0] for grid in coarse_grids], edge_order=2)
        grad_magnitude = np.sqrt(np.sum(np.array(gradients)**2, axis=0))
        high_change_mask = grad_magnitude > tolerance

        if depth >= max_depth or not np.any(high_change_mask):
            return list(zip(params_list.tolist(), results_values))

        refined_results = []
        indices = np.argwhere(high_change_mask)
        evaluated_points = set()

        for idx in indices:
            sub_ranges = []
            for i in range(num_params):
                grid = coarse_grids[i]
                idx_val = idx[i]
                min_idx = max(idx_val - 1, 0)
                max_idx = min(idx_val + 1, grid.size - 1)
                min_val = grid[min_idx]
                max_val = grid[max_idx]
                sub_ranges.append((min_val, max_val))

            range_key = tuple(sub_ranges)
            if range_key in evaluated_points:
                continue
            evaluated_points.add(range_key)
            sub_results = recursive_refine(sub_ranges, int(qn * refinement_factor), depth + 1, f)
            refined_results.extend(sub_results)

        low_change_indices = np.argwhere(~high_change_mask)
        for idx in low_change_indices:
            idx_tuple = tuple(idx)
            params = [param_mesh[i][idx_tuple] for i in range(num_params)]
            result_value = results_array[idx_tuple]
            refined_results.append((params, result_value))

        return refined_results

    final_results = recursive_refine(param_ranges, q_n, depth=0, f=f)
    return final_results

# Test function (example)
def example_function(x, y):
    return np.sin(x) * np.cos(y)

# Define parameter ranges
param_ranges = [(0, np.pi), (0, 2 * np.pi)]

# Compare times
if __name__ == "__main__":
    # Measure time for original method
    start_time = time.time()
    results_original = adaptive_sweep(example_function, param_ranges, q_n=10, refinement_factor=3, tolerance=0.2)
    time_original = time.time() - start_time

    # Measure time for multiprocessing method
    start_time_multiprocessing = time.time()
    results_multiprocessing = adaptive_sweep_multiprocessing(
        example_function, param_ranges, q_n=10, refinement_factor=3, tolerance=0.2
    )
    time_multiprocessing = time.time() - start_time_multiprocessing

    # Print the results
    print(f"Original Method Time: {time_original:.4f} seconds")
    print(f"Multiprocessing Method Time: {time_multiprocessing:.4f} seconds")
