from pytestlab.instruments import AutoInstrument

osc = AutoInstrument.from_config("keysight/DSOX1204G")
awg = AutoInstrument.from_config("keysight/EDU33212A")
psu = AutoInstrument.from_config("keysight/EDU36311A")
dmm = AutoInstrument.from_config("keysight/EDU34450A")

# from pytestlab.config import OscilloscopeConfig, WaveformGeneratorConfig, PowerSupplyConfig, MultimeterConfig

# osc_config = OscilloscopeConfig.from_json_file("../pytestlab/profiles/keysight/DSOX1204G.json")
# awg_config = WaveformGeneratorConfig.from_json_file("../pytestlab/profiles/keysight/EDU33212A.json")
# psu_config = PowerSupplyConfig.from_json_file("../pytestlab/profiles/keysight/EDU36311A.json")
# dmm_config = MultimeterConfig.from_json_file("../pytestlab/profiles/keysight/EDU34450A.json")

# print(osc_config.to_json())
# print(awg_config.to_json())
# print(psu_config.to_json())
# print(dmm_config.to_json())