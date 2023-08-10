from scpi_abstraction.instruments.AutoInstrument import AutoInstrument
import json

path_to_instrument_description = "/examples/instrument_descriptions/digital_multi_meter.json"
description = json.load(open(path_to_instrument_description, "r"))

instrument = AutoInstrument(description)

print(instrument.id())

instrument.close()