from __future__ import annotations

import hashlib
import time
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field
from typing import Any
from typing import cast

import numpy as np

from .bench import AWG
from .bench import DMM
from .bench import PSU
from .bench import BenchConfig
from .bench import Scope
from .circuit_package import CircuitPackage
from .determinism import make_rng
from .instruments.twins import AWGTwin
from .instruments.twins import DMMTwin
from .instruments.twins import PSUTwin
from .instruments.twins import ScopeTwin
from .kernel import KernelAdapter
from .kernel import NgspiceKernel
from .netlist import extract_nodes
from .noise import NoiseConfig
from .parameters import ParameterSet
from .parameters import ParameterSpec
from .parameters import normalize_parameter_set
from .parameters import parameter_hash
from .physics_model import PhysicsModel
from .plugins import get_plugin
from .spice import KernelSettings
from .variations import VariationConfig
from .wiring import UnknownNode
from .wiring import WiringCompiler
from .wiring import WiringConfig


@dataclass
class SessionMetadata:
    session_id: str
    seed: int
    created_at: float = field(default_factory=time.time)


class Session:
    def __init__(
        self,
        circuit: CircuitPackage,
        bench: BenchConfig,
        wiring: WiringConfig,
        seed: int = 1337,
        *,
        spice_engine: str = "ngspice",
        ngspice_cmd: str = "ngspice",
        eespice_cmd: str = "eespice",
        kernel: KernelAdapter | None = None,
        kernel_settings: KernelSettings | None = None,
        variations: VariationConfig | None = None,
        noise: NoiseConfig | None = None,
        physics_models: dict[str, PhysicsModel] | None = None,
        model_params: dict[str, float] | ParameterSet | None = None,
        parameter_specs: Mapping[str, ParameterSpec | Mapping[str, Any]] | None = None,
        store: object | None = None,
        telemetry: object | None = None,
    ):
        self.circuit = circuit
        self.bench = bench
        self.wiring = wiring
        self.seed = seed
        self.spice_engine = spice_engine
        self.ngspice_cmd = ngspice_cmd
        self.eespice_cmd = eespice_cmd
        self.kernel = kernel or self._default_kernel(spice_engine, ngspice_cmd, eespice_cmd)
        self.kernel_settings = kernel_settings or KernelSettings(
            timeout_s=10.0,
            cpu_time_s=5,
            max_memory_mb=512,
        )
        self.variations = variations
        self.noise = noise or NoiseConfig()
        noise_seed = self.seed if self.noise.seed is None else self.seed ^ int(self.noise.seed)
        self.noise_rng = make_rng(noise_seed)
        self.physics_models = physics_models or {}
        self.parameter_set = normalize_parameter_set(model_params, specs=parameter_specs)
        self.model_params = dict(self.parameter_set.values)
        self.store = store
        self.telemetry = telemetry
        self.twin_package: dict[str, Any] | None = None
        self.metadata = SessionMetadata(session_id=self._hash_identity(), seed=seed)
        self.node_set = self._extract_node_set()
        self.compiler = WiringCompiler(bench=self.bench, wiring=self.wiring, nodes=self.node_set)
        self.mapping = self.compiler.compile()
        self.probe_elements = self.compiler.inject_probe_loading()
        self.psus: dict[str, PSUTwin] = {}
        self.awgs: dict[str, AWGTwin] = {}
        self.dmms: dict[str, DMMTwin] = {}
        self.scopes: dict[str, ScopeTwin] = {}
        self.extensions: dict[str, object] = {}
        self._instantiate_instruments()

    @staticmethod
    def _default_kernel(
        spice_engine: str,
        ngspice_cmd: str,
        eespice_cmd: str,
    ) -> KernelAdapter:
        engine = spice_engine.lower().replace("-", "_")
        if engine in {"auto", "ngspice"}:
            return NgspiceKernel(cmd=ngspice_cmd)
        if engine == "eespice":
            from .simulators.eespice_cli import EEspiceCliKernel

            return EEspiceCliKernel(cmd=eespice_cmd)
        raise ValueError(f"unsupported spice_engine: {spice_engine}")

    def _extract_node_set(self) -> set[str] | None:
        """Return the authoritative netlist node set, or ``None`` if unavailable.

        Used to validate wiring and probe node names against real circuit nodes.
        A missing netlist keeps validation unavailable for compatibility, but
        parser/extraction failures must fail loudly so validation is not
        silently disabled.
        """
        entry = self.circuit.root / self.circuit.manifest.entry_netlist
        try:
            return extract_nodes(entry.read_text(), base_dir=entry.parent)
        except FileNotFoundError:
            return None
        except (OSError, UnicodeError, ValueError) as exc:
            raise ValueError(f"failed to extract nodes from {entry}: {exc}") from exc

    def validate_nodes(self, *names: str) -> None:
        """Raise :class:`UnknownNode` if any name is not a real netlist node.

        Ground (``0`` / the configured ground node) is always accepted. No-ops
        when the node set could not be determined.
        """
        if self.node_set is None:
            return
        allowed = {n.lower() for n in self.node_set}
        ground = {"0", str(self.wiring.ground_node).strip().lower()}
        for name in names:
            canonical = str(name).strip().lower()
            if canonical in ground or canonical in allowed:
                continue
            raise UnknownNode(name, available=self.node_set)

    def _hash_identity(self) -> str:
        digest = hashlib.sha256()
        digest.update(self.circuit.to_content_hash().encode())
        digest.update(self.bench.bench_id.encode())
        digest.update(str(self.seed).encode())
        digest.update(parameter_hash(getattr(self, "parameter_set", None)).encode())
        digest.update(self.wiring.ground_node.encode())
        return digest.hexdigest()[:16]

    def resolve_model_params(self, call_params: dict[str, float] | None = None) -> dict[str, float]:
        """Return session calibrated parameters merged with per-call overrides."""
        return self.parameter_set.resolve(call_params)

    @property
    def parameter_hash(self) -> str:
        return parameter_hash(self.parameter_set)

    def _instantiate_instruments(self) -> None:
        for inst_id, inst in self.bench.instruments.items():
            if inst.kind == "PSU":
                self.psus[inst_id] = PSUTwin(
                    seed=self.seed, config=cast(PSU, inst), limits=self.bench.limits
                )
            elif inst.kind == "AWG":
                self.awgs[inst_id] = AWGTwin(
                    seed=self.seed, config=cast(AWG, inst), limits=self.bench.limits
                )
            elif inst.kind == "DMM":
                self.dmms[inst_id] = DMMTwin(
                    seed=self.seed, config=cast(DMM, inst), limits=self.bench.limits
                )
            elif inst.kind == "SCOPE":
                self.scopes[inst_id] = ScopeTwin(
                    seed=self.seed, config=cast(Scope, inst), limits=self.bench.limits
                )
            else:
                plugin = get_plugin(inst.kind)
                if plugin is None:
                    raise ValueError(f"unsupported instrument kind: {inst.kind}")
                self.extensions[inst_id] = plugin.create_twin(
                    seed=self.seed, config=inst, limits=self.bench.limits
                )

    def acquire_scope(self, scope_id: str, channel: str, waveform: np.ndarray):
        scope = self.scopes[scope_id]
        if not scope.state.enabled:
            raise ValueError("scope channel disabled")
        return scope.acquire(waveform)

    def read_dmm(self, dmm_id: str, node_voltage: float):
        dmm = self.dmms[dmm_id]
        return dmm.measure(node_voltage)

    def psu_output(self, psu_id: str, voltage: float, current_limit: float):
        psu = self.psus[psu_id]
        channel = psu.state.selected_channel
        psu.set_state(channel=channel, voltage_setpoint=voltage, current_limit=current_limit)
        psu.set_state(channel=channel, enabled=True)
        return psu.measure(channel=channel)
