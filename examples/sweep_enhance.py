from pytestlab.instruments import AutoInstrument
from pytestlab.experiments import Experiment, Database
import numpy as np
from tqdm import tqdm
import matplotlib.pyplot as plt

# loading the instruments
psu = AutoInstrument.from_config("keysight/EDU36311A")
dmm = AutoInstrument.from_config("keysight/EDU34450A")

V_DD = 2
V_IN = 1
V_B = 3

experiment = Experiment(
    name="adaptive_sweep",
    description="Adaptive sweeping of the PSU voltage and measuring with the DMM."
)

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

# Initial coarse sweep
coarse_points = 10
coarse_data = []
for vb in tqdm(np.linspace(5, 0, coarse_points), desc="Coarse Sweep"):
    coarse_sweep_data = []
    for vin in np.linspace(0, 5, 100):
        psu.set_voltage(V_IN, vin)
        psu.set_voltage(V_B, vb)
        measurement = dmm.measure(int_time="MED")
        coarse_sweep_data.append([vin, vb, measurement.values])
    coarse_data.append(coarse_sweep_data)

coarse_data = np.array(coarse_data)

# Simple adaptive sampling - no recursive refinement
# Identify points of significant change (example using a simple threshold)
threshold = 0.1 # adjust this threshold as needed
# calculate change in voltage
change = np.diff(coarse_data[:,:,2], axis=1)
high_change_indices = np.where(np.abs(change) > threshold)

# Add points in areas of significant change
adaptive_data = []
for vb_index, vb in enumerate(np.linspace(5,0, coarse_points)):
    vin_data = []
    for vin_index, vin in enumerate(np.linspace(0,5,10)):
        if (vb_index, vin_index) in zip(*high_change_indices):
            # Add more points near high change areas
            for i in np.linspace(0, 1, 5): #add 5 points
                new_vin = vin + i * (np.linspace(0, 5, 10)[vin_index+1] - vin)
                psu.set_voltage(V_IN, new_vin)
                psu.set_voltage(V_B, vb)
                measurement = dmm.measure(int_time="MED")
                vin_data.append([new_vin, vb, measurement.values])

        psu.set_voltage(V_IN, vin)
        psu.set_voltage(V_B, vb)
        measurement = dmm.measure(int_time="MED")
        vin_data.append([vin, vb, measurement.values])
    adaptive_data.append(vin_data)



adaptive_data = np.array(adaptive_data)
np.save("adaptive_data_sweep_10.npy", adaptive_data)

psu.output(V_IN, state=False)
psu.output(V_DD, state=False)
psu.output(V_B, state=False)

#Plot Data

plt.figure(figsize=(10, 6))
for vb_index in range(adaptive_data.shape[0]):
    plt.plot(adaptive_data[vb_index,:,0], adaptive_data[vb_index,:,2], label=f"V_B = {np.linspace(5,0, coarse_points)[vb_index]:.2f} V")
plt.xlabel("V_IN (V)")
plt.ylabel("Measured Voltage (V)")
plt.title("Adaptive Voltage Sweep")
plt.legend()
plt.grid(True)
plt.show()