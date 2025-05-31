from enum import Enum

class SCPIOnOff(str, Enum):
    ON = "ON"
    OFF = "OFF"

class WaveformType(str, Enum):
    SINE = "SIN"
    SQUARE = "SQU"
    RAMP = "RAMP"
    PULSE = "PULS"
    NOISE = "NOIS"
    DC = "DC"
    ARB = "ARB"

class TriggerSlope(str, Enum):
    POSITIVE = "POS"
    NEGATIVE = "NEG"
    EITHER = "EITH"
    ALTERNATING = "ALT" # Check exact SCPI

class AcquisitionType(str, Enum):
    NORMAL = "NORM"    # NORMal in SCPI
    AVERAGE = "AVER"   # AVERage
    HIGH_RES = "HRES"  # HRESolution
    PEAK = "PEAK"

class OutputLoadImpedance(str, Enum):
    INFINITY = "INFinity"
    MINIMUM = "MINimum"
    MAXIMUM = "MAXimum"
    DEFAULT = "DEFault"
    FIFTY_OHM = "50" # Common numeric value

class OutputPolarity(str, Enum):
    NORMAL = "NORMal"
    INVERTED = "INVerted"

class VoltageUnit(str, Enum):
    VPP = "VPP"
    VRMS = "VRMS"
    DBM = "DBM"

class TriggerSource(str, Enum):
    IMMEDIATE = "IMMediate"
    EXTERNAL = "EXTernal"
    TIMER = "TIMer"
    BUS = "BUS"

class SyncMode(str, Enum):
    NORMAL = "NORMal"
    CARRIER = "CARRier"
    MARKER = "MARKer"

class ModulationSource(str, Enum):
    INTERNAL = "INTernal"
    CH1 = "CH1"
    CH2 = "CH2"
    EXTERNAL = "EXTernal" # Some instruments support EXT for modulation

class ArbFilterType(str, Enum):
    NORMAL = "NORMal"
    STEP = "STEP"
    OFF = "OFF"

class ArbAdvanceMode(str, Enum):
    TRIGGER = "TRIGger"
    SRATE = "SRATe"

class SweepSpacing(str, Enum):
    LINEAR = "LINear"
    LOGARITHMIC = "LOGarithmic"

class BurstMode(str, Enum):
    TRIGGERED = "TRIGgered"
    GATED = "GATed"