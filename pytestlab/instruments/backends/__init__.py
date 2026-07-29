from __future__ import annotations

__all__ = [
    "LambBackend",
    "SimBackend",
    "VisaBackend",
]


def __getattr__(name: str):
    """Load optional transport backends only when they are requested."""
    if name == "LambBackend":
        from .lamb import LambBackend

        return LambBackend
    if name == "SimBackend":
        from .sim_backend import SimBackend

        return SimBackend
    if name == "VisaBackend":
        from .visa_backend import VisaBackend

        return VisaBackend
    raise AttributeError(name)
