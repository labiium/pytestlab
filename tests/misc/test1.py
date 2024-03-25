from pytestlab.instruments import AutoInstrument

osc = AutoInstrument.from_config("keysight/DSOX1204G")

print(osc.id())

# data = osc.read_channels(1,2,3)

# print(data)
from pytestlab.experiments import Experiment

experiment = Experiment("Test experiment", "This is a test experiment")

experiment.add_parameter("frequency", "Hz")


experiment.add_trial(osc.read_channels(1)[1], frequency=1000)
experiment.add_trial(osc.read_channels(1)[1], frequency=1000)
experiment.add_trial(osc.read_channels(1)[1], frequency=1000)
experiment.add_trial(osc.read_channels(1)[1], frequency=1000)

print(experiment)
experiment.list_trials()

from pytestlab.experiments import Database

db = Database("test")

db.store_experiment("codenamd", experiment)