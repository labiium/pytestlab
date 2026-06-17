"""Factory and generator helpers to simplify SimBench setup."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path

import yaml

from .bench import AWG
from .bench import DMM
from .bench import PSU
from .bench import BenchConfig
from .bench import PSUChannel
from .bench import Scope
from .circuit_package import CircuitPackage
from .circuit_package import Manifest
from .circuit_package import ManifestConstraints
from .circuit_package import ManifestMetadata
from .session import Session
from .variations import VariationConfig
from .wiring import Connection
from .wiring import ProbeModel
from .wiring import WiringConfig
from .wiring import WiringRules


def manifest_from_netlist(
    netlist_path: Path,
    *,
    metadata: ManifestMetadata | dict[str, object],
    allowed_includes: Sequence[str] | None = None,
    constraints: ManifestConstraints | None = None,
    write_manifest: bool = False,
) -> Manifest:
    """Generate a :class:`Manifest` from a raw netlist on disk.

    This helper computes the content hash for ``netlist_path`` and returns a
    fully populated ``Manifest``. When ``write_manifest`` is ``True`` the
    manifest is also written alongside the netlist for later reuse.
    """

    allowed_includes = list(allowed_includes or [])
    metadata_obj = (
        metadata if isinstance(metadata, ManifestMetadata) else ManifestMetadata(**metadata)
    )
    constraints_obj = constraints or ManifestConstraints()

    digest = hashlib.sha256(netlist_path.read_bytes()).hexdigest()
    manifest = Manifest(
        entry_netlist=netlist_path.name,
        allowed_includes=allowed_includes,
        metadata=metadata_obj,
        constraints=constraints_obj,
        hashes={netlist_path.name: f"sha256:{digest}"},
    )

    if write_manifest:
        manifest_path = netlist_path.with_name("manifest.json")
        manifest_path.write_text(manifest.model_dump_json(indent=2))

    return manifest


def circuit_from_netlist(
    netlist_path: Path,
    *,
    metadata: ManifestMetadata | dict[str, object],
    allowed_includes: Sequence[str] | None = None,
    constraints: ManifestConstraints | None = None,
    write_manifest: bool = False,
) -> CircuitPackage:
    """Build a :class:`CircuitPackage` without hand-writing a manifest."""

    manifest = manifest_from_netlist(
        netlist_path,
        metadata=metadata,
        allowed_includes=allowed_includes,
        constraints=constraints,
        write_manifest=write_manifest,
    )
    return CircuitPackage(root=netlist_path.parent, manifest=manifest)


def default_bench(
    bench_id: str = "simbench-demo",
    *,
    psu_channels: int = 1,
    add_awg: bool = True,
    add_dmm: bool = True,
    scope_channels: int = 2,
) -> BenchConfig:
    """Create a :class:`BenchConfig` with typical instrument defaults."""

    instruments: dict[str, object] = {}

    if psu_channels:
        channels = [
            PSUChannel(name=f"CH{i + 1}", v_max=30.0, i_max=3.0) for i in range(psu_channels)
        ]
        instruments["psu1"] = PSU(channels=channels)

    if add_awg:
        instruments["awg1"] = AWG(vpp_max=10.0)

    if add_dmm:
        instruments["dmm1"] = DMM()

    if scope_channels:
        instruments["scope1"] = Scope(channels=scope_channels)

    return BenchConfig(bench_id=bench_id, instruments=instruments)


def basic_measurement_wiring(
    *,
    bench: BenchConfig,
    source_node: str = "vin",
    return_node: str = "0",
    sense_node: str = "vout",
    ground_node: str = "0",
    probe_rin_ohm: float | None = 10e6,
    rules: WiringRules | None = None,
) -> WiringConfig:
    """Wire common instruments for source/sense measurements."""

    if rules is None:
        rules = WiringRules()
        if "awg1" in bench.instruments and "psu1" in bench.instruments:
            rules.allow_output_sharing = True

    connections: list[Connection] = []

    if "awg1" in bench.instruments:
        connections.append(Connection(from_="awg1.HI", to=source_node))
        connections.append(Connection(from_="awg1.LO", to=return_node))

    if "psu1" in bench.instruments:
        first_channel = bench.instruments["psu1"].channels[0].name
        connections.append(Connection(from_=f"psu1.{first_channel}.HI", to=source_node))
        connections.append(Connection(from_=f"psu1.{first_channel}.LO", to=return_node))

    if "dmm1" in bench.instruments:
        connections.append(Connection(from_="dmm1.V.HI", to=sense_node))
        connections.append(Connection(from_="dmm1.V.LO", to=ground_node))

    if "scope1" in bench.instruments:
        connections.append(Connection(from_="scope1.CH1.HI", to=sense_node))
        connections.append(Connection(from_="scope1.CH1.LO", to=ground_node))

    probe_models = {"scope1.CH1.HI": ProbeModel(rin_ohm=probe_rin_ohm)} if probe_rin_ohm else {}

    return WiringConfig(
        ground_node=ground_node,
        connections=connections,
        probe_models=probe_models,
        rules=rules,
    )


def session_from_files(
    *,
    netlist_path: Path,
    bench_path: Path,
    wiring_path: Path,
    seed: int = 1337,
    variations_path: Path | None = None,
) -> Session:
    """Create a :class:`Session` from disk-backed assets."""

    bench = BenchConfig.model_validate(yaml.safe_load(bench_path.read_text()))
    wiring = WiringConfig.model_validate(yaml.safe_load(wiring_path.read_text()))
    circuit = CircuitPackage.from_path(netlist_path)
    variations = None
    if variations_path is not None and variations_path.exists():
        variations = VariationConfig.model_validate(yaml.safe_load(variations_path.read_text()))
    return Session(
        circuit=circuit,
        bench=bench,
        wiring=wiring,
        seed=seed,
        variations=variations,
    )


def session_from_configs(
    *,
    circuit: CircuitPackage,
    bench: BenchConfig,
    wiring: WiringConfig,
    seed: int = 1337,
    variations: VariationConfig | None = None,
) -> Session:
    """Instantiate a :class:`Session` from in-memory configs."""

    return Session(
        circuit=circuit,
        bench=bench,
        wiring=wiring,
        seed=seed,
        variations=variations,
    )
