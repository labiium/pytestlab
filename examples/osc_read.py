from pytestlab.instruments import AutoInstrument

# loading the instruments
osc = AutoInstrument.from_config("keysight/DSOX1204G")

data = osc.read_channel(1)

osc.close()

