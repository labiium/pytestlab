from pytestlab.instruments.Oscilloscope import Oscilloscope
# from pytestlab.instruments import 
from pytestlab.instruments.PowerSupply import PowerSupply
from pytestlab.instruments.WaveformGenerator import WaveformGenerator
from pytestlab.profiles.keysight.smartbench import oscilloscope_profile, power_supply_profile, awg_profile

# # # Create an instance of the Oscilloscope class

# visa_resource = "USB0::0x2A8D::0x0396::CN62277315::0::INSTR"

visa_resource = "USB0::0x2A8D::0x0396::CN63197216::0::INSTR"
osc = Oscilloscope(visa_resource=visa_resource, profile=oscilloscope_profile["DSOX1204G"])


# osc.reset()

# osc.configure_trigger(2, 2)

osc.set_trigger(2, 0.001)

# wave_visa_resource = ""

# awg = WaveformGenerator(visa_resource=wave_visa_resource, profile=awg_profile["EDU33212A"])

# awg.reset()
# awg.output(1, state=True)
# awg.set_amplitude(1, 2)
# awg.set_offset(1, 2)


# awg.o
# # awg.close()
# osc.display_channel([1,2,3,4])
# values = osc.perform_franalysis(1,2, 50, 1000)

# # print(values)

# # print(type(values))
# psu_visa = "USB0::0x2A8D::0x8F01::CN62250003::0::INSTR"
# psu = PowerSupply(visa_resource=psu_visa, profile=power_supply_profile["EDU36311A"])

# # psu.reset()

# psu.set_voltage(2, 1)
# psu.set_current(2, 1)
# psu.output(1, state=True)
# # psu.output([1, 2, 3], state=False)

# psu.display(True)


# psu._send_command("OUTPut ON, (@
# 2)")
# psu._send_command("OUTPut:STATe ON, (@1,2,3)")
# psu.enable_output(2)
# psu.display(False)
# print(psu.id())
# psu.display(False)
# psu.disable_output(2)
# psu.enable_output(3)
# psu = DigitalPowerSupply()

# # fft_data = values[1].perform_fft()

# # print(fft_data)

# fft_dat = osc.read_fft_data()
# 
# fft_data = osc._query(":FFT:DATA?")
# fran_data = osc.perform_franalysis


# data = values[1].perform_fft()

# data.plot()

# osc.fft_display(state=False)

# osc.configure_fft(1)

# osc.read_fft_data()

# from pytestlab.instruments.Oscilloscope import Oscilloscope
# from pytestlab.instruments.WaveformGenerator import WaveformGenerator
# from pytestlab.profiles.keysight.smartbench import oscilloscope_profile, awg_profile

# osc = Oscilloscope(visa_resource=visa_resource, profile=oscilloscope_profile["DSOX1204G"])

# awg_resource = "USB0::0x2A8D::0x8D01::CN62490164::0::INSTR"
# awg = WaveformGenerator(visa_resource=awg_resource, profile=awg_profile["EDU33212A"])

# # awg.set_amplitude(1, 3)
# awg.set_frequency(1, 3446)
# # awg._wait()
# awg.set_offset(1, 10)

# # ## Generate arbitrary waveform
# # import numpy as np

# # waves = np.linspace(-1, 1, 1000)
# # # waves = np.sin(waves)

# # awg.set_arbitrary_waveform(1, waves)
# # awg.set_waveform?
# awg._wait()