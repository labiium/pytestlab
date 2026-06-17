from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import warnings
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any
from typing import Literal
from typing import cast

import numpy as np

if TYPE_CHECKING:
    from .session import Session

from .models import SourceDescriptor
from .netlist import expand_includes
from .plugins import get_plugin
from .variations import apply_variations_and_faults


class SpiceEngineError(RuntimeError):
    pass


class NgspiceNotFound(SpiceEngineError):
    pass


# ngspice is a system dependency: ``pip install pytestlab[circuit]`` installs the
# Python lane but NOT the simulator binary. Keep the guidance here so every
# resolution failure points the user at a real install path.
_NGSPICE_INSTALL_HELP = (
    "The pytestlab.sim.circuit lane needs an `ngspice` binary on PATH; the "
    "`pytestlab[circuit]` extra does not (and cannot) install it. Install it via:\n"
    "  - Debian/Ubuntu: sudo apt-get install ngspice\n"
    "  - macOS (Homebrew): brew install ngspice\n"
    "  - conda: conda install -c conda-forge ngspice\n"
    "  - Docker: docker run --rm danchitnis/ngspice ngspice -v\n"
    "Or point the bench at a specific binary with the `ngspice_cmd` setting."
)


def _ngspice_not_found(resolved_cmd: str) -> NgspiceNotFound:
    return NgspiceNotFound(
        f"ngspice command not found ({resolved_cmd!r}).\n{_NGSPICE_INSTALL_HELP}"
    )


class NgspiceRunError(SpiceEngineError):
    pass


@dataclass(frozen=True)
class KernelSettings:
    reltol: float = 1e-3
    abstol: float = 1e-12
    vntol: float = 1e-6
    maxstep: float | None = None
    minstep: float | None = None
    temp_c: float | None = None
    itl1: int | None = None
    itl2: int | None = None
    itl4: int | None = None
    timeout_s: float | None = None
    max_memory_mb: int | None = None
    cpu_time_s: int | None = None

    def control_lines(self) -> list[str]:
        lines = [
            f"set reltol={self.reltol:.12g}",
            f"set abstol={self.abstol:.12g}",
            f"set vntol={self.vntol:.12g}",
        ]
        if self.maxstep is not None:
            lines.append(f"set maxstep={float(self.maxstep):.12g}")
        if self.minstep is not None:
            lines.append(f"set minstep={float(self.minstep):.12g}")
        if self.temp_c is not None:
            lines.append(f"set temp={float(self.temp_c):.12g}")
        if self.itl1 is not None:
            lines.append(f"set itl1={int(self.itl1)}")
        if self.itl2 is not None:
            lines.append(f"set itl2={int(self.itl2)}")
        if self.itl4 is not None:
            lines.append(f"set itl4={int(self.itl4)}")
        return lines

    def as_dict(self) -> dict[str, float | int]:
        payload: dict[str, float | int] = {
            "reltol": self.reltol,
            "abstol": self.abstol,
            "vntol": self.vntol,
        }
        if self.maxstep is not None:
            payload["maxstep"] = float(self.maxstep)
        if self.minstep is not None:
            payload["minstep"] = float(self.minstep)
        if self.temp_c is not None:
            payload["temp_c"] = float(self.temp_c)
        if self.itl1 is not None:
            payload["itl1"] = int(self.itl1)
        if self.itl2 is not None:
            payload["itl2"] = int(self.itl2)
        if self.itl4 is not None:
            payload["itl4"] = int(self.itl4)
        if self.timeout_s is not None:
            payload["timeout_s"] = float(self.timeout_s)
        if self.max_memory_mb is not None:
            payload["max_memory_mb"] = int(self.max_memory_mb)
        if self.cpu_time_s is not None:
            payload["cpu_time_s"] = int(self.cpu_time_s)
        return payload


@dataclass(frozen=True)
class DcSweepSpec:
    source: str
    start: float
    stop: float
    step: float


@dataclass(frozen=True)
class AcSweepSpec:
    sweep: Literal["dec", "oct", "lin"] = "dec"
    points: int = 10
    start_hz: float = 1.0
    stop_hz: float = 1e6


@dataclass(frozen=True)
class SpiceResult:
    analysis: Literal["op", "dc", "ac", "tran"]
    scale: np.ndarray
    scale_unit: str
    node_voltages: dict[str, np.ndarray]
    source_currents: dict[str, np.ndarray]
    sources: tuple[SourceDescriptor, ...]
    element_currents: dict[str, np.ndarray] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def time_s(self) -> np.ndarray:
        if self.analysis != "tran":
            raise ValueError("time_s is only available for transient results")
        return self.scale


def _sanitize_identifier(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", value)
    return cleaned or "x"


def _resolve_engine(session: Session, *, cmd: str | None = None) -> tuple[str, str]:
    engine = str(
        os.getenv("SIMBENCH_SPICE_ENGINE")
        or getattr(session, "spice_engine", "ngspice")
    ).strip()
    resolved_cmd = str(
        cmd
        or os.getenv("SIMBENCH_NGSPICE_CMD")
        or getattr(session, "ngspice_cmd", "ngspice")
    )
    return engine.lower(), resolved_cmd


def ngspice_available(cmd: str = "ngspice") -> bool:
    return shutil.which(cmd) is not None


def simulate_transient(
    session: Session,
    nodes: list[str],
    *,
    sample_rate: float,
    record_length: int,
    params: dict[str, float] | None = None,
    settings: KernelSettings | None = None,
    currents: list[str] | None = None,
    cmd: str | None = None,
) -> SpiceResult:
    params = _resolve_params(session, params)
    engine, resolved_cmd = _resolve_engine(session, cmd=cmd)
    if engine not in {"auto", "ngspice"}:
        raise ValueError(f"Unknown spice engine: {engine!r}")

    ngspice_cmd = shutil.which(resolved_cmd)
    if ngspice_cmd is None:
        raise _ngspice_not_found(resolved_cmd)

    _ensure_ground(session)

    record_length = int(record_length)
    if record_length <= 0:
        raise ValueError("record_length must be positive")
    sample_rate = float(sample_rate)
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")

    dt = 1.0 / sample_rate
    tstop = dt * max(0, record_length - 1)
    _enforce_kernel_constraints(session, points=record_length, tstop=tstop)

    requested_nodes = list(nodes)
    spice_nodes = _filter_spice_nodes(session, requested_nodes)

    settings = settings or KernelSettings()

    with tempfile.TemporaryDirectory(prefix="simbench_ngspice_") as tmpdir:
        tmp_path = Path(tmpdir)
        out_path = tmp_path / "simbench_wrdata.txt"
        netlist_lines, sources, element_currents, compile_metadata = (
            _build_augmented_netlist(session)
        )
        element_keys, element_names = _element_vectors(element_currents, currents)
        vector_count = len(spice_nodes) + len(sources) + len(element_names)
        if vector_count <= 0:
            raise NgspiceRunError("No vectors requested from ngspice")
        control = _build_control_block(
            settings,
            analysis_lines=[f"tran {dt:.12g} {tstop:.12g} 0 {dt:.12g}"],
            out_path=out_path,
            vectors=_vector_list(spice_nodes, sources, element_names),
        )
        full = _assemble_netlist(netlist_lines, control, params)
        compile_metadata.update(_provenance_metadata(netlist_lines, full, params))
        _run_ngspice(
            full,
            session.circuit.root,
            ngspice_cmd,
            tmp_path,
            timeout_s=settings.timeout_s,
            max_memory_mb=settings.max_memory_mb,
            cpu_time_s=settings.cpu_time_s,
        )

        data = _load_wrdata(out_path)
        scale, series = _parse_real_wrdata(data, vector_count)

        if scale.size > 1 and np.any(np.diff(scale) < 0):
            order = np.argsort(scale)
            scale = scale[order]
            series = series[order]

        if scale.size > 1:
            unique_scale, unique_idx = np.unique(scale, return_index=True)
            scale = unique_scale
            series = series[unique_idx]

        target_time_s = np.arange(record_length, dtype=float) * dt
        if scale.size >= 2:
            resampled_cols = [
                np.interp(target_time_s, scale, series[:, idx])
                for idx in range(series.shape[1])
            ]
            series = np.column_stack(resampled_cols)
        else:
            series = np.tile(series[0, : series.shape[1]], (record_length, 1))

        node_voltages, source_currents, element_currents_out = _extract_vectors(
            spice_nodes, sources, element_keys, series
        )
        _inject_ground_node(
            node_voltages, session.wiring.ground_node, record_length, requested_nodes
        )

        metadata = {
            "engine": "ngspice",
            "cmd": ngspice_cmd,
            "settings": settings.as_dict(),
            "analysis": "tran",
            "dt": dt,
            "tstop": tstop,
        }
        metadata.update(compile_metadata)
        return SpiceResult(
            analysis="tran",
            scale=target_time_s,
            scale_unit="s",
            node_voltages=node_voltages,
            source_currents=source_currents,
            element_currents=element_currents_out,
            sources=sources,
            metadata=metadata,
        )


def simulate_op(
    session: Session,
    nodes: list[str],
    *,
    params: dict[str, float] | None = None,
    settings: KernelSettings | None = None,
    currents: list[str] | None = None,
    cmd: str | None = None,
) -> SpiceResult:
    params = _resolve_params(session, params)
    physics_result = _try_physics_model_op(session, nodes, params=params)
    if physics_result is not None:
        return physics_result

    engine, resolved_cmd = _resolve_engine(session, cmd=cmd)
    if engine not in {"auto", "ngspice"}:
        raise ValueError(f"Unknown spice engine: {engine!r}")

    ngspice_cmd = shutil.which(resolved_cmd)
    if ngspice_cmd is None:
        raise _ngspice_not_found(resolved_cmd)

    _ensure_ground(session)

    requested_nodes = list(nodes)
    _enforce_kernel_constraints(session, points=1)
    spice_nodes = _filter_spice_nodes(session, requested_nodes)
    settings = settings or KernelSettings()

    with tempfile.TemporaryDirectory(prefix="simbench_ngspice_") as tmpdir:
        tmp_path = Path(tmpdir)
        out_path = tmp_path / "simbench_wrdata.txt"
        netlist_lines, sources, element_currents, compile_metadata = (
            _build_augmented_netlist(session)
        )
        element_keys, element_names = _element_vectors(element_currents, currents)
        vector_count = len(spice_nodes) + len(sources) + len(element_names)
        if vector_count <= 0:
            raise NgspiceRunError("No vectors requested from ngspice")
        control = _build_control_block(
            settings,
            analysis_lines=["op"],
            out_path=out_path,
            vectors=_vector_list(spice_nodes, sources, element_names),
        )
        full = _assemble_netlist(netlist_lines, control, params)
        compile_metadata.update(_provenance_metadata(netlist_lines, full, params))
        _run_ngspice(
            full,
            session.circuit.root,
            ngspice_cmd,
            tmp_path,
            timeout_s=settings.timeout_s,
            max_memory_mb=settings.max_memory_mb,
            cpu_time_s=settings.cpu_time_s,
        )

        data = _load_wrdata(out_path)
        scale, series = _parse_real_wrdata(data, vector_count)

        if scale.size == 0:
            raise NgspiceRunError("ngspice produced no operating point samples")

        if series.ndim == 1:
            series = series.reshape(1, -1)

        node_voltages, source_currents, element_currents_out = _extract_vectors(
            spice_nodes, sources, element_keys, series
        )
        _inject_ground_node(
            node_voltages, session.wiring.ground_node, series.shape[0], requested_nodes
        )

        metadata = {
            "engine": "ngspice",
            "cmd": ngspice_cmd,
            "settings": settings.as_dict(),
            "analysis": "op",
        }
        metadata.update(compile_metadata)
        return SpiceResult(
            analysis="op",
            scale=scale,
            scale_unit="op_index",
            node_voltages=node_voltages,
            source_currents=source_currents,
            element_currents=element_currents_out,
            sources=sources,
            metadata=metadata,
        )


def simulate_dc_sweep(
    session: Session,
    nodes: list[str],
    sweep: DcSweepSpec,
    *,
    params: dict[str, float] | None = None,
    settings: KernelSettings | None = None,
    currents: list[str] | None = None,
    cmd: str | None = None,
) -> SpiceResult:
    params = _resolve_params(session, params)
    engine, resolved_cmd = _resolve_engine(session, cmd=cmd)
    if engine not in {"auto", "ngspice"}:
        raise ValueError(f"Unknown spice engine: {engine!r}")

    ngspice_cmd = shutil.which(resolved_cmd)
    if ngspice_cmd is None:
        raise _ngspice_not_found(resolved_cmd)

    _ensure_ground(session)

    requested_nodes = list(nodes)
    _enforce_kernel_constraints(
        session,
        points=_dc_sweep_points(sweep),
    )
    spice_nodes = _filter_spice_nodes(session, requested_nodes)
    settings = settings or KernelSettings()

    with tempfile.TemporaryDirectory(prefix="simbench_ngspice_") as tmpdir:
        tmp_path = Path(tmpdir)
        out_path = tmp_path / "simbench_wrdata.txt"
        netlist_lines, sources, element_currents, compile_metadata = (
            _build_augmented_netlist(session)
        )
        element_keys, element_names = _element_vectors(element_currents, currents)
        vector_count = len(spice_nodes) + len(sources) + len(element_names)
        if vector_count <= 0:
            raise NgspiceRunError("No vectors requested from ngspice")
        control = _build_control_block(
            settings,
            analysis_lines=[
                f"dc {sweep.source} {float(sweep.start):.12g} {float(sweep.stop):.12g} {float(sweep.step):.12g}"
            ],
            out_path=out_path,
            vectors=_vector_list(spice_nodes, sources, element_names),
        )
        full = _assemble_netlist(netlist_lines, control, params)
        compile_metadata.update(_provenance_metadata(netlist_lines, full, params))
        _run_ngspice(
            full,
            session.circuit.root,
            ngspice_cmd,
            tmp_path,
            timeout_s=settings.timeout_s,
            max_memory_mb=settings.max_memory_mb,
            cpu_time_s=settings.cpu_time_s,
        )

        data = _load_wrdata(out_path)
        scale, series = _parse_real_wrdata(data, vector_count)
        if scale.size == 0:
            raise NgspiceRunError("ngspice produced no dc sweep samples")

        node_voltages, source_currents, element_currents_out = _extract_vectors(
            spice_nodes, sources, element_keys, series
        )
        _inject_ground_node(
            node_voltages, session.wiring.ground_node, series.shape[0], requested_nodes
        )

        metadata = {
            "engine": "ngspice",
            "cmd": ngspice_cmd,
            "settings": settings.as_dict(),
            "analysis": "dc",
            "sweep": {
                "source": sweep.source,
                "start": float(sweep.start),
                "stop": float(sweep.stop),
                "step": float(sweep.step),
            },
        }
        metadata.update(compile_metadata)
        return SpiceResult(
            analysis="dc",
            scale=scale,
            scale_unit="sweep",
            node_voltages=node_voltages,
            source_currents=source_currents,
            element_currents=element_currents_out,
            sources=sources,
            metadata=metadata,
        )


def simulate_ac(
    session: Session,
    nodes: list[str],
    sweep: AcSweepSpec,
    *,
    params: dict[str, float] | None = None,
    settings: KernelSettings | None = None,
    currents: list[str] | None = None,
    cmd: str | None = None,
) -> SpiceResult:
    params = _resolve_params(session, params)
    physics_result = _try_physics_model_ac(session, nodes, sweep)
    if physics_result is not None:
        return physics_result

    engine, resolved_cmd = _resolve_engine(session, cmd=cmd)
    if engine not in {"auto", "ngspice"}:
        raise ValueError(f"Unknown spice engine: {engine!r}")

    ngspice_cmd = shutil.which(resolved_cmd)
    if ngspice_cmd is None:
        raise _ngspice_not_found(resolved_cmd)

    _ensure_ground(session)

    requested_nodes = list(nodes)
    spice_nodes = _filter_spice_nodes(session, requested_nodes)
    settings = settings or KernelSettings()

    sweep_mode = sweep.sweep.lower()
    if sweep_mode not in {"dec", "oct", "lin"}:
        raise ValueError(f"Unknown AC sweep mode: {sweep.sweep!r}")
    _enforce_kernel_constraints(
        session,
        points=_ac_sweep_points(sweep),
    )

    with tempfile.TemporaryDirectory(prefix="simbench_ngspice_") as tmpdir:
        tmp_path = Path(tmpdir)
        out_path = tmp_path / "simbench_wrdata.txt"
        netlist_lines, sources, element_currents, compile_metadata = (
            _build_augmented_netlist(session)
        )
        element_keys, element_names = _element_vectors(element_currents, currents)
        vector_count = len(spice_nodes) + len(sources) + len(element_names)
        if vector_count <= 0:
            raise NgspiceRunError("No vectors requested from ngspice")
        control = _build_control_block(
            settings,
            analysis_lines=[
                f"ac {sweep_mode} {int(sweep.points)} {float(sweep.start_hz):.12g} {float(sweep.stop_hz):.12g}"
            ],
            out_path=out_path,
            vectors=_vector_list(spice_nodes, sources, element_names),
        )
        full = _assemble_netlist(netlist_lines, control, params)
        compile_metadata.update(_provenance_metadata(netlist_lines, full, params))
        _run_ngspice(
            full,
            session.circuit.root,
            ngspice_cmd,
            tmp_path,
            timeout_s=settings.timeout_s,
            max_memory_mb=settings.max_memory_mb,
            cpu_time_s=settings.cpu_time_s,
        )

        data = _load_wrdata(out_path)
        scale, series = _parse_complex_wrdata(data, vector_count)
        if scale.size == 0:
            raise NgspiceRunError("ngspice produced no ac sweep samples")

        node_voltages, source_currents, element_currents_out = _extract_vectors(
            spice_nodes, sources, element_keys, series
        )
        _inject_ground_node(
            node_voltages, session.wiring.ground_node, series.shape[0], requested_nodes
        )

        metadata = {
            "engine": "ngspice",
            "cmd": ngspice_cmd,
            "settings": settings.as_dict(),
            "analysis": "ac",
            "sweep": {
                "mode": sweep_mode,
                "points": int(sweep.points),
                "start_hz": float(sweep.start_hz),
                "stop_hz": float(sweep.stop_hz),
            },
        }
        metadata.update(compile_metadata)
        return SpiceResult(
            analysis="ac",
            scale=scale,
            scale_unit="Hz",
            node_voltages=node_voltages,
            source_currents=source_currents,
            element_currents=element_currents_out,
            sources=sources,
            metadata=metadata,
        )


def _ensure_ground(session: Session) -> None:
    if session.wiring.ground_node != "0":
        raise SpiceEngineError(
            "ngspice requires ground node '0'. "
            f"Got wiring.ground_node={session.wiring.ground_node!r}."
        )


def _enforce_kernel_constraints(
    session: Session, *, points: int | None = None, tstop: float | None = None
) -> None:
    constraints = session.circuit.manifest.constraints
    if points is not None and points > constraints.max_points:
        raise SpiceEngineError("analysis exceeds manifest max_points constraint")
    if tstop is not None and tstop > constraints.max_tran_time_s:
        raise SpiceEngineError("analysis exceeds manifest max_tran_time_s constraint")


def _dc_sweep_points(sweep: DcSweepSpec) -> int:
    step = float(sweep.step)
    if step == 0.0:
        raise ValueError("dc sweep step must be non-zero")
    start = float(sweep.start)
    stop = float(sweep.stop)
    if (stop - start) / step < 0:
        raise ValueError("dc sweep step does not advance toward stop")
    return int(math.floor((stop - start) / step)) + 1


def _ac_sweep_points(sweep: AcSweepSpec) -> int:
    start = float(sweep.start_hz)
    stop = float(sweep.stop_hz)
    if start <= 0 or stop <= 0:
        raise ValueError("ac sweep start/stop must be positive")
    if stop < start:
        raise ValueError("ac sweep stop must be >= start")
    mode = sweep.sweep.lower()
    if mode == "lin":
        return int(sweep.points)
    if mode == "dec":
        decades = math.log10(stop / start) if stop > start else 0.0
        return int(math.ceil(decades * sweep.points)) + 1
    if mode == "oct":
        octaves = math.log2(stop / start) if stop > start else 0.0
        return int(math.ceil(octaves * sweep.points)) + 1
    raise ValueError(f"Unknown AC sweep mode: {sweep.sweep!r}")


def _filter_spice_nodes(session: Session, nodes: list[str]) -> list[str]:
    ground = session.wiring.ground_node
    return [node for node in nodes if node != ground]


def _try_physics_model_op(
    session: Session,
    nodes: list[str],
    *,
    params: dict[str, float] | None,
) -> SpiceResult | None:
    models = getattr(session, "physics_models", None) or {}
    if not models:
        return None
    node_values: dict[str, np.ndarray] = {}
    for key, model in models.items():
        vin_node, vout_node = _split_physics_key(key)
        if vout_node not in nodes:
            continue
        vin = _physics_input_value(session, vin_node, params)
        node_values[vout_node] = np.asarray(
            [model.dc_operating_point(vin)], dtype=float
        )
    if not node_values:
        return None
    _inject_ground_node(node_values, session.wiring.ground_node, 1, nodes)
    return SpiceResult(
        analysis="op",
        scale=np.asarray([0.0]),
        scale_unit="op_index",
        node_voltages=node_values,
        source_currents={},
        element_currents={},
        sources=(),
        metadata={"engine": "physics_model", "analysis": "op"},
    )


def _try_physics_model_ac(
    session: Session, nodes: list[str], sweep: AcSweepSpec
) -> SpiceResult | None:
    models = getattr(session, "physics_models", None) or {}
    if not models:
        return None
    mode = sweep.sweep.lower()
    if mode == "lin":
        freq = np.linspace(
            float(sweep.start_hz), float(sweep.stop_hz), int(sweep.points)
        )
    else:
        count = _ac_sweep_points(sweep)
        freq = np.geomspace(float(sweep.start_hz), float(sweep.stop_hz), count)
    node_values: dict[str, np.ndarray] = {}
    for key, model in models.items():
        _, vout_node = _split_physics_key(key)
        if vout_node not in nodes:
            continue
        node_values[vout_node] = np.asarray(
            model.frequency_response(freq), dtype=complex
        )
    if not node_values:
        return None
    _inject_ground_node(node_values, session.wiring.ground_node, freq.size, nodes)
    return SpiceResult(
        analysis="ac",
        scale=freq,
        scale_unit="Hz",
        node_voltages=node_values,
        source_currents={},
        element_currents={},
        sources=(),
        metadata={"engine": "physics_model", "analysis": "ac"},
    )


def _split_physics_key(key: str) -> tuple[str, str]:
    if "->" in key:
        left, right = key.split("->", 1)
    elif "→" in key:
        left, right = key.split("→", 1)
    else:
        raise ValueError(f"physics model key must be 'input->output', got {key!r}")
    return left.strip(), right.strip()


def _physics_input_value(
    session: Session,
    vin_node: str,
    params: dict[str, float] | None,
) -> float:
    if params and vin_node in params:
        return float(params[vin_node])
    inputs = getattr(session, "_physics_inputs", None)
    if isinstance(inputs, dict) and vin_node in inputs:
        return float(inputs[vin_node])
    return 1.0


def _run_ngspice(
    netlist_lines: list[str],
    root: Path,
    cmd: str,
    tmp_path: Path,
    *,
    timeout_s: float | None = None,
    max_memory_mb: int | None = None,
    cpu_time_s: int | None = None,
) -> None:
    netlist_path = tmp_path / "simbench.cir"
    log_path = tmp_path / "ngspice.log"

    netlist_path.write_text("\n".join(netlist_lines).rstrip() + "\n", encoding="utf-8")

    try:

        def _limit_resources() -> None:  # pragma: no cover - platform specific
            try:
                import resource
            except Exception:
                return
            try:
                if max_memory_mb is not None:
                    limit = int(max_memory_mb) * 1024 * 1024
                    resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
                if cpu_time_s is not None:
                    cpu_limit = int(cpu_time_s)
                    resource.setrlimit(resource.RLIMIT_CPU, (cpu_limit, cpu_limit))
            except Exception:
                return

        proc = subprocess.run(
            [cmd, "-b", "-o", str(log_path), str(netlist_path)],
            cwd=str(root),
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            preexec_fn=_limit_resources if (max_memory_mb or cpu_time_s) else None,
        )
    except subprocess.TimeoutExpired as exc:  # pragma: no cover
        raise NgspiceRunError("ngspice timed out") from exc
    except subprocess.CalledProcessError as exc:  # pragma: no cover
        details = ""
        if log_path.exists():
            details = log_path.read_text(errors="replace")
        raise NgspiceRunError(
            f"ngspice failed with exit code {exc.returncode}. {details}".strip()
        ) from exc

    # Backstop: ngspice can report convergence/topology problems (floating
    # nodes, singular matrices) on a *successful* exit. These are silently
    # discarded otherwise, so surface them as warnings — a quiet ~0 V reading
    # from a floating node is exactly the failure mode this protects against.
    log_text = log_path.read_text(errors="replace") if log_path.exists() else ""
    _warn_on_ngspice_diagnostics("\n".join((log_text, proc.stdout or "", proc.stderr or "")))


# Substrings (lower-cased) that indicate a topology/convergence problem ngspice
# may report without failing the run.
_NGSPICE_WARNING_PATTERNS = (
    "no dc path to ground",
    "singular matrix",
    "is not connected",
    "has no path to ground",
)


def _warn_on_ngspice_diagnostics(output: str) -> None:
    lowered = output.lower()
    hits = [line.strip() for line in output.splitlines()
            if any(p in line.lower() for p in _NGSPICE_WARNING_PATTERNS)]
    if not hits and not any(p in lowered for p in _NGSPICE_WARNING_PATTERNS):
        return
    detail = "; ".join(dict.fromkeys(hits)) or "see ngspice log"
    warnings.warn(
        f"ngspice reported a circuit topology/convergence problem that may make "
        f"measurements unreliable: {detail}",
        RuntimeWarning,
        stacklevel=2,
    )


def _load_wrdata(out_path: Path) -> np.ndarray:
    if not out_path.exists():  # pragma: no cover
        raise NgspiceRunError("ngspice did not produce output data file")

    data = np.loadtxt(out_path, comments="#")
    if data.ndim == 1:
        data = data.reshape(1, -1)
    if data.shape[1] < 1:
        raise NgspiceRunError("ngspice output did not contain any vectors")
    return np.asarray(data, dtype=float)


def _parse_real_wrdata(
    data: np.ndarray, vector_count: int
) -> tuple[np.ndarray, np.ndarray]:
    cols = int(data.shape[1])
    if cols == 1 + vector_count:
        scale = np.asarray(data[:, 0], dtype=float)
        series = np.asarray(data[:, 1:], dtype=float)
    elif cols >= 1 + vector_count:
        scale = np.asarray(data[:, 0], dtype=float)
        series = np.asarray(data[:, 1 : 1 + vector_count], dtype=float)
    elif cols == vector_count:
        scale = np.arange(data.shape[0], dtype=float)
        series = np.asarray(data[:, :vector_count], dtype=float)
    else:  # pragma: no cover
        raise NgspiceRunError(
            f"Unexpected ngspice wrdata column count ({cols}); expected {vector_count} vectors."
        )

    if series.shape[1] < vector_count:
        raise NgspiceRunError(
            f"ngspice output missing vectors (expected {vector_count}, got {series.shape[1]})."
        )

    finite = np.isfinite(scale)
    if not finite.all():
        scale = scale[finite]
        series = series[finite]
    return scale, series


def _parse_complex_wrdata(
    data: np.ndarray, vector_count: int
) -> tuple[np.ndarray, np.ndarray]:
    cols = int(data.shape[1])
    expected = 1 + 2 * vector_count
    if cols < expected:
        raise NgspiceRunError(
            f"Unexpected ngspice wrdata column count ({cols}); expected {expected} for complex data."
        )

    scale = np.asarray(data[:, 0], dtype=float)
    raw = np.asarray(data[:, 1 : 1 + 2 * vector_count], dtype=float)
    real = raw[:, 0::2]
    imag = raw[:, 1::2]
    series = real + 1j * imag

    finite = np.isfinite(scale)
    if not finite.all():
        scale = scale[finite]
        series = series[finite]
    return scale, series


def _vector_list(
    nodes: list[str],
    sources: tuple[SourceDescriptor, ...],
    element_names: list[str],
) -> list[str]:
    vectors = [f"v({n})" for n in nodes]
    vectors += [f"i({src.vsrc_name})" for src in sources]
    vectors += [f"i({name})" for name in element_names]
    return vectors


def _element_vectors(
    element_currents: dict[str, str],
    requested: list[str] | None,
) -> tuple[list[str], list[str]]:
    if not element_currents and not requested:
        return [], []

    keys: list[str] = []
    names: list[str] = []
    seen: set[str] = set()

    if not requested:
        for key, name in element_currents.items():
            if key in seen:
                continue
            keys.append(key)
            names.append(name)
            seen.add(key)
        return keys, names

    for item in requested:
        if item in element_currents:
            key = item
            name = element_currents[item]
        else:
            key = item
            name = item
        if key in seen:
            continue
        keys.append(key)
        names.append(name)
        seen.add(key)
    return keys, names


def _extract_vectors(
    nodes: list[str],
    sources: tuple[SourceDescriptor, ...],
    element_keys: list[str],
    series: np.ndarray,
) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray], dict[str, np.ndarray]]:
    node_voltages: dict[str, np.ndarray] = {}
    source_currents: dict[str, np.ndarray] = {}
    element_currents: dict[str, np.ndarray] = {}

    for idx, node in enumerate(nodes):
        node_voltages[node] = np.asarray(series[:, idx], dtype=series.dtype)

    for offset, desc in enumerate(sources):
        source_currents[desc.key] = np.asarray(
            series[:, len(nodes) + offset], dtype=series.dtype
        )

    base = len(nodes) + len(sources)
    for offset, key in enumerate(element_keys):
        element_currents[key] = np.asarray(series[:, base + offset], dtype=series.dtype)

    return node_voltages, source_currents, element_currents


def _inject_ground_node(
    node_voltages: dict[str, np.ndarray],
    ground: str,
    record_length: int,
    requested_nodes: list[str],
) -> None:
    if ground in requested_nodes and ground not in node_voltages:
        node_voltages[ground] = np.zeros(record_length, dtype=float)


def _build_control_block(
    settings: KernelSettings,
    analysis_lines: list[str],
    *,
    out_path: Path,
    vectors: list[str],
) -> list[str]:
    control = [
        ".control",
        "set filetype=ascii",
        "set plotwinsize=0",
        "set wr_singlescale",
        "set noaskquit",
    ]
    control += settings.control_lines()
    control += analysis_lines
    control.append(f"wrdata {out_path.as_posix()} " + " ".join(vectors))
    control += ["quit", ".endc"]
    return control


def _assemble_netlist(
    netlist_lines: list[str],
    control: list[str],
    params: dict[str, float] | None,
) -> list[str]:
    param_lines = _param_override_lines(params)
    return (
        ["* SimBench augmented netlist"]
        + netlist_lines
        + param_lines
        + control
        + [".end"]
    )


def _param_override_lines(params: dict[str, float] | None) -> list[str]:
    if not params:
        return []
    lines = []
    for key, value in sorted(params.items()):
        ident = _sanitize_identifier(key)
        lines.append(f".param {ident}={float(value):.12g}")
    return lines


def _resolve_params(
    session: Session, params: dict[str, float] | None
) -> dict[str, float]:
    resolver = getattr(session, "resolve_model_params", None)
    if callable(resolver):
        return cast(dict[str, float], resolver(params))
    return dict(params or {})


def _hash_lines(lines: list[str]) -> str:
    return hashlib.sha256(("\n".join(lines) + "\n").encode("utf-8")).hexdigest()


def _param_hash(params: dict[str, float] | None) -> str:
    payload = {str(k): float(v) for k, v in sorted((params or {}).items())}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _provenance_metadata(
    base_lines: list[str], full_lines: list[str], params: dict[str, float] | None
) -> dict[str, Any]:
    return {
        "base_netlist_hash": _hash_lines(base_lines),
        "rendered_netlist_hash": _hash_lines(full_lines),
        "parameter_hash": _param_hash(params),
        "model_params": {str(k): float(v) for k, v in sorted((params or {}).items())},
    }


def _build_augmented_netlist(
    session: Session,
) -> tuple[list[str], tuple[SourceDescriptor, ...], dict[str, str], dict[str, Any]]:
    allowed_includes = set(session.circuit.manifest.allowed_includes)
    constraints = session.circuit.manifest.constraints
    expanded = expand_includes(
        session.circuit.canonicalize(),
        root=session.circuit.root,
        allowed_includes=allowed_includes,
        max_depth=constraints.max_include_depth,
        max_files=constraints.max_include_files,
        max_file_bytes=constraints.max_file_bytes,
    )
    mutation = apply_variations_and_faults(
        expanded.text,
        getattr(session, "variations", None),
    )
    base_lines = _clean_netlist_lines(
        mutation.text,
        root=session.circuit.root,
        allowed_includes=allowed_includes,
    )

    from .injectors import AwgInjector
    from .injectors import DmmInjector
    from .injectors import InjectionResult
    from .injectors import ProbeInjector
    from .injectors import PsuInjector

    injection_result = InjectionResult()
    for injector in (AwgInjector(), PsuInjector(), DmmInjector(), ProbeInjector()):
        injection_result.extend(injector.inject(session))

    # Plugin-defined instrument injections.
    for inst_id, inst in session.bench.instruments.items():
        if inst.kind in {"PSU", "AWG", "DMM", "SCOPE"}:
            continue
        plugin = get_plugin(inst.kind)
        if plugin is None:
            continue
        injection = plugin.inject(session, inst_id, inst)
        injection_result.netlist_lines.extend(injection.netlist_lines)
        injection_result.sources.extend(injection.sources)
        injection_result.element_currents.update(injection.element_currents)

    full = base_lines + injection_result.netlist_lines
    netlist_hash = hashlib.sha256("\n".join(full).encode()).hexdigest()
    compile_metadata = {
        "compiled_netlist_hash": f"sha256:{netlist_hash}",
        "variation_metadata": mutation.metadata,
        "include_files": expanded.include_files,
    }

    return (
        full,
        tuple(injection_result.sources),
        injection_result.element_currents,
        compile_metadata,
    )


def _resolve_probe_terminal(key: str, *, terminals: set[str]) -> str | None:
    if key in terminals:
        return key
    for suffix in (".HI", ".LO"):
        candidate = f"{key}{suffix}"
        if candidate in terminals:
            return candidate
    return None


def _clean_netlist_lines(
    text: str, *, root: Path, allowed_includes: set[str]
) -> list[str]:
    lines: list[str] = []
    in_control = False
    first_statement = True
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue

        if first_statement:
            first_statement = False
            continue

        lower = stripped.lower()
        if in_control:
            if lower.startswith(".endc"):
                in_control = False
            continue

        if lower.startswith(".control"):
            in_control = True
            continue

        if lower.startswith(".end"):
            continue

        # Strip analysis directives; SimBench owns the analysis setup.
        if lower.startswith(
            (".op", ".tran", ".ac", ".dc", ".tf", ".noise", ".pz", ".step")
        ):
            continue

        include_match = re.match(
            r"^\s*\.(?:inc|include)\s+(.+)$", raw, flags=re.IGNORECASE
        )
        if include_match:
            token = include_match.group(1).strip().strip('"').strip("'")
            if token not in allowed_includes:
                raise SpiceEngineError(
                    f"Netlist includes {token!r} but it is not listed in manifest.allowed_includes"
                )
            inc_path = (root / token).resolve()
            lines.append(f'.include "{inc_path}"')
            continue

        lines.append(raw.rstrip())
    return lines


def _awg_source_spec(awg: Any) -> str:
    """Convert an AWG twin state into a SPICE source specification."""

    waveform = str(getattr(awg.state, "waveform", "sine")).lower()
    freq = float(getattr(awg.state, "frequency_hz", 1e3))
    vpp = float(getattr(awg.state, "amplitude_vpp", 1.0))
    unit = str(getattr(awg.state, "voltage_unit", "VPP")).upper()
    offset = float(getattr(awg.state, "offset_v", 0.0))
    phase = float(getattr(awg.state, "phase_deg", 0.0)) % 360.0
    duty = float(getattr(awg.state, "duty_cycle", 0.5))
    burst_enabled = bool(getattr(awg.state, "burst_enabled", False))
    burst_count = int(getattr(awg.state, "burst_count", 1))

    if unit == "VRMS":
        vpp = vpp * 2.0 * math.sqrt(2.0)

    if waveform in {"dc"} or freq <= 0:
        return f"DC {offset:.12g}"

    amp = vpp / 2.0
    per = 1.0 / max(freq, 1e-12)
    delay = (phase / 360.0) * per

    if waveform in {"sine", "sin"}:
        return f"SIN({offset:.12g} {amp:.12g} {freq:.12g} 0 0 {phase:.12g})"

    if waveform in {"square", "squ", "pulse"}:
        v1 = offset - amp
        v2 = offset + amp
        edge = min(1e-6, per / 100.0)
        pw = max(edge, per * duty)
        if burst_enabled and burst_count > 0:
            return (
                f"PULSE({v1:.12g} {v2:.12g} {delay:.12g} {edge:.12g} "
                f"{edge:.12g} {pw:.12g} {per:.12g} {burst_count})"
            )
        return f"PULSE({v1:.12g} {v2:.12g} {delay:.12g} {edge:.12g} {edge:.12g} {pw:.12g} {per:.12g})"

    if waveform in {"triangle", "tri", "ramp"}:
        v1 = offset - amp
        v2 = offset + amp
        edge = per / 2.0
        if burst_enabled and burst_count > 0:
            return (
                f"PULSE({v1:.12g} {v2:.12g} {delay:.12g} {edge:.12g} "
                f"{edge:.12g} 0 {per:.12g} {burst_count})"
            )
        return f"PULSE({v1:.12g} {v2:.12g} {delay:.12g} {edge:.12g} {edge:.12g} 0 {per:.12g})"

    # Fallback: treat as DC at offset.
    return f"DC {offset:.12g}"
