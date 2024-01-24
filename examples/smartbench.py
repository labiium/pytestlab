from pytestlab.instruments import AutoInstrument

# loading the instruments
osc = AutoInstrument.from_config("keysight/DSOX1204G")
awg = AutoInstrument.from_config("keysight/EDU33212A")
psu = AutoInstrument.from_config("keysight/EDU36311A")
dmm = AutoInstrument.from_config("keysight/EDU34450A")

# printing IDN of instruments
print(osc.id())
print(awg.id())
print(psu.id())
print(dmm.id())

# closing the connection
osc.close()
awg.close()
psu.close()
dmm.close()