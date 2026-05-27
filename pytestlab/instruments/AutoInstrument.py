from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config.instrument_config import InstrumentConfig
from ..devices.factory import AutoDevice
from ..errors import InstrumentConfigurationError
from .instrument import Instrument
from .instrument import InstrumentIO


class AutoInstrument:
    """Factory for drivers that are specifically ``Instrument`` subclasses."""

    @classmethod
    def from_type(
        cls: type[AutoInstrument], device_type: str, *args: Any, **kwargs: Any
    ) -> Instrument[Any]:
        device = AutoDevice.from_type(device_type, *args, **kwargs)
        if not isinstance(device, Instrument):
            raise InstrumentConfigurationError(
                device_type,
                f"Device type '{device_type}' resolved to {type(device).__name__}, not Instrument.",
            )
        return device

    @classmethod
    def from_config(
        cls: type[AutoInstrument],
        config_source: str | dict[str, Any] | InstrumentConfig,
        *args: Any,
        serial_number: str | None = None,
        debug_mode: bool = False,
        simulate: bool | None = None,
        backend_type_hint: str | None = None,
        address_override: str | None = None,
        timeout_override_ms: int | None = None,
        backend_override: InstrumentIO | None = None,
        backend_spec_override: dict[str, Any] | None = None,
        sim_session: Any | None = None,
        role_override: str | None = None,
    ) -> Instrument[Any]:
        device = AutoDevice.from_config(
            config_source,
            *args,
            serial_number=serial_number,
            debug_mode=debug_mode,
            simulate=simulate,
            backend_type_hint=backend_type_hint,
            address_override=address_override,
            timeout_override_ms=timeout_override_ms,
            backend_override=backend_override,
            backend_spec_override=backend_spec_override,
            sim_session=sim_session,
            role_override=role_override,
        )
        if not isinstance(device, Instrument):
            raise InstrumentConfigurationError(
                config_source,
                f"Config resolved to {type(device).__name__}, not an Instrument.",
            )
        return device

    @classmethod
    def from_profile(
        cls: type[AutoInstrument],
        profile_key_or_path: str | Path,
        *args: Any,
        serial_number: str | None = None,
        debug_mode: bool = False,
        simulate: bool | None = None,
        backend_type_hint: str | None = None,
        address_override: str | None = None,
        timeout_override_ms: int | None = None,
        backend_override: InstrumentIO | None = None,
        backend_spec_override: dict[str, Any] | None = None,
        sim_session: Any | None = None,
        role_override: str | None = None,
    ) -> Instrument[Any]:
        device = AutoDevice.from_profile(
            profile_key_or_path,
            *args,
            serial_number=serial_number,
            debug_mode=debug_mode,
            simulate=simulate,
            backend_type_hint=backend_type_hint,
            address_override=address_override,
            timeout_override_ms=timeout_override_ms,
            backend_override=backend_override,
            backend_spec_override=backend_spec_override,
            sim_session=sim_session,
            role_override=role_override,
        )
        if not isinstance(device, Instrument):
            raise InstrumentConfigurationError(
                profile_key_or_path,
                f"Profile resolved to {type(device).__name__}, not an Instrument.",
            )
        return device

    @classmethod
    def register_instrument(
        cls: type[AutoInstrument],
        device_type: str,
        instrument_class: type[Instrument[Any]],
    ) -> None:
        from ..devices.registry import register_device_type

        if not issubclass(instrument_class, Instrument):
            raise InstrumentConfigurationError(
                device_type,
                f"Cannot register class {instrument_class.__name__}. It must be a subclass of Instrument.",
            )
        register_device_type(device_type, instrument_class)

    get_config_from_cdn = AutoDevice.get_config_from_cdn
    get_config_from_local = AutoDevice.get_config_from_local
