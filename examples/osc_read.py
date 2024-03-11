from pytestlab.instruments import AutoInstrument
from pytestlab.experiments import Database
import pytestlab

pytestlab.instruments.instrument.backend = "labiium"

# loading the instruments
osc = AutoInstrument.from_config("keysight/DSOX1204G")

# channel_readings = osc.read_channels(1)

# data = channel_readings[1]

# db = Database("osc_reading")

# print(data)
# # A codename is a unique identifier for the experiment
# db.store_measurement("osc_reading", data)

# # A codename is a unique identifier for the experiment
# measurement_data = db.retrieve_measurement("osc_reading")

# print(measurement_data)

# osc.close()


data = osc.screenshot()

data.save("screenshot.png")

osc.close()