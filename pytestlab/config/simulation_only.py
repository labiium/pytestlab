"""Normalize trusted bench input for PyTestLab's built-in, offline simulator path."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from ..devices.factory import AutoDevice
from ..devices.registry import is_builtin_profile_import
from .bench_config import BenchConfigExtended
from .bench_config import DeviceEntry

_BUILTIN_TRANSPORTS = {"sim", "circuit_sim", "visa", "lamb"}
_CIRCUIT_TYPES = {"waveform_generator", "power_supply", "oscilloscope", "multimeter"}
_REPLAY_TYPES = _CIRCUIT_TYPES | {
    "instrument",
    "profile_instrument",
    "generic_instrument",
    "dc_active_load",
    "vna",
    "vector_network_analyzer",
    "impedance_analyzer",
    "spectrum_analyzer",
    "power_meter",
    "switch_matrix",
    "source_measure",
}


def _local_path(value: str | Path, base_path: Path | None) -> Path:
    path = Path(value)
    if not path.is_absolute():
        if base_path is None:
            raise ValueError("Relative simulator inputs require a bench descriptor file.")
        path = base_path / path
    return path.resolve()


def _profile_path(entry: DeviceEntry, base_path: Path | None) -> Path:
    source = entry.resolved_source()
    if isinstance(source, Path):
        return _local_path(source, base_path)
    # Packaged keys cannot escape the installed profiles tree or fall back to the CDN.
    root = (Path(__file__).resolve().parents[1] / "profiles").resolve()
    path = (root / source).with_suffix(".yaml").resolve()
    if not path.is_relative_to(root):
        raise ValueError("Simulator profile keys must stay within packaged profiles.")
    return path


def _backend_type(spec: Any) -> str | None:
    if spec is None:
        return None
    if not isinstance(spec, Mapping) or "import_path" in spec:
        raise ValueError("custom backend configuration is not supported")
    value = spec.get("type")
    if value is None:
        return None
    if not isinstance(value, str) or value.lower() not in _BUILTIN_TRANSPORTS:
        raise ValueError(f"unsupported backend type {value!r}")
    return value.lower()


def normalize_simulation_config(
    config: BenchConfigExtended, *, base_path: Path | None
) -> BenchConfigExtended:
    """Preflight every entry before any backend provider or factory is called.

    No executable hook or third-party driver/backend is admitted. This is not
    isolation for arbitrary Python, simulator input, or code run by the caller.
    """
    hooks = config.automation
    if hooks is not None and (hooks.pre_experiment or hooks.post_experiment):
        raise ValueError("Simulation-only benches do not run automation hooks; remove them first.")

    result = config.model_copy(deep=True)
    result.simulate = True
    result.simulation_only = True
    result.automation = None
    result.backend_defaults = None
    result.continue_on_device_error = False
    circuit_entries = 0
    for alias, entry in {**result.devices, **result.instruments}.items():
        try:
            if entry.device_type is not None:
                raise ValueError(f"no built-in offline simulator for {entry.device_type!r}")
            selection = _backend_type(entry.backend)
            profile = _profile_path(entry, base_path)
            data = AutoDevice.get_config_from_file(profile)
            if "profile" in data:
                raise ValueError("nested profile selection is not supported")
            _backend_type(data.get("backend"))
            mode = "circuit_sim" if selection == "circuit_sim" else "sim"
            supported = _CIRCUIT_TYPES if mode == "circuit_sim" else _REPLAY_TYPES
            device_type = data.get("device_type")
            if not isinstance(device_type, str) or device_type not in supported:
                raise ValueError(f"no built-in {mode} for device_type {device_type!r}")
            for key in ("driver", "config_model"):
                value = data.get(key)
                if value is not None and (
                    not isinstance(value, str)
                    or not is_builtin_profile_import(
                        value, device_type, config=key == "config_model"
                    )
                ):
                    raise ValueError(f"custom {key} imports are not supported")
            AutoDevice._load_config_model(data, role_override=entry.role)
            if mode == "sim" and not isinstance(data.get("simulation"), Mapping):
                raise ValueError("profile has no local simulation section")
            if mode == "circuit_sim":
                if result.sim_circuit is None:
                    raise ValueError("circuit_sim requires a sim_circuit section")
                circuit_entries += 1

            # Resolve packaged and local profiles to the very same file that was
            # inspected. No user-profile lookup, live address, or transport override.
            entry.profile = None
            entry.file = str(profile)
            entry.address = "sim"
            entry.serial_number = None
            entry.simulate = True
            entry.transport = None
            entry.backend = {"type": mode}
        except (ValueError, OSError, yaml.YAMLError) as exc:
            raise ValueError(f"Cannot simulate bench entry {alias!r}: {exc}") from exc

    if result.sim_circuit is not None:
        if not circuit_entries:
            raise ValueError("sim_circuit has no entries using the circuit_sim backend.")
        source_key = "netlist" if result.sim_circuit.netlist is not None else "twin_package"
        source = _local_path(getattr(result.sim_circuit, source_key), base_path)
        if not source.exists():
            raise ValueError(f"Missing circuit simulation input: {source}")
        setattr(result.sim_circuit, source_key, str(source))

    for entry in result.accessories.values():
        if entry.file is not None:
            entry.file = str(_local_path(entry.file, base_path))
        elif entry.profile and Path(entry.profile).suffix.lower() in {".yaml", ".yml", ".json"}:
            entry.profile = str(_local_path(entry.profile, base_path))
    return result
