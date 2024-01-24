from pytestlab.instruments import AutoInstrument

# loading the instruments
osc = AutoInstrument.from_config("keysight/DSOX1204G")
awg = AutoInstrument.from_config("keysight/EDU33212A")
psu = AutoInstrument.from_config("keysight/EDU36311A")
dmm = AutoInstrument.from_config("keysight/EDU34450A")

# print(osc._query("*IDN?"))


psu.set_voltage(2, 5)
psu.set_current(2, 0.05)

psu.set_voltage(1, 1.8)
psu.set_current(1, 0.05)

# psu.set_voltage(3, 3.0)
psu.set_current(3, 0.05)
psu.output(3)


### DM
# for i in range(10):
#     psu.set_voltage(1 + i/10)
#     sleep


import numpy as np

end = 5
start = 0
steps = 0.1
total = (end - start) / steps
data = np.zeros(int(total))
counter = 0
i = 0
while i <= end:
    psu.set_voltage(3, i)
    data[counter] = float(dmm._query("MEAS:VOLT:DC? AUTO,FAST"))
    i += steps
    counter += 1

# print(data)

import matplotlib.pyplot as plt

x = np.linspace(0, 5, total + 1)

plt.plot(x, data)