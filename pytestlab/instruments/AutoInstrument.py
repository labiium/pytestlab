from pytestlab.instruments.Oscilloscope import Oscilloscope, DigitalOscilloscopeWithJitter
from pytestlab.instruments.DigitalMultimeter import DigitalMultimeter
from pytestlab.instruments.WaveformGenerator import WaveformGenerator
from pytestlab.instruments.DigitalPowerSupply import DigitalPowerSupply
from pytestlab.errors import InstrumentConfigurationError

def AutoInstrument(profile):
    """
    Automatically instantiate and return an instrument object based on a given profile.

    Args:
        profile (dict): A dictionary profile containing information about the instrument to be created. 
                            The dictionary should contain a "device_type" key with a string value 
                            specifying the type of the device ("oscilloscope", "digital_multimeter", 
                            "waveform_generator", "digital_power_supply"). 
                            Additional will be required depending on the device type.
                            
    Returns:
        Object: An instance of the corresponding instrument class, initialized based on the profile.

    Raises:
        InstrumentConfigurationError: If the device type is not recognized or missing in the profile.
    """
    match profile["device_type"]:
        case "oscilloscope":
            if profile["jitter_analysis"]:
                return DigitalOscilloscopeWithJitter(profile["visa_resource"], profile)
            else:
                return Oscilloscope(profile["visa_resource"], profile)
        case "digital_multimeter":
            return DigitalMultimeter(profile["visa_resource"], profile)
        case "waveform_generator":
            return WaveformGenerator(profile["visa_resource"], profile)
        case "digital_power_supply":
            return DigitalPowerSupply(profile["visa_resource"], profile)
        case _:
            raise InstrumentConfigurationError()
