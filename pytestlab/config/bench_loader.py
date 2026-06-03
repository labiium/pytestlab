from __future__ import annotations

import ast
import operator
from pathlib import Path
from typing import Any

import yaml

from ..devices.factory import AutoDevice
from ..errors import InstrumentConfigurationError
from .bench_config import BenchConfigExtended
from .bench_config import SimCircuitConfig


def load_bench_yaml(path_or_dict: str | Path | dict) -> BenchConfigExtended:
    """Load and validate a bench configuration from a YAML file or dictionary."""
    if isinstance(path_or_dict, str | Path):
        with open(path_or_dict) as f:
            data = yaml.safe_load(f)
    elif isinstance(path_or_dict, dict):
        data = path_or_dict
    else:
        raise TypeError("Input must be a path or dict.")
    config = BenchConfigExtended.model_validate(data)
    return config


def load_sim_bench_yaml(path: str | Path) -> tuple[BenchConfigExtended, Any | None]:
    """Load a bench YAML and build the shared circuit-simulation Session when configured."""
    config = load_bench_yaml(path)
    if config.sim_circuit is None:
        return config, None

    from pytestlab_sim import KernelSettings
    from pytestlab_sim import Session
    from pytestlab_sim import circuit_from_netlist
    from pytestlab_sim import noise_config_from_preset
    from pytestlab_sim.noise import NoisePreset

    bench_path = Path(path)
    sc = config.sim_circuit
    netlist_path = (bench_path.parent / sc.netlist).resolve()
    circuit = circuit_from_netlist(
        netlist_path,
        metadata={
            "title": netlist_path.stem,
            "author": "pytestlab",
            "license": "UNLICENSED",
            "intended_analyses": ["op", "tran", "ac"],
        },
    )
    sim_bench = _build_sim_bench_from_bench_config(config, base_path=bench_path.parent)
    wiring = _build_sim_wiring_from_entries(sc)
    noise = noise_config_from_preset(NoisePreset(sc.noise_preset), seed=sc.noise_seed)
    kernel_settings = KernelSettings(**sc.kernel_settings) if sc.kernel_settings else None
    session = Session(
        circuit=circuit,
        bench=sim_bench,
        wiring=wiring,
        seed=sc.seed,
        noise=noise,
        kernel_settings=kernel_settings,
    )

    return config, session


def _build_sim_bench_from_bench_config(config: BenchConfigExtended, *, base_path: Path | None = None):
    from pytestlab_sim.bench import AWG
    from pytestlab_sim.bench import DMM
    from pytestlab_sim.bench import PSU
    from pytestlab_sim.bench import BenchConfig as SimBenchConfig
    from pytestlab_sim.bench import PSUChannel
    from pytestlab_sim.bench import Scope

    instruments: dict[str, Any] = {}
    for alias, entry in {**config.devices, **config.instruments}.items():
        if not entry.backend or entry.backend.get("type") != "circuit_sim":
            continue
        device_type = _device_type_for_profile(entry.resolved_source(base_path=base_path))
        if device_type == "waveform_generator":
            instruments[alias] = AWG(vpp_max=10.0)
        elif device_type == "power_supply":
            instruments[alias] = PSU(channels=[PSUChannel(name="CH1", v_max=60.0, i_max=5.0)])
        elif device_type == "oscilloscope":
            instruments[alias] = Scope(channels=4)
        elif device_type == "multimeter":
            instruments[alias] = DMM()
        else:
            raise InstrumentConfigurationError(
                alias,
                f"circuit_sim does not support {entry.source_kind} '{entry.source}' "
                f"with device_type '{device_type}'.",
            )
    return SimBenchConfig(bench_id=config.bench_name, instruments=instruments)


def _device_type_for_profile(profile: str | Path) -> str:
    try:
        config_data = AutoDevice._load_config_data_from_string(str(profile))
    except Exception as exc:
        raise InstrumentConfigurationError(
            profile,
            f"Could not load profile for circuit_sim backend: {exc}",
        ) from exc
    device_type = config_data.get("device_type")
    if not isinstance(device_type, str) or not device_type:
        raise InstrumentConfigurationError(profile, "Profile must declare a device_type.")
    return device_type


def _build_sim_wiring_from_entries(sc: SimCircuitConfig):
    from pytestlab_sim.wiring import Connection
    from pytestlab_sim.wiring import WiringConfig
    from pytestlab_sim.wiring import WiringRules

    connections = [
        Connection(from_=_normalize_sim_terminal(term), to=str(node))
        for term, node in sc.wiring.items()
    ]
    return WiringConfig(
        connections=connections,
        rules=WiringRules(allow_output_sharing=True),
    )


def _normalize_sim_terminal(term: str) -> str:
    return term.replace("+", ".HI").replace("-", ".LO")


def build_validation_context(config: BenchConfigExtended) -> dict[str, Any]:
    """Build a context dictionary for custom validation expressions."""
    context = {}
    for alias, entry in config.devices.items():
        context[alias] = entry.model_dump()
    for alias, entry in config.instruments.items():
        context[alias] = entry.model_dump()
    context["experiment"] = config.experiment.model_dump() if config.experiment else {}
    return context


def run_custom_validations(config: BenchConfigExtended, context: dict) -> None:
    """Run custom validation expressions and raise ValueError if any fail."""
    if not config.custom_validations:
        return
    for expr in config.custom_validations:
        try:
            if not _safe_eval_validation(expr, context):
                raise ValueError(f"Custom validation failed: {expr}")
        except Exception as e:
            raise ValueError(f"Error evaluating custom validation '{expr}': {e}") from e


_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
    ast.Not: operator.not_,
}
_CMP_OPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.Is: operator.is_,
    ast.IsNot: operator.is_not,
    ast.In: lambda left, right: left in right,
    ast.NotIn: lambda left, right: left not in right,
}


def _safe_eval_validation(expr: str, context: dict[str, Any]) -> Any:
    tree = ast.parse(expr, mode="eval")
    return _eval_node(tree.body, context)


def _eval_node(node: ast.AST, context: dict[str, Any]) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id not in context:
            raise ValueError(f"Unknown validation name: {node.id}")
        return context[node.id]
    if isinstance(node, ast.Subscript):
        value = _eval_node(node.value, context)
        key = _eval_node(node.slice, context)
        return value[key]
    if isinstance(node, ast.List):
        return [_eval_node(item, context) for item in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_eval_node(item, context) for item in node.elts)
    if isinstance(node, ast.Dict):
        result: dict[Any, Any] = {}
        for key, value in zip(node.keys, node.values, strict=True):
            if key is None:
                raise ValueError("Dictionary unpacking is not supported in validation expressions.")
            result[_eval_node(key, context)] = _eval_node(value, context)
        return result
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            bool_result: Any = True
            for value in node.values:
                bool_result = _eval_node(value, context)
                if not bool_result:
                    return bool_result
            return bool_result
        if isinstance(node.op, ast.Or):
            bool_result = False
            for value in node.values:
                bool_result = _eval_node(value, context)
                if bool_result:
                    return bool_result
            return bool_result
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _UNARY_OPS[type(node.op)](_eval_node(node.operand, context))
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        return _BIN_OPS[type(node.op)](
            _eval_node(node.left, context), _eval_node(node.right, context)
        )
    if isinstance(node, ast.Compare):
        left = _eval_node(node.left, context)
        for op, comparator in zip(node.ops, node.comparators, strict=True):
            if type(op) not in _CMP_OPS:
                raise ValueError(f"Unsupported comparison: {type(op).__name__}")
            right = _eval_node(comparator, context)
            if not _CMP_OPS[type(op)](left, right):
                return False
            left = right
        return True
    raise ValueError(f"Unsupported validation expression: {type(node).__name__}")
