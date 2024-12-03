from pytestlab.instruments import AutoInstrument
from pytestlab.experiments.sweep import grid_sweep
import numpy as np
from tqdm import tqdm

# loading the instruments
psu = AutoInstrument.from_config("keysight/EDU36311A")
dmm = AutoInstrument.from_config("keysight/EDU34450A")

V_DD = 2
V_IN = 1
V_B = 3


psu.set_voltage(V_DD, 5)
psu.set_current(V_DD, 0.1)

psu.set_voltage(V_IN, 0)
psu.set_current(V_IN, 0.1)

psu.set_voltage(V_B, 3.0)
psu.set_current(V_B, 0.1)

psu.output(V_IN)
psu.output(V_DD)
psu.output(V_B)

V_IN_points = 100
V_B_points = 10

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
np.save(f"data/grid_sweep_FAST_{V_IN_points}_{V_B_points}.npy", data_grid)# np.save(f"data/single/grad_sweep_FAST_{V_IN_points}_{V_B_points}.npy", [data_grad[2]])

psu.output([V_IN, V_DD, V_B], state=False)