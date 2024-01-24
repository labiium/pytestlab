from pytestlab.instruments.DigitalMultimeter import DigitalMultimeter

dmm = AutoInstrument.from_config("keysight/EDU34450A")

# print the id of the digital multimeter
print(dmm.id())

# reset the digital multimeter
dmm.reset()

# set the voltage of channel 1 to 1.5V
dmm.set_channel_voltage(1, 1.5)

# get the voltage of channel 1
print(dmm.get_channel_voltage(1))

# measure the frequency of channel 1
print(dmm.measure_frequency(1))

# close the connection to the digital multimeter
dmm.close()