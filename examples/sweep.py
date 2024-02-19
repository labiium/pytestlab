from pytestlab.instruments import AutoInstrument
from pytestlab.experiments import Experiment, Database
import numpy as np

# loading the instruments
psu = AutoInstrument.from_config("keysight/EDU36311A")
dmm = AutoInstrument.from_config("keysight/EDU34450A")

experiment = Experiment(
    name="sweep",
    description="Sweeping the voltage of the PSU and measuring the voltage with the DMM."
)

# setting up the experiment
experiment.add_parameter("psu_voltage", "V", "Voltage of the PSU.")


psu.set_voltage(2, 5)
psu.set_current(2, 0.05)

psu.set_voltage(1, 1.8)
psu.set_current(1, 0.05)

# psu.set_voltage(3, 3.0)
psu.set_current(3, 0.05)
psu.output(3)


for psu_voltage in np.linspace(0, 5, 100):
    psu.set_voltage(3, psu_voltage)
    # DMM measure command is a blocking command
    experiment.add_trial(dmm.measure(int_time="Fast"), psu_voltage=psu_voltage)


# saving the results
db = Database("psu_sweep")

# A codename is a unique identifier for the experiment
db.store_experiment("psu_sweep", experiment)

# A codename is a unique identifier for the experiment
experiment_data = db.retrieve_experiment("psu_sweep")


for trial in experiment:
    print(trial)