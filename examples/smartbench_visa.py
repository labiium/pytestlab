from pytestlab.instruments.PowerSupply import PowerSupply
from pytestlab.instruments.WaveformGenerator import WaveformGenerator
from pytestlab.instruments.Oscilloscope import Oscilloscope
from pytestlab.instruments.Multimeter import Multimeter
from pytestlab.instruments.PowerSupply import PowerSupply
from pytestlab.profiles.keysight.smartbench import oscilloscope_profile, awg_profile, power_supply_profile, multimeter_profile

# loading the instruments and profiles via the pytestlab.profiles module
osc = Oscilloscope(visa_resource="<visa_resource_string>", profile=oscilloscope_profile["DSOX1204G"])
awg = WaveformGenerator(visa_resource="<visa_resource_string>", profile=awg_profile["EDU33212A"])
psu = PowerSupply(visa_resource="<visa_resource_string>", profile=power_supply_profile["EDU36311A"])
dmm = Multimeter(visa_resource="<visa_resource_string>", profile=multimeter_profile["EDU34450A"])

# setting the visa resources
print(osc.id())
print(awg.id())
print(psu.id())
print(dmm.id())

# closing the connections
osc.close()
awg.close()
psu.close()
dmm.close()
