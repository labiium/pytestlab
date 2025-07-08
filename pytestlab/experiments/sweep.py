from __future__ import annotations

# --- DUMMY Sweep class for mkdocstrings compatibility ---
class Sweep:
    """
    Dummy Sweep class for documentation compatibility.
    This is not used in runtime code, but allows mkdocstrings to resolve
    'pytestlab.experiments.Sweep' for API docs.
    """
    pass


import numpy as np
import functools
from tqdm import tqdm
from typing import Callable, List, Tuple, Any, Dict, Union, TypeVar, cast, Optional

# Type variables for better typing
T = TypeVar('T')
R = TypeVar('R')

# ==========================================
# Helper Functions (Moved to Top Level)
# ==========================================

def f_evaluate(params: Tuple[Any, ...], f: Callable[..., Any]) -> Any:
    return f(*params)

class ParameterSpace:
    """
    Represents a parameter space for sweep operations.

    This class helps define and manage parameter spaces for various sweep strategies,
    including parameter ranges, constraints, and integration with MeasurementSession.
    """

    def __init__(self,
                 ranges: Union[List[Tuple[float, float]], str, Dict[str, Tuple[float, float]]] = "auto",
                 names: Optional[List[str]] = None,
                 constraint: Optional[Callable[[Dict[str, float]], bool]] = None):
        """
        Initialize a parameter space.

        Args:
            ranges: Parameter ranges in one of these formats:
                - List of (min, max) tuples: [(min1, max1), (min2, max2), ...]
                - Dict of {name: (min, max)}: {"x": (0, 10), "y": (-5, 5), ...}
                - "auto" to extract from MeasurementSession
            names: Parameter names (required if ranges is a list of tuples)
            constraint: Optional function that takes a dict of parameter values
                        and returns True if the combination is valid
        """
        self.ranges = ranges
        self.names = names or []
        self.constraint = constraint
        self._session = None

        # Validate ranges and names
        if isinstance(ranges, list) and names and len(ranges) != len(names):
            raise ValueError("Number of ranges must match number of parameter names")

        # Convert dict to list format if provided as dict
        if isinstance(ranges, dict):
            self.names = list(ranges.keys())
            self.ranges = [ranges[name] for name in self.names]

    @classmethod
    def from_session(cls, session, constraint=None):
        """
        Create a ParameterSpace from a MeasurementSession.

        Args:
            session: A MeasurementSession with defined parameters
            constraint: Optional constraint function

        Returns:
            ParameterSpace: A configured parameter space
        """
        space = cls("auto", constraint=constraint)
        space._session = session

        # Extract parameter information
        param_names = []
        param_ranges = []

        for name, param in session._parameters.items():
            param_names.append(name)
            values = param.values

            # Calculate range from values
            min_val = min(values)
            max_val = max(values)
            param_ranges.append((min_val, max_val))

        space.names = param_names
        space.ranges = param_ranges

        return space

    def get_parameters(self):
        """
        Get parameter information.

        Returns:
            tuple: (names, ranges) where:
                - names is a list of parameter names
                - ranges is a list of (min, max) tuples
        """
        # If auto, extract from session
        if self.ranges == "auto":
            if not self._session:
                raise ValueError("'auto' ranges require a MeasurementSession")
            return ParameterSpace.from_session(self._session, self.constraint).get_parameters()

        return self.names, self.ranges

    def is_valid(self, param_values: Union[List[float], Dict[str, float]]) -> bool:
        """
        Check if a parameter combination is valid according to the constraint.

        Args:
            param_values: Parameter values as a list or dict

        Returns:
            bool: True if valid, False otherwise
        """
        if not self.constraint:
            return True

        # Convert list to dict if needed
        if isinstance(param_values, list):
            param_dict = dict(zip(self.names, param_values))
        else:
            param_dict = param_values

        return self.constraint(param_dict)

    def wrap_function(self, func: Callable):
        """
        Wrap a function to handle parameter passing and session integration.

        Args:
            func: The measurement function to wrap

        Returns:
            Callable: A wrapped function that handles parameters appropriately
        """
        # Get parameter information
        names, _ = self.get_parameters()

        # Define wrapper function for session usage
        def wrapped_func(*params):
            # Convert positional params to dict
            param_dict = dict(zip(names, params))

            # Apply constraint if any
            if self.constraint and not self.constraint(param_dict):
                # Return a default value for invalid combinations
                return float('nan')

            # Call the original function with named parameters
            return func(**param_dict)

        return wrapped_func

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


# ==========================================
# Rename existing implementation functions
# ==========================================
grid_sweep_impl = grid_sweep
monte_carlo_sweep_impl = monte_carlo_sweep
gwass_impl = gwass


# ==========================================
# New decorator-based API
# ==========================================

def grid_sweep(param_space=None, points=10):
    """
    Apply a grid sweep to a measurement function.

    Args:
        param_space: Parameter space definition, one of:
            - ParameterSpace object
            - List of (min, max) tuples
            - Dict of {name: (min, max)}
            - "auto" to extract from MeasurementSession
        points: Points per dimension, either:
            - Single integer (same for all dimensions)
            - List of integers (one per dimension)

    Returns:
        Callable: A decorator that applies a grid sweep

    Example:
        @grid_sweep({"voltage": (0, 10), "current": (0, 1)}, 20)
        def measure(voltage, current):
            # Measurement code
            return result

        # Or with auto parameter extraction from session
        @session.acquire
        @grid_sweep(points=15)
        async def measure(voltage, current, instrument):
            # Measurement code
            return result

        # With constraint
        def valid_region(params):
            return params["voltage"] > 2 * params["current"]

        @grid_sweep(
            ParameterSpace({"voltage": (0, 10), "current": (0, 1)}, constraint=valid_region),
            points=15
        )
        def measure(voltage, current):
            # Measurement code
            return result
    """
    # Handle different param_space types
    if param_space is None:
        param_space = "auto"

    if not isinstance(param_space, ParameterSpace):
        param_space = ParameterSpace(param_space)

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Handle session as first argument
            if args and hasattr(args[0], '_parameters') and hasattr(args[0], 'acquire'):
                session = args[0]
                local_space = ParameterSpace.from_session(session, param_space.constraint)

                # Create measurement function that closes over the original func
                def measure_func(**params):
                    return func(**params, **kwargs)

                # Get parameters and run grid sweep
                names, ranges = local_space.get_parameters()
                wrapped_func = local_space.wrap_function(measure_func)

                # Run the original grid_sweep function
                results = grid_sweep_impl(wrapped_func, ranges, points)

                # Format results if needed
                return results
            else:
                # Standard usage without session
                if param_space.ranges == "auto":
                    raise ValueError("'auto' parameter space requires a MeasurementSession")

                # Get parameters and run grid sweep
                names, ranges = param_space.get_parameters()
                wrapped_func = param_space.wrap_function(func)

                # Run the original grid_sweep function
                return grid_sweep_impl(wrapped_func, ranges, points)
        return wrapper
    return decorator


def monte_carlo_sweep(param_space=None, samples=50):
    """
    Apply a Monte Carlo sweep to a measurement function.

    Args:
        param_space: Parameter space definition, one of:
            - ParameterSpace object
            - List of (min, max) tuples
            - Dict of {name: (min, max)}
            - "auto" to extract from MeasurementSession
        samples: Number of samples, either:
            - Single integer (total samples)
            - List of integers (samples per dimension)

    Returns:
        Callable: A decorator that applies a Monte Carlo sweep

    Example:
        @monte_carlo_sweep({"voltage": (0, 10), "current": (0, 1)}, 100)
        def measure(voltage, current):
            # Measurement code
            return result

        # With constraint function
        def valid_region(params):
            return params["voltage"] > 0.5 and params["current"] < 0.8

        @monte_carlo_sweep(
            ParameterSpace({"voltage": (0, 10), "current": (0, 1)}, constraint=valid_region),
            samples=200
        )
        def measure(voltage, current):
            # Measurement code
            return result
    """
    # Handle different param_space types
    if param_space is None:
        param_space = "auto"

    if not isinstance(param_space, ParameterSpace):
        param_space = ParameterSpace(param_space)

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Handle session as first argument
            if args and hasattr(args[0], '_parameters') and hasattr(args[0], 'acquire'):
                session = args[0]
                local_space = ParameterSpace.from_session(session, param_space.constraint)

                # Create measurement function that closes over the original func
                def measure_func(**params):
                    return func(**params, **kwargs)

                # Get parameters and run Monte Carlo sweep
                names, ranges = local_space.get_parameters()
                wrapped_func = local_space.wrap_function(measure_func)

                # Convert samples to per-dimension if needed
                samples_list = samples
                if isinstance(samples, int):
                    # Equal distribution among parameters
                    samples_list = [int(samples**(1/len(ranges)))] * len(ranges)

                # Run the original Monte Carlo sweep function
                return monte_carlo_sweep_impl(wrapped_func, ranges, samples_list)
            else:
                # Standard usage without session
                if param_space.ranges == "auto":
                    raise ValueError("'auto' parameter space requires a MeasurementSession")

                # Get parameters and run Monte Carlo sweep
                names, ranges = param_space.get_parameters()
                wrapped_func = param_space.wrap_function(func)

                # Convert samples to per-dimension if needed
                samples_list = samples
                if isinstance(samples, int):
                    # Equal distribution among parameters
                    samples_list = [int(samples**(1/len(ranges)))] * len(ranges)

                return monte_carlo_sweep_impl(wrapped_func, ranges, samples_list)
        return wrapper
    return decorator


def gwass(param_space=None, budget=100, initial_percentage=0.1):
    """
    Apply gradient-weighted adaptive stochastic sampling to a measurement function.

    Args:
        param_space: Parameter space definition, one of:
            - ParameterSpace object
            - List of (min, max) tuples
            - Dict of {name: (min, max)}
            - "auto" to extract from MeasurementSession
        budget: Total number of function evaluations allowed
        initial_percentage: Percentage of budget to use for initial grid

    Returns:
        Callable: A decorator that applies GWASS

    Example:
        @gwass({"voltage": (0, 10), "current": (0, 1)}, budget=200)
        def measure(voltage, current):
            # Measurement code
            return result

        # Or with constraint
        def valid_region(params):
            # Only accept points where voltage > 2*current
            return params["voltage"] > 2 * params["current"]

        @gwass(
            ParameterSpace({"voltage": (0, 10), "current": (0, 1)}, constraint=valid_region),
            budget=150
        )
        def measure(voltage, current):
            # Measurement code
            return result
    """
    # Handle different param_space types
    if param_space is None:
        param_space = "auto"

    if not isinstance(param_space, ParameterSpace):
        param_space = ParameterSpace(param_space)

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Handle session as first argument
            if args and hasattr(args[0], '_parameters') and hasattr(args[0], 'acquire'):
                session = args[0]
                local_space = ParameterSpace.from_session(session, param_space.constraint)

                # Create measurement function that closes over the original func
                def measure_func(**params):
                    return func(**params, **kwargs)

                # Get parameters and run GWASS
                names, ranges = local_space.get_parameters()
                wrapped_func = local_space.wrap_function(measure_func)

                # Run the original GWASS function
                return gwass_impl(wrapped_func, ranges, budget, initial_percentage)
            else:
                # Standard usage without session
                if param_space.ranges == "auto":
                    raise ValueError("'auto' parameter space requires a MeasurementSession")

                # Get parameters and run GWASS
                names, ranges = param_space.get_parameters()
                wrapped_func = param_space.wrap_function(func)

                return gwass_impl(wrapped_func, ranges, budget, initial_percentage)
        return wrapper
    return decorator
