from pytestlab.instruments import AutoInstrument
from pytestlab.experiments import Database
import pytestlab

# loading the instruments
osc = AutoInstrument.from_config("keysight/DSOX1204G")

channel_readings = osc.read_channels(1)