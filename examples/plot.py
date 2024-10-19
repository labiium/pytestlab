import matplotlib.pyplot as plt
import numpy as np

data = np.load("data_sweep.npy")

for i in range(len(data)):
    plt.plot(data[i][:, 0], data[i][:, 2], label=f"V_B = {data[i][0, 1]} V")