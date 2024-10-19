from pytestlab.instruments import AutoInstrument
from pytestlab.experiments import Experiment, Database
from pytestlab.experiments.sweep import grid_sweep, adaptive_sweep
import numpy as np
from tqdm import tqdm

# loading the instruments
psu = AutoInstrument.from_config("keysight/EDU36311A")
dmm = AutoInstrument.from_config("keysight/EDU34450A")

V_DD = 2
V_IN = 1
V_B = 3

experiment = Experiment(
    name="sweep",
    description="Sweeping the voltage of the PSU and measuring the voltage with the DMM."
)

# setting up the experiment
experiment.add_parameter("v_in", "V", "Voltage IN of the PSU.")
experiment.add_parameter("v_b", "V", "Voltage B of the PSU")

psu.set_voltage(V_DD, 5)
psu.set_current(V_DD, 0.1)

psu.set_voltage(V_IN, 0)
psu.set_current(V_IN, 0.1)

psu.set_voltage(V_B, 3.0)
psu.set_current(V_B, 0.1)

psu.output(V_IN)
psu.output(V_DD)
psu.output(V_B)



more_data = []

for psu_vb_voltage in tqdm(np.linspace(5, 0, 10)):
    data = []
    for psu_vin_voltage in np.linspace(0, 5, 100):
        psu.set_voltage(V_IN, psu_vin_voltage)
        psu.set_voltage(V_B, psu_vb_voltage)
        measurement = dmm.measure(int_time="MED")
        # print(measurement)
        data.append([psu_vin_voltage, psu_vb_voltage, measurement.values])
        # experiment.add_trial(dmm.measure(int_time="FAST"), v_in=psu_vin_voltage, v_b=psu_vb_voltage)
    more_data.append(data)


def measurement(psu_vin_voltage, psu_vb_voltage):
    psu.set_voltage(V_IN, psu_vin_voltage)
    psu.set_voltage(V_B, psu_vb_voltage)
    measurement = dmm.measure(int_time="MED")
    return measurement.values

results_grid = grid_sweep(measurement, [(0, 5), (0, 5)], [10, 10])
results_adaptive = adaptive_sweep(measurement, [(0, 5), (0, 5)])
# saving the results
# db = Database("psu_sweep")

# # A codename is a unique identifier for the experiment
# db.store_experiment("psu_sweep", experiment)

# # A codename is a unique identifier for the experiment
# experiment_data = db.retrieve_experiment("psu_sweep")


# for trial in experiment:
#     print(trial)


psu.output(V_IN, state=False)
psu.output(V_DD, state=False)
psu.output(V_B, state=False)



np_data = np.array(more_data)

np.save("data_sweep.npy", np_data)