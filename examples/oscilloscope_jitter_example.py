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


# measure the jitter of channel 1
print(oscilloscope.perform_rms_jitter_measurement(1, 0.5))