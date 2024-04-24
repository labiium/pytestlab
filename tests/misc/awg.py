from pytestlab.instruments import AutoInstrument

awg = AutoInstrument.from_config("keysight/EDU33212A")


awg.set_waveform(1, "SIN")

awg.set_frequency(1, 20)

awg.set_amplitude(1, 10)



# awg.set_offset(1, -5)