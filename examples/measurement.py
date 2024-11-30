from pytestlab.instruments import AutoInstrument

# loading the instrument
psu = AutoInstrument.from_config("keysight/EDU36311A")
dmm = AutoInstrument.from_config("keysight/EDU34450A")

# setting the voltage and current
psu.set_voltage(1, 5)
psu.set_current(1, 0.1)

# turning on the output
# default is always OFF
psu.output(1)


# measuring the voltage
data = dmm.measure(int_time="MED")
print(data)

# To get the raw data float
print(data.values)

# turn off the output
psu.output(1, False)

# closing the connection
psu.close()
dmm.close()