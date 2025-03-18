from pytestlab.instruments import AutoInstrument

psu = AutoInstrument.from_config("keysight/EDU36311A")

print(psu.id())
print(psu.get_configuration())

psu.set_voltage(3, 3.3)