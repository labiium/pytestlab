"""Simulator backend contracts and discovery helpers."""

from .capabilities import CapabilityCheck
from .capabilities import SimulatorCapabilities
from .capabilities import UnsupportedCapability
from .capabilities import UnsupportedReason
from .capabilities import get_simulator_capabilities
from .capabilities import list_simulator_backends
from .capabilities import raise_missing_vector
from .capabilities import require_capability
from .eespice_cli import EEspiceCliKernel
from .ngspice_cli import NgspiceCliKernel
from .ngspice_cli import ngspice_capabilities
from .requests import AnalysisKind
from .requests import RequiredFeatures
from .requests import SimulationRequest

__all__ = [
    "AnalysisKind",
    "CapabilityCheck",
    "EEspiceCliKernel",
    "NgspiceCliKernel",
    "RequiredFeatures",
    "SimulationRequest",
    "SimulatorCapabilities",
    "UnsupportedCapability",
    "UnsupportedReason",
    "get_simulator_capabilities",
    "list_simulator_backends",
    "ngspice_capabilities",
    "raise_missing_vector",
    "require_capability",
]
