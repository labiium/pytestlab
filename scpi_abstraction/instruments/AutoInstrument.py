from scpi_abstraction.instruments.Oscilloscope import Oscilloscope, DigitalOscilloscopeWithJitter
from scpi_abstraction.instruments.DigitalMultimeter import DigitalMultimeter
from scpi_abstraction.instruments.WaveformGenerator import WaveformGenerator
from scpi_abstraction.instruments.DigitalPowerSupply import DigitalPowerSupply
from scpi_abstraction.errors import InstrumentConfigurationError

def AutoInstrument(description):
    match description["device_type"]:
        case "oscilloscope":
            if description["jitter_analysis"]:
                return DigitalOscilloscopeWithJitter(description["visa_resource"], description)
            else:
                return Oscilloscope(description["visa_resource"], description)
        case "digital_multimeter":
            return DigitalMultimeter(description["visa_resource"], description)
        case "waveform_generator":
            return WaveformGenerator(description["visa_resource"], description)
        case "digital_power_supply":
            return DigitalPowerSupply(description["visa_resource"], description)
        case _:
            raise InstrumentConfigurationError()