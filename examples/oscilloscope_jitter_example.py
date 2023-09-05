from scpi_abstraction.instruments.Oscilloscope import Oscilloscope
from scpi_abstraction.InstrumentManager import InstrumentManager

# connect to the oscilloscope
oscilloscope = Oscilloscope("USB0::0x0957::0x1799::MY58100838::INSTR")

# reset oscilloscope
oscilloscope.reset()

print(oscilloscope.id())

# get the voltage of channel 1
print(oscilloscope.get_channel_voltage(1))

# measure the frequency of channel 1
print(oscilloscope.measure_frequency(1))

# rms jitter measurement
print(oscilloscope.perform_rms_jitter_measurement(1, 0.5))

# peak-to-peak jitter measurement
print(oscilloscope.perform_peak_to_peak_jitter_measurement(1, 0.5))

# rise time measurement
print(oscilloscope.perform_rise_time_measurement(1, 0.5))

# fall time measurement
print(oscilloscope.perform_fall_time_measurement(1, 0.5))

# eye diagram measurement