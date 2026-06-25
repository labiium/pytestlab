from pytestlab.instruments.DCActiveLoad import DCActiveLoad
from pytestlab.instruments.Multimeter import Multimeter
from pytestlab.instruments.Oscilloscope import Oscilloscope
from pytestlab.instruments.PowerMeter import PowerMeter
from pytestlab.instruments.PowerSupply import PowerSupply
from pytestlab.instruments.SpectrumAnalyser import SpectrumAnalyser
from pytestlab.instruments.VectorNetworkAnalyser import VectorNetworkAnalyser
from pytestlab.instruments.VirtualInstrument import VirtualInstrument
from pytestlab.instruments.WaveformGenerator import WaveformGenerator

SUPPORTED_CLASSES = (
    Oscilloscope,
    WaveformGenerator,
    PowerSupply,
    Multimeter,
    DCActiveLoad,
    PowerMeter,
    SpectrumAnalyser,
    VectorNetworkAnalyser,
    VirtualInstrument,
)


def test_every_supported_instrument_class_declares_operation_contract():
    missing = [cls.__name__ for cls in SUPPORTED_CLASSES if not cls.operation_descriptors()]
    assert not missing


def test_operation_ids_are_generic_not_vendor_or_model_specific():
    forbidden = (
        "keysight",
        "rigol",
        "rohde",
        "tektronix",
        "mxr",
        "dsox",
        "edu",
        "n9000",
        "e5071",
        "u2000",
    )
    offenders = []
    for cls in SUPPORTED_CLASSES:
        for descriptor in cls.operation_descriptors():
            op = descriptor.operation_id.lower()
            if any(token in op for token in forbidden):
                offenders.append(f"{cls.__name__}.{descriptor.operation_id}")
    assert not offenders
