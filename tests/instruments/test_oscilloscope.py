from pytestlab.instruments import AutoInstrument

osc = AutoInstrument.from_config("keysight/DSOX1204G")

print(osc.id())

assert type(osc.id()) == str

print(osc.read_channels(1))

osc.reset()
osc.wave_gen(True)

osc.set_wave_gen_func("SIN")
osc.set_wave_gen_freq(1000)
osc.set_wave_gen_amp(4)
# osc.set_wave_gen_offset(-9)

osc.set_wgen_sin(4, 1, 100)

osc.set_wgen_square(0, 5, 10, 1)
osc.set_wgen_ramp(0, 5, 10, 1)
osc.set_wgen_pulse(0, 5, 10 ,1)
osc.set_wgen_dc(5)
osc.set_wgen_noise(0, 4, 8)


osc.fft_display()

osc.configure_fft(1, 10, 0, span=1000)
print(osc.read_fft_data())

osc.franalysis_sweep(1,2, 10, 100, 2)