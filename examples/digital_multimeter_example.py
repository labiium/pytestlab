from scpi_abstraction.instruments.DigitalMultimeter import DigitalMultimeter
import json
# connect to the digital multimeter
path_to_description = "/examples/instrument_descriptions/digital_multi_meter.json"
description = json.load(open(path_to_description, "r"))

digital_multimeter = DigitalMultimeter(description["visa_resource"], description)

# print the id of the digital multimeter
print(digital_multimeter.id())

# reset the digital multimeter
digital_multimeter.reset()

# set the voltage of channel 1 to 1.5V
digital_multimeter.set_channel_voltage(1, 1.5)

# get the voltage of channel 1
print(digital_multimeter.get_channel_voltage(1))


# measure the frequency of channel 1
print(digital_multimeter.measure_frequency(1))

# close the connection to the digital multimeter
digital_multimeter.close()