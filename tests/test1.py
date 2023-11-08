# from pytestlab.instruments.Oscilloscope import Oscilloscope
# from pytestlab.profiles.keysight.smartbench import oscilloscope_profile

# # Create an instance of the Oscilloscope class

visa_resource = "USB0::0x2A8D::0x0396::CN63197262::0::INSTR"

# osc = Oscilloscope(visa_resource=visa_resource, profile=oscilloscope_profile["DSOX1204G"])

# values = osc.perform_franalysis(1,2, 50, 1000)

# # print(values)

# # print(type(values))

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

from pytestlab.instruments.Oscilloscope import Oscilloscope
from pytestlab.instruments.WaveformGenerator import WaveformGenerator
from pytestlab.profiles.keysight.smartbench import oscilloscope_profile, awg_profile

osc = Oscilloscope(visa_resource=visa_resource, profile=oscilloscope_profile["DSOX1204G"])

awg_resource = "USB0::0x2A8D::0x8D01::CN62490164::0::INSTR"
awg = WaveformGenerator(visa_resource=awg_resource, profile=awg_profile["EDU33212A"])

awg.set_amplitude(1, 3)
awg.set_frequency(1, 3446)
awg.set_offset(1, 0)

## Generate arbitrary waveform
import numpy as np

waves = np.linspace(-1, 1, 1000)
# waves = np.sin(waves)

# awg.set_arbitrary_waveform(1, waves)
awg.set_waveform(1, "RAMP")
# print(osc.id())
# print(awg.id())

# # # You should hear the instruments reset
# osc.reset()
# awg.reset()

awg.output(1, state=True)

# # Remember to close the connection or you can't use the instruments in different programs
# osc.close()
# awg.close()
