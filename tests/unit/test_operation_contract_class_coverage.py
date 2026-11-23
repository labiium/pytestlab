from pytestlab.instruments.DCActiveLoad import DCActiveLoad
from pytestlab.instruments.ImpedanceAnalyzer import ImpedanceAnalyzer
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
    ImpedanceAnalyzer,
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


def test_every_operation_names_an_explicit_public_method():
    missing = []
    for cls in SUPPORTED_CLASSES:
        for descriptor in cls.operation_descriptors():
            method_name = descriptor.public_method or descriptor.operation_id
            if method_name.startswith("_") or not callable(getattr(cls, method_name, None)):
                missing.append(f"{cls.__name__}.{descriptor.operation_id}->{method_name}")
    assert not missing


def test_every_public_io_method_has_an_operation_contract():
    non_io_helpers = {
        WaveformGenerator: {"channel"},
        Oscilloscope: {"channel", "health_check", "plot_channels"},
        PowerSupply: {"channel"},
        DCActiveLoad: {"health_check"},
    }
    # Guard overrides of inherited transport/lifecycle primitives do not create
    # new profile operations. Confirm that each exception actually has a base implementation.
    guarded_inherited_io = {
        PowerMeter: {
            "write",
            "query",
            "query_raw",
            "read",
            "read_raw",
            "read_status_byte",
            "close",
            "attempt_error_recovery",
        }
    }
    missing = []
    for cls in SUPPORTED_CLASSES:
        described = {
            descriptor.public_method or descriptor.operation_id
            for descriptor in cls.operation_descriptors()
        }
        excluded = non_io_helpers.get(cls, set())
        for name, value in cls.__dict__.items():
            if name.startswith("_") or name in excluded or not callable(value):
                continue
            if name in guarded_inherited_io.get(cls, set()) and any(
                callable(base.__dict__.get(name)) for base in cls.__mro__[1:]
            ):
                continue
            if name not in described:
                missing.append(f"{cls.__name__}.{name}")
    assert not missing
