"""Bench-scoped lifecycle support for backends with shared resources."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field
from importlib import import_module
from pathlib import Path
from typing import Any
from typing import Protocol
from typing import runtime_checkable

from ..errors import InstrumentConfigurationError


@runtime_checkable
class BackendProvider(Protocol):
    """Prepare and release one backend's bench-scoped shared resource."""

    def is_configured(self, config: Any) -> bool:
        """Return whether this provider is needed by ``config``."""

    def prepare(self, config: Any, *, base_path: Path | None) -> Any:
        """Create the resource shared by this backend's device instances."""

    def cleanup(self, resource: Any) -> None:
        """Release a resource created by :meth:`prepare`."""


@dataclass
class BackendResourceScope:
    """Owned collection of prepared backend resources with idempotent cleanup."""

    _resources: dict[str, Any] = field(default_factory=dict)
    _cleanups: list[tuple[BackendProvider, Any]] = field(default_factory=list)
    _closed: bool = False

    @property
    def resources(self) -> Mapping[str, Any]:
        return self._resources

    def get(self, backend_type: str, default: Any = None) -> Any:
        return self._resources.get(backend_type.lower(), default)

    def add(self, backend_type: str, provider: BackendProvider, resource: Any) -> None:
        if self._closed:
            raise RuntimeError("Cannot add resources to a closed backend scope.")
        key = backend_type.lower()
        if key in self._resources:
            raise InstrumentConfigurationError(
                backend_type, f"Backend resource '{backend_type}' was prepared more than once."
            )
        self._resources[key] = resource
        self._cleanups.append((provider, resource))

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        first_error: Exception | None = None
        for provider, resource in reversed(self._cleanups):
            try:
                provider.cleanup(resource)
            except Exception as exc:  # cleanup all resources before reporting failure
                first_error = first_error or exc
        self._cleanups.clear()
        self._resources.clear()
        if first_error is not None:
            raise first_error

    def __enter__(self) -> BackendResourceScope:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()


_providers: dict[str, BackendProvider] = {}
_provider_specs: dict[str, tuple[str, str]] = {
    "circuit_sim": ("pytestlab.config.bench_loader", "CircuitSimBackendProvider"),
}


def register_backend_provider(
    backend_type: str, provider: BackendProvider, *, replace: bool = False
) -> None:
    """Register a bench-scoped backend provider."""
    key = backend_type.lower()
    if key in _providers and not replace:
        raise InstrumentConfigurationError(
            backend_type, f"Backend provider '{backend_type}' is already registered."
        )
    if not isinstance(provider, BackendProvider):
        raise InstrumentConfigurationError(
            backend_type,
            "Backend provider must define is_configured(), prepare(), and cleanup().",
        )
    _providers[key] = provider
    _provider_specs.pop(key, None)


def get_backend_provider(backend_type: str) -> BackendProvider | None:
    """Return a provider, lazily loading built-in implementations."""
    key = backend_type.lower()
    spec = _provider_specs.pop(key, None)
    if spec is not None:
        module_name, attr_name = spec
        provider_type = getattr(import_module(module_name), attr_name)
        register_backend_provider(key, provider_type(), replace=True)
    return _providers.get(key)


def prepare_backend_resources(config: Any, *, base_path: Path | None) -> BackendResourceScope:
    """Prepare every configured provider and roll back if any preparation fails."""
    scope = BackendResourceScope()
    try:
        for key in tuple(dict.fromkeys([*_provider_specs, *_providers])):
            provider = get_backend_provider(key)
            if provider is not None and provider.is_configured(config):
                scope.add(key, provider, provider.prepare(config, base_path=base_path))
    except Exception as prepare_error:
        try:
            scope.close()
        except Exception as cleanup_error:
            prepare_error.add_note(f"Backend resource rollback also failed: {cleanup_error}")
        raise
    return scope


__all__ = [
    "BackendProvider",
    "BackendResourceScope",
    "get_backend_provider",
    "prepare_backend_resources",
    "register_backend_provider",
]
