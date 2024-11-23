from pytestlab.instruments import AutoInstrument
from pytestlab.experiments import Experiment, Database
from pytestlab.experiments.sweep import grid_sweep, adaptive_sweep, monte_carlo_sweep, gradient_based_sweep
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

V_IN_points = 15
V_B_points = 15


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


def measurement(psu_vb_voltage):
    for v_change in np.linspace(0, 5, 10):
        psu.set_voltage(V_IN, v_change)
        psu.set_voltage(V_B, psu_vb_voltage)
        measurement = dmm.measure(int_time="FAST")
    return measurement.values




print("Grid Sweep in progress...")
results_grid = grid_sweep(measurement, [(0, 5), (0, 5)], [V_IN_points, V_B_points])
results_grid = np.array([[x[0][0], x[0][1],  x[1]] for x in results_grid])
np.save(f"data/grid_sweep_FAST_{V_IN_points}_{V_B_points}.npy", results_grid)


print("Adaptive Sweep in progress...")
results_adaptive = adaptive_sweep(measurement, [(0, 5), (0, 5)], [V_IN_points, V_B_points])
results_adaptive = np.array([[x[0][0], x[0][1], x[1]] for x in results_adaptive])
np.save(f"data/adaptive_sweep_FAST_{V_IN_points}_{V_B_points}.npy", results_adaptive)

print("Monte Carlo Sweeping...")
results_monte = monte_carlo_sweep(measurement, [(0, 5), (0, 5)], [V_IN_points, V_B_points])
results_monte = np.array([[x[0][0], x[0][1], x[1]] for x in results_monte])
np.save(f"data/monte_sweep_FAST_{V_IN_points}_{V_B_points}.npy", results_monte)

print("Gradient Based Sweep...")
results_grad = gradient_based_sweep(measurement, [(0, 5), (0, 5)], [V_IN_points, V_B_points])
results_grad = np.array([[x[0][0], x[0][1], x[1]] for x in results_grad])
np.save(f"data/grad_sweep_FAST_{V_IN_points}_{V_B_points}.npy", results_grad)

psu.output(V_IN, state=False)
psu.output(V_DD, state=False)
psu.output(V_B, state=False)
