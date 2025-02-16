from pytestlab.instruments import AutoInstrument

dmm = AutoInstrument.from_config("keysight/EDU34450A")

# dmm.configure(mode="VOLT", ac_dc="DC", rang=1, res="MED")

print(dmm.measure(measurement_type="VOLT", mode="DC", rang="750V", int_time="MED"))