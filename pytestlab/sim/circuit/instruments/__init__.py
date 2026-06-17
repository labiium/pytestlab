from ..wiring import AwgRef
from ..wiring import DmmRef
from ..wiring import PsuRef
from ..wiring import ScopeRef
from .base import InstrumentState
from .base import InstrumentTwin
from .base import MeasurementResult
from .twins import AWGTwin
from .twins import DMMTwin
from .twins import PSUTwin
from .twins import ScopeTwin


def psu(instrument_id: str) -> PsuRef:
    return PsuRef(instrument_id)


def awg(instrument_id: str) -> AwgRef:
    return AwgRef(instrument_id)


def scope(instrument_id: str) -> ScopeRef:
    return ScopeRef(instrument_id)


def dmm(instrument_id: str) -> DmmRef:
    return DmmRef(instrument_id)

__all__ = [
    "InstrumentTwin",
    "MeasurementResult",
    "InstrumentState",
    "PSUTwin",
    "AWGTwin",
    "DMMTwin",
    "ScopeTwin",
    "awg",
    "dmm",
    "psu",
    "scope",
]
