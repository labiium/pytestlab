from pytestlab.instruments import AutoInstrument

osc = AutoInstrument.from_config("keysight/MXR404A")

print(osc.id())