from pytestlab.instruments import AutoInstrument

osc = AutoInstrument.from_config("keysight/DSOX3054G")

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
