from pytestlab.instruments.Oscilloscope import Oscilloscope
from pytestlab.profiles.keysight.smartbench import oscilloscope_profile

visa_resource = "USB0::0x2A8D::0x0396::CN63187275::0::INSTR"

osc = Oscilloscope(visa_resource=visa_resource, profile=oscilloscope_profile["DSOX1204G"], debug_mode=True)

# osc.reset()

# result = osc.measure_voltage_peak_to_peak(1)

# print(result)

# result = osc.measure_rms_voltage(1)

# print(result)

# osc.set_timebase_scale(1e-8)

# osc.wave_gen(True)

# result = osc.get_timebase_scale()

# print(result)
osc.set_acquisition_time(0.001)

values = osc.read_channels([1], points=200)

fft_result = osc.configure_fft(1, 1, 2)

fft_result = osc.read_fft_data()

print(fft_result)
# ### BROKEN
# # result = osc.get_voltage_stream(1, 0.5, 10)

# # print(result)

# osc.set_acquisition_time(0.0000001)


# # setting sampling rate
# osc.set_sample_rate(1)