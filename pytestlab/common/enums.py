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
    "ArbFilterType",
    "ArbAdvanceMode",
    "SweepSpacing",
    "BurstMode",
]


class SCPIOnOff(str, Enum):  # noqa: UP042 - keep str(Enum) semantics for compatibility.
    """SCPI tokens for binary on/off state parameters."""

    ON = "ON"
    OFF = "OFF"


class WaveformType(str, Enum):  # noqa: UP042 - keep str(Enum) semantics for compatibility.
    """Canonical SCPI waveform-shape tokens."""

    SINE = "SIN"
    SQUARE = "SQU"
    RAMP = "RAMP"
    PULSE = "PULS"
    NOISE = "NOIS"
    DC = "DC"
    ARB = "ARB"


class TriggerSlope(str, Enum):  # noqa: UP042 - keep str(Enum) semantics for compatibility.
    """Trigger-edge slope selections shared by instrument drivers."""

    POSITIVE = "POS"
    NEGATIVE = "NEG"
    EITHER = "EITH"
    ALTERNATING = "ALT"  # Check exact SCPI


class AcquisitionType(str, Enum):  # noqa: UP042 - keep str(Enum) semantics for compatibility.
    """Oscilloscope acquisition and sampling modes."""

    NORMAL = "NORM"  # NORMal in SCPI
    AVERAGE = "AVER"  # AVERage
    HIGH_RES = "HRES"  # HRESolution
    PEAK = "PEAK"


class OutputLoadImpedance(str, Enum):  # noqa: UP042 - keep str(Enum) semantics for compatibility.
    """Special output-load impedance tokens accepted by waveform generators."""

    INFINITY = "INFinity"
    MINIMUM = "MINimum"
    MAXIMUM = "MAXimum"
    DEFAULT = "DEFault"
    FIFTY_OHM = "50"  # Common numeric value


class OutputPolarity(str, Enum):  # noqa: UP042 - keep str(Enum) semantics for compatibility.
    """Normal or inverted output polarity selections."""

    NORMAL = "NORMal"
    INVERTED = "INVerted"


class VoltageUnit(str, Enum):  # noqa: UP042 - keep str(Enum) semantics for compatibility.
    """Voltage-amplitude units supported by waveform generators."""

    VPP = "VPP"
    VRMS = "VRMS"
    DBM = "DBM"


class TriggerSource(str, Enum):  # noqa: UP042 - keep str(Enum) semantics for compatibility.
    """Sources that can initiate a triggerable operation."""

    IMMEDIATE = "IMMediate"
    EXTERNAL = "EXTernal"
    TIMER = "TIMer"
    BUS = "BUS"


class SyncMode(str, Enum):  # noqa: UP042 - keep str(Enum) semantics for compatibility.
    """Waveform-generator synchronization output modes."""

    NORMAL = "NORMal"
    CARRIER = "CARRier"
    MARKER = "MARKer"


class ModulationSource(str, Enum):  # noqa: UP042 - keep str(Enum) semantics for compatibility.
    """Internal, channel, or external modulation sources."""

    INTERNAL = "INTernal"
    CH1 = "CH1"
    CH2 = "CH2"
    EXTERNAL = "EXTernal"  # Some instruments support EXT for modulation


class ArbFilterType(str, Enum):  # noqa: UP042 - keep str(Enum) semantics for compatibility.
    """Reconstruction filters for arbitrary waveform playback."""

    NORMAL = "NORMal"
    STEP = "STEP"
    OFF = "OFF"


class ArbAdvanceMode(str, Enum):  # noqa: UP042 - keep str(Enum) semantics for compatibility.
    """Advance modes for sequenced arbitrary waveforms."""

    TRIGGER = "TRIGger"
    SRATE = "SRATe"


class SweepSpacing(str, Enum):  # noqa: UP042 - keep str(Enum) semantics for compatibility.
    """Linear or logarithmic waveform-generator sweep spacing."""

    LINEAR = "LINear"
    LOGARITHMIC = "LOGarithmic"


class BurstMode(str, Enum):  # noqa: UP042 - keep str(Enum) semantics for compatibility.
    """Triggered and gated waveform burst modes."""

    TRIGGERED = "TRIGgered"
    GATED = "GATed"
