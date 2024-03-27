from pytestlab.instruments import AutoInstrument

osc = AutoInstrument.from_config("keysight/DSOX1204G")

data = osc.read_channels(1)

from pytestlab.experiments import Experiment, Database

exp = Experiment("test", "test for databases")


for i in range(100):
    exp.add_trial(data)

print(exp.data)
print(exp.data["Channel 1 (V)"])
db = Database("test")

db.store_experiment("Experiment", exp)

data = db.retrieve_experiment("Experiment")

print(data.data)

import os 

os.remove("test.db")