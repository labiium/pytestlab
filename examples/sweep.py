from pytestlab.instruments import AutoInstrument
from pytestlab.experiments import Experiment, Database
from pytestlab.experiments.sweep import grid_sweep, adaptive_sweep, monte_carlo_sweep, gradient_based_sweep, adaptive_gradient_sampling, aggressive_adaptive_gradient_sampling, aggro_stochastic
import numpy as np
from tqdm import tqdm

# loading the instruments
psu = AutoInstrument.from_config("keysight/EDU36311A")
dmm = AutoInstrument.from_config("keysight/EDU34450A")

V_DD = 2
V_IN = 1
V_B = 3

# print("Starting experiment")

# experiment = Experiment(
#     name="sweep",
#     description="Sweeping the voltage of the PSU and measuring the voltage with the DMM."
# )

# # setting up the experiment
# experiment.add_parameter("v_in", "V", "Voltage IN of the PSU.")
# experiment.add_parameter("v_b", "V", "Voltage B of the PSU")

psu.set_voltage(V_DD, 5)
psu.set_current(V_DD, 0.1)

psu.set_voltage(V_IN, 0)
psu.set_current(V_IN, 0.1)

psu.set_voltage(V_B, 3.0)
psu.set_current(V_B, 0.1)

psu.output(V_IN)
psu.output(V_DD)
psu.output(V_B)

V_IN_points = 10000
V_B_points = 10


# more_data = []

# for psu_vb_voltage in tqdm(np.linspace(5, 0, 10)):
#     data = []
#     for psu_vin_voltage in np.linspace(0, 5, 10):
#         psu.set_voltage(V_IN, psu_vin_voltage)
#         psu.set_voltage(V_B, psu_vb_voltage)
#         measurement = dmm.measure(int_time="MED")
#         # print(measurement)
#         data.append([psu_vin_voltage, psu_vb_voltage, measurement.values])
#         # experiment.add_trial(dmm.measure(int_time="FAST"), v_in=psu_vin_voltage, v_b=psu_vb_voltage)
#     more_data.append(data)

# np_data = np.array(more_data)
# np.save("naive_sweep_1.npy", np_data)


def measurement(psu_vin_voltage, psu_vb_voltage):
    psu.set_voltage(V_IN, psu_vin_voltage)
    psu.set_voltage(V_B, psu_vb_voltage)
    measurement = dmm.measure(int_time="FAST")
    return measurement.values


def SingleMeasurement(ps_vb_voltage):
    return lambda ps_vin_voltage: measurement(ps_vin_voltage, ps_vb_voltage)

print("Grid Sweep in progress...")
data_grid = []
for psu_vb_voltage in tqdm(np.linspace(5, 0, V_B_points)):
    results_grid = grid_sweep(SingleMeasurement(psu_vb_voltage), [(0, 5)], [V_IN_points])
    results_grid = np.array([[psu_vb_voltage, x[0][0], x[1]] for x in results_grid])
    data_grid.append(results_grid)
data_grid = np.array(data_grid)
np.save(f"data/single/grid_sweep_FAST_{V_IN_points}_{V_B_points}.npy", data_grid)


# print("Adaptive Sweep in progress...")
# data_adaptive = []
# for psu_vb_voltage in np.linspace(5, 0, V_B_points):
#     results_adaptive = adaptive_sweep(SingleMeasurement(psu_vb_voltage), [(0, 5)], [V_IN_points],
#     refinement_factor=1,     # No refinement
#     tolerance=float('inf'),  # No refinement
#     max_refinement_steps=0   # No refinement
#     )
#     results_adaptive = np.array([[psu_vb_voltage, x[0][0], x[1]] for x in results_adaptive])
#     data_adaptive.append(results_adaptive)

# data_adaptive = np.array(data_adaptive)
# np.save(f"data/single/adaptive_sweep_FAST_{V_IN_points}_{V_B_points}.npy", data_adaptive)

# print("Monte Carlo Sweeping...")
# data_monte = []
# for psu_vb_voltage in np.linspace(5, 0, V_B_points):
#     results_monte = monte_carlo_sweep(SingleMeasurement(psu_vb_voltage), [(0, 5)], [V_IN_points])
#     results_monte = np.array([[psu_vb_voltage, x[0][0], x[1]] for x in results_monte])
#     data_monte.append(results_monte)

# data_monte = np.array(data_monte)
# np.save(f"data/single/monte_sweep_FAST_{V_IN_points}_{V_B_points}.npy", data_monte)

# print("Gradient Based Sweep...")
# data_grad = []
# for psu_vb_voltage in np.linspace(5, 0, V_B_points):
#     results_grad = gradient_based_sweep(SingleMeasurement(psu_vb_voltage), [(0, 5)], [V_IN_points])
#     results_grad = np.array([[psu_vb_voltage, x[0][0], x[1]] for x in results_grad])
#     data_grad.append(results_grad)


# print("Saving data...")
# print(data_grad)
# # data_grad = np.array(data_grad)
# np.save(f"data/single/grad_sweep_FAST_{V_IN_points}_{V_B_points}.npy", [data_grad[2]])



# print("Adaptive Gradient Based Sweep...")
# data_grad = []
# for psu_vb_voltage in np.linspace(5, 0, V_B_points):
#     results_grad = adaptive_gradient_sampling(SingleMeasurement(psu_vb_voltage), [(0, 5)], V_IN_points)
#     results_grad = np.array([[psu_vb_voltage, x[0][0], x[1]] for x in results_grad])
#     print(results_grad.shape)
#     data_grad.append(results_grad)


# print("Saving data...")
# np.save(f"data/single/adagrad_sweep_FAST_{V_IN_points}_{V_B_points}.npy", data_grad)

# print("Aggressive Adaptive Gradient Based Sweep...")
# data_grad = []
# for psu_vb_voltage in np.linspace(5, 0, V_B_points):
#     results_grad = aggressive_adaptive_gradient_sampling(SingleMeasurement(psu_vb_voltage), [(0, 5)], V_IN_points)
#     results_grad = np.array([[psu_vb_voltage, x[0][0], x[1]] for x in results_grad])
#     print(results_grad.shape)
#     data_grad.append(results_grad)


# print("Saving data...")
# np.save(f"data/single/aggro_adagrad_sweep_FAST_{V_IN_points}_{V_B_points}.npy", data_grad)

# print("Aggressive Stochastic Based Sweep...")
# data_grad = []
# for psu_vb_voltage in np.linspace(5, 0, V_B_points):
#     results_grad = aggro_stochastic(SingleMeasurement(psu_vb_voltage), [(0, 5)], V_IN_points)
#     results_grad = np.array([[psu_vb_voltage, x[0][0], x[1]] for x in results_grad])
#     print(results_grad.shape)
#     data_grad.append(results_grad)


print("Saving data...")
np.save(f"data/single/ago_stochastic_sweep_FAST_{V_IN_points}_{V_B_points}.npy", data_grad)

psu.output(V_IN, state=False)
psu.output(V_DD, state=False)
psu.output(V_B, state=False)
