from scpi_abstraction.instruments.Oscilloscope import Oscilloscope, DigitalOscilloscopeWithJitter
from scpi_abstraction.instruments.DigitalMultimeter import DigitalMultimeter
from scpi_abstraction.instruments.WaveformGenerator import WaveformGenerator
from scpi_abstraction.instruments.DigitalPowerSupply import DigitalPowerSupply
from scpi_abstraction.errors import InstrumentConfigurationError

def AutoInstrument(description):
    """
    Automatically instantiate and return an instrument object based on a given description.

    Args:
        description (dict): A dictionary containing information about the instrument to be created. 
                            The dictionary should contain a "device_type" key with a string value 
                            specifying the type of the device ("oscilloscope", "digital_multimeter", 
                            "waveform_generator", "digital_power_supply"). 
                            Additional keys may be required depending on the device type.
                            
    Returns:
        Object: An instance of the corresponding instrument class, initialized based on the description.

    Raises:
        InstrumentConfigurationError: If the device type is not recognized or missing in the description.

    Examples:
        >>> AutoInstrument({"device_type": "oscilloscope", "visa_resource": "USB0::0x1AB1::0x0588::DS1A194234567",
                            "jitter_analysis": True})

        >>> AutoInstrument({"device_type": "digital_multimeter", "visa_resource": "USB0::0x1111::0x2222::1234ABCD"})
    """
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
