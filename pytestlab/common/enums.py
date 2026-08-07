from enum import Enum

__all__ = [
    "SCPIOnOff",
    "WaveformType",
    "TriggerSlope",
    "AcquisitionType",
    "OutputLoadImpedance",
    "OutputPolarity",
    "VoltageUnit",
    "TriggerSource",
    "SyncMode",
    "ModulationSource",
]


class SCPIOnOff(str, Enum):  # noqa: UP042 - keep str(Enum) semantics for compatibility.
    ON = "ON"
    OFF = "OFF"


class WaveformType(str, Enum):  # noqa: UP042 - keep str(Enum) semantics for compatibility.
    SINE = "SIN"
    SQUARE = "SQU"
    RAMP = "RAMP"
    PULSE = "PULS"
    NOISE = "NOIS"
    DC = "DC"
    ARB = "ARB"


class TriggerSlope(str, Enum):  # noqa: UP042 - keep str(Enum) semantics for compatibility.
    POSITIVE = "POS"
    NEGATIVE = "NEG"
    EITHER = "EITH"
    ALTERNATING = "ALT"  # Check exact SCPI


class AcquisitionType(str, Enum):  # noqa: UP042 - keep str(Enum) semantics for compatibility.
    NORMAL = "NORM"  # NORMal in SCPI
    AVERAGE = "AVER"  # AVERage
    HIGH_RES = "HRES"  # HRESolution
    PEAK = "PEAK"


class OutputLoadImpedance(str, Enum):  # noqa: UP042 - keep str(Enum) semantics for compatibility.
    INFINITY = "INFinity"
    MINIMUM = "MINimum"
    MAXIMUM = "MAXimum"
    DEFAULT = "DEFault"
    FIFTY_OHM = "50"  # Common numeric value


class OutputPolarity(str, Enum):  # noqa: UP042 - keep str(Enum) semantics for compatibility.
    NORMAL = "NORMal"
    INVERTED = "INVerted"


class VoltageUnit(str, Enum):  # noqa: UP042 - keep str(Enum) semantics for compatibility.
    VPP = "VPP"
    VRMS = "VRMS"
    DBM = "DBM"


class TriggerSource(str, Enum):  # noqa: UP042 - keep str(Enum) semantics for compatibility.
    IMMEDIATE = "IMMediate"
    EXTERNAL = "EXTernal"
    TIMER = "TIMer"
    BUS = "BUS"


class SyncMode(str, Enum):  # noqa: UP042 - keep str(Enum) semantics for compatibility.
    NORMAL = "NORMal"
    CARRIER = "CARRier"
    MARKER = "MARKer"


class ModulationSource(str, Enum):  # noqa: UP042 - keep str(Enum) semantics for compatibility.
    INTERNAL = "INTernal"
    CH1 = "CH1"
    CH2 = "CH2"
    EXTERNAL = "EXTernal"  # Some instruments support EXT for modulation


class ArbFilterType(str, Enum):  # noqa: UP042 - keep str(Enum) semantics for compatibility.
    NORMAL = "NORMal"
    STEP = "STEP"
    OFF = "OFF"


class ArbAdvanceMode(str, Enum):  # noqa: UP042 - keep str(Enum) semantics for compatibility.
    TRIGGER = "TRIGger"
    SRATE = "SRATe"


class SweepSpacing(str, Enum):  # noqa: UP042 - keep str(Enum) semantics for compatibility.
    LINEAR = "LINear"
    LOGARITHMIC = "LOGarithmic"


class BurstMode(str, Enum):  # noqa: UP042 - keep str(Enum) semantics for compatibility.
    TRIGGERED = "TRIGgered"
    GATED = "GATed"
