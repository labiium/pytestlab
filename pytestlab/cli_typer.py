# pytestlab/cli.py
from __future__ import annotations

import code
import contextlib
import difflib
import importlib.util
import inspect
import json
import math
import os
import re
import shutil
import sys
import time
import types
from collections.abc import Mapping
from importlib import metadata
from pathlib import Path
from typing import Annotated
from typing import Any
from typing import cast

import httpx
import rich
import typer
import yaml
from rich.console import Console
from rich.highlighter import JSONHighlighter
from rich.markup import escape as rich_escape
from rich.syntax import Syntax
from rich.table import Table

from ._lamb_url import resolve_lamb_url
from .cli_prober import prober_app
from .errors import InstrumentCommunicationError
from .errors import InstrumentConfigurationError
from .errors import InstrumentConnectionError
from .errors import OperationDiscoveryError

_CAPABILITY_ERRORS = (
    TypeError,
    ValueError,
    RuntimeError,
    InstrumentCommunicationError,
    InstrumentConfigurationError,
    InstrumentConnectionError,
)


def _get_version() -> str:
    try:
        return metadata.version("pytestlab")
    except metadata.PackageNotFoundError:
        try:
            from pytestlab import __version__ as fallback_version

            return fallback_version
        except Exception:
            return "unknown"
    except Exception:
        return "unknown"


def version_callback(value: bool):
    if value:
        rich.print(f"PyTestLab version {_get_version()}")
        raise typer.Exit()


app = typer.Typer(help="PyTestLab: Scientific test & measurement toolbox CLI.")


def resolve_bench_path(explicit: Path | None = None) -> Path:
    """Resolve a bench path from the CLI option, environment, or cwd ancestry."""

    if explicit is not None:
        candidates = [explicit.expanduser()]
    elif os.environ.get("PYTESTLAB_BENCH"):
        candidates = [Path(os.environ["PYTESTLAB_BENCH"]).expanduser()]
    else:
        candidates = []
        directory = Path.cwd()
        while True:
            matches = [
                directory / name
                for name in ("bench.yaml", "bench.yml")
                if (directory / name).is_file()
            ]
            if len(matches) > 1:
                raise ValueError(
                    f"Ambiguous bench configuration in '{directory}': "
                    + ", ".join(str(path) for path in matches)
                )
            if matches:
                candidates = matches
                break
            if directory.parent == directory:
                break
            directory = directory.parent

    path = candidates[0] if candidates else None
    if path is None:
        raise FileNotFoundError(
            "No bench configuration found. Pass --bench PATH, set PYTESTLAB_BENCH, "
            "or place bench.yaml/bench.yml in the current directory or an ancestor."
        )
    if not path.is_file():
        source = "--bench" if explicit is not None else "PYTESTLAB_BENCH"
        raise FileNotFoundError(f"Bench configuration from {source} was not found: '{path}'")
    return path.resolve()


def _bench_option() -> Any:
    return typer.Option("--bench", help="Bench configuration path (or use PYTESTLAB_BENCH).")


def _open_cli_bench(
    bench_path: Path | None,
    *,
    aliases: set[str] | None = None,
    cameras_only: bool = False,
    camera_alias: str | None = None,
):
    from pytestlab.bench import Bench

    try:
        resolved = resolve_bench_path(bench_path)
        if cameras_only:
            from pytestlab.camera import Camera
            from pytestlab.config.bench_loader import load_bench_yaml
            from pytestlab.devices import AutoDevice

            config = load_bench_yaml(resolved)
            unavailable: list[str] = []
            if camera_alias is not None:
                entry = config.devices.get(camera_alias)
                if entry is None:
                    raise ValueError(f"No camera device named '{camera_alias}' in the bench.")
                model, data = Bench._load_entry_profile(entry, resolved.parent)
                driver = AutoDevice._resolve_driver(model, data, entry.source)
                if not issubclass(driver, Camera):
                    raise TypeError(
                        f"Bench resource '{camera_alias}' does not provide a Camera capability."
                    )
                aliases = {camera_alias}

            if aliases is None:
                aliases = set()
                for alias, entry in config.devices.items():
                    try:
                        model, data = Bench._load_entry_profile(entry, resolved.parent)
                        driver = AutoDevice._resolve_driver(model, data, entry.source)
                    except (OSError, *_CAPABILITY_ERRORS):
                        unavailable.append(alias)
                        continue
                    if issubclass(driver, Camera):
                        aliases.add(alias)
            if not aliases:
                message = "Bench contains no Camera capabilities."
                if unavailable:
                    message = (
                        "Bench contains no Camera capabilities; unavailable profiles: "
                        + ", ".join(unavailable)
                    )
                raise ValueError(message)
        return Bench.open(resolved, aliases=aliases, start_experiment=False)
    except (OSError, *_CAPABILITY_ERRORS) as exc:
        rich.print(f"[bold red]Error: {rich_escape(str(exc))}[/bold red]")
        raise typer.Exit(code=1) from None


def _close_cli_bench(bench: Any) -> None:
    close = getattr(bench, "close_all", None)
    if callable(close):
        close()


camera_app = typer.Typer(name="camera", help="Use generic camera capabilities.")
app.add_typer(camera_app)


def _camera_resources(bench: Any) -> dict[str, Any]:
    """Return resources that expose the generic camera capability."""

    from pytestlab.camera import Camera

    resources = getattr(bench, "resources", None)
    if not isinstance(resources, Mapping):
        resources = getattr(bench, "devices", {})
    return {
        str(alias): resource
        for alias, resource in resources.items()
        if isinstance(resource, Camera)
        or all(
            callable(getattr(resource, name, None))
            for name in ("capture", "capture_many", "get_capabilities")
        )
    }


def _camera_resource(bench: Any, alias: str | None) -> tuple[str, Any]:
    cameras = _camera_resources(bench)
    if alias is not None:
        try:
            return alias, cameras[alias]
        except KeyError:
            if cameras:
                available = ", ".join(sorted(cameras))
                raise TypeError(
                    f"No camera capability named '{alias}' (available: {available})."
                ) from None
            raise TypeError(
                f"Bench resource '{alias}' does not provide a Camera capability."
            ) from None
    if len(cameras) == 1:
        return next(iter(cameras.items()))
    if not cameras:
        raise TypeError("Bench contains no Camera capabilities.")
    raise TypeError(
        "More than one camera is available; pass the camera alias: " + ", ".join(sorted(cameras))
    )


def _camera_output_paths(
    output: Path | None,
    *,
    alias: str,
    count: int,
) -> list[Path]:
    """Resolve concise CLI output into stable, non-overwriting paths."""

    if output is None:
        root = Path(os.getenv("PYTESTLAB_CAPTURE_DIR", "/tmp/pytestlab-captures"))
        stamp = f"capture-{time.time_ns()}"
        output = root / alias / stamp
    if not output.suffix:
        output.mkdir(parents=True, exist_ok=True)
        return [output / f"capture-{index:06d}.png" for index in range(1, count + 1)]
    if count == 1:
        return [output]
    return [
        output.with_name(f"{output.stem}_{index:03d}{output.suffix}")
        for index in range(1, count + 1)
    ]


@camera_app.command("capture")
def camera_capture(
    alias: Annotated[str, typer.Argument(help="Camera alias in the bench.")],
    output: Annotated[
        Path | None,
        typer.Argument(help="Image path or output directory; defaults under /tmp."),
    ] = None,
    count: Annotated[int, typer.Option("--count", min=1, help="Number of frames to capture.")] = 1,
    interval: Annotated[
        float, typer.Option("--interval", min=0, help="Seconds between frames.")
    ] = 0.0,
    metadata: Annotated[
        bool,
        typer.Option("--metadata/--no-metadata", help="Write one JSON sidecar per frame."),
    ] = True,
    as_json: Annotated[bool, typer.Option("--json", help="Emit machine-readable output.")] = False,
    bench_path: Annotated[Path | None, _bench_option()] = None,
):
    """Capture one or more frames from an explicitly named bench camera."""
    bench = _open_cli_bench(bench_path, cameras_only=True, camera_alias=alias)
    try:
        camera_alias, resource = _camera_resource(bench, alias)
        destinations = _camera_output_paths(output, alias=camera_alias, count=count)
        results = resource.capture_many(
            destinations,
            interval_s=interval,
            metadata=metadata,
        )
        paths = [result.path for result in results]
        metadata_paths = [
            result.metadata_path for result in results if result.metadata_path is not None
        ]
        payload = {
            "alias": camera_alias,
            "count": count,
            "paths": [str(path) for path in paths],
            "metadata": [str(path) for path in metadata_paths],
        }
        if as_json:
            typer.echo(json.dumps(payload, sort_keys=True))
        elif count == 1:
            rich.print(f"Captured [green]{paths[0]}[/green]")
        else:
            rich.print(f"Captured {count} frames to [green]{paths[0].parent}[/green]")
    except (OSError, httpx.HTTPError, *_CAPABILITY_ERRORS) as exc:
        rich.print(f"[bold red]Error: {rich_escape(str(exc))}[/bold red]")
        raise typer.Exit(code=1) from None
    finally:
        _close_cli_bench(bench)


@camera_app.command("discover")
def camera_discover(
    url: Annotated[
        str | None,
        typer.Option(help="LAMB server URL; defaults to LAMB_SERVER or http://lamb-server:8000."),
    ] = None,
    as_json: Annotated[
        bool, typer.Option("--json", help="Emit machine-readable camera resource strings.")
    ] = False,
    timeout_ms: Annotated[
        int, typer.Option(help="Discovery request timeout in milliseconds.")
    ] = 5000,
):
    """Discover connected LAMB cameras without a bench file or opening a camera."""
    url = resolve_lamb_url(url)
    try:
        if timeout_ms <= 0:
            raise ValueError("--timeout-ms must be positive.")
        if not url.startswith(("http://", "https://")):
            raise ValueError("--url must be an HTTP(S) LAMB server URL.")
        with httpx.Client(timeout=timeout_ms / 1000) as client:
            response = client.get(f"{url.rstrip('/')}/webcams")
            response.raise_for_status()
            payload = response.json()
        devices = payload.get("devices") if isinstance(payload, dict) else None
        if not isinstance(devices, list) or any(
            not isinstance(device, dict)
            or not isinstance(device.get("resource_string"), str)
            or not device["resource_string"]
            for device in devices
        ):
            raise ValueError(
                "LAMB camera discovery must return devices with nonempty resource strings."
            )
        if as_json:
            typer.echo(json.dumps(devices, sort_keys=True))
        elif not devices:
            typer.echo("No cameras found on the LAMB server.")
        else:
            table = Table(title="LAMB cameras")
            table.add_column("Resource string", overflow="fold")
            table.add_column("Label")
            for device in devices:
                table.add_row(
                    rich_escape(device["resource_string"]),
                    rich_escape(str(device.get("label", ""))),
                )
            rich.print(table)
    except (httpx.HTTPError, ValueError) as exc:
        rich.print(f"[bold red]Error: {rich_escape(str(exc))}[/bold red]")
        raise typer.Exit(code=1) from None


@camera_app.command("list")
def camera_list(
    as_json: Annotated[bool, typer.Option("--json", help="Emit machine-readable output.")] = False,
    bench_path: Annotated[Path | None, _bench_option()] = None,
):
    """List Camera capabilities declared by a bench."""

    bench = _open_cli_bench(bench_path, cameras_only=True)
    try:
        rows: list[dict[str, Any]] = []
        for alias, resource in sorted(_camera_resources(bench).items()):
            capabilities = resource.get_capabilities()
            rows.append(
                {
                    "alias": alias,
                    "formats": list(capabilities.formats),
                    "supports_trigger": capabilities.supports_trigger,
                    "supports_stream": capabilities.supports_stream,
                    "max_width": capabilities.max_width,
                    "max_height": capabilities.max_height,
                }
            )
        if as_json:
            typer.echo(json.dumps(rows, sort_keys=True))
            return
        if not rows:
            rich.print("No Camera capabilities found.")
            return
        table = Table(title="Camera capabilities")
        table.add_column("Alias", style="cyan")
        table.add_column("Formats", style="green")
        table.add_column("Trigger", style="yellow")
        table.add_column("Stream", style="yellow")
        for row in rows:
            table.add_row(
                row["alias"],
                ", ".join(row["formats"]),
                str(row["supports_trigger"]),
                str(row["supports_stream"]),
            )
        rich.print(table)
    except (TypeError, ValueError) as exc:
        rich.print(f"[bold red]Error: {exc}[/bold red]")
        raise typer.Exit(code=1) from None
    finally:
        _close_cli_bench(bench)


@camera_app.command("info")
def camera_info(
    alias: Annotated[
        str | None,
        typer.Argument(help="Camera alias; omit when the bench configures only one camera alias."),
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Emit machine-readable output.")] = False,
    bench_path: Annotated[Path | None, _bench_option()] = None,
):
    """Show one Camera capability declaration."""

    bench = _open_cli_bench(bench_path, cameras_only=True, camera_alias=alias)
    try:
        camera_alias, resource = _camera_resource(bench, alias)
        capabilities = resource.get_capabilities()
        payload = {
            "alias": camera_alias,
            "formats": list(capabilities.formats),
            "supports_trigger": capabilities.supports_trigger,
            "supports_stream": capabilities.supports_stream,
            "max_width": capabilities.max_width,
            "max_height": capabilities.max_height,
        }
        if as_json:
            typer.echo(json.dumps(payload, sort_keys=True))
        else:
            rich.print(payload)
    except (TypeError, ValueError) as exc:
        rich.print(f"[bold red]Error: {exc}[/bold red]")
        raise typer.Exit(code=1) from None
    finally:
        _close_cli_bench(bench)


motion_app = typer.Typer(name="motion", help="Use motion capabilities by bench alias.")
app.add_typer(motion_app)


def _parse_motion_position(values: list[str]) -> dict[str, float]:
    if len(values) == 1 and values[0].lstrip().startswith("{"):
        payload = json.loads(values[0])
        if not isinstance(payload, dict):
            raise ValueError("motion position JSON must be an object")
        return {str(axis): float(value) for axis, value in payload.items()}
    position: dict[str, float] = {}
    for value in values:
        if "=" not in value:
            raise ValueError("motion coordinates must use axis=value (or one JSON object)")
        axis, number = value.split("=", 1)
        if not axis:
            raise ValueError("motion axis names cannot be empty")
        position[axis] = float(number)
    return position


motion_error = "Bench resource '{alias}' does not provide a MotionDevice capability."


def _motion_resource(bench: Any, alias: str):
    from pytestlab.motion import MotionDevice

    resource = bench.devices.get(alias)
    if not isinstance(resource, MotionDevice) and not all(
        callable(getattr(resource, name, None))
        for name in ("move_absolute", "move_relative", "get_position", "get_status")
    ):
        raise TypeError(motion_error.format(alias=alias))
    return resource


def _motion_result_payload(result: Any) -> dict[str, Any]:
    state = getattr(result, "state", None)
    state_value = getattr(state, "value", state)
    return {
        "operation_id": result.operation_id,
        "operation": result.operation,
        "state": state_value,
        "requested": result.requested,
        "actual": result.actual,
        "frame": result.frame,
        "units": result.units,
        "error": result.error,
        "details": result.details,
    }


def _report_motion_result(result: Any, *, as_json: bool = False, alias: str | None = None) -> None:
    payload = _motion_result_payload(result)
    state = payload["state"]
    if as_json:
        typer.echo(json.dumps(payload, sort_keys=True, default=str))
    else:
        label, color = {
            "succeeded": ("Completed", "green"),
            "queued": ("Queued", "yellow"),
            "running": ("Running", "yellow"),
            "cancelled": ("Cancelled", "yellow"),
            "failed": ("Failed", "red"),
            "faulted": ("Faulted", "red"),
        }.get(state, ("Unconfirmed", "yellow"))
        resource = f"{rich_escape(alias)}: " if alias is not None else ""
        operation = rich_escape(str(payload["operation"]))
        operation_id = rich_escape(str(payload["operation_id"]))
        rich.print(f"{resource}[{color}]{label}[/{color}] {operation} ({operation_id})")
    if state in {"failed", "faulted"}:
        raise RuntimeError(str(payload["error"] or "motion_operation_failed"))


def _report_motion_error(exc: Exception) -> None:
    Console(stderr=True).print(f"[bold red]Error: {rich_escape(str(exc))}[/bold red]")


@motion_app.command("move")
@app.command("move", hidden=True)
def move_command(
    alias: Annotated[str, typer.Argument(help="Motion resource alias in the bench.")],
    coordinates: Annotated[list[str], typer.Argument(help="axis=value pairs or a JSON object.")],
    relative: Annotated[
        bool, typer.Option("--relative", help="Move by offsets instead of absolute coordinates.")
    ] = False,
    frame: Annotated[str, typer.Option("--frame")] = "machine",
    units: Annotated[str, typer.Option("--units")] = "mm",
    wait: Annotated[bool, typer.Option("--wait")] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Emit machine-readable output.")] = False,
    bench_path: Annotated[Path | None, _bench_option()] = None,
):
    """Move a MotionDevice using its generic absolute or relative operation."""
    bench = _open_cli_bench(bench_path, aliases={alias})
    try:
        resource = _motion_resource(bench, alias)
        position = _parse_motion_position(coordinates)
        operation = resource.move_relative if relative else resource.move_absolute
        result = operation(position, frame=frame, units=units, wait=wait)
        _report_motion_result(result, as_json=as_json, alias=alias)
    except _CAPABILITY_ERRORS as exc:
        _report_motion_error(exc)
        raise typer.Exit(code=1) from None
    finally:
        _close_cli_bench(bench)


@app.command("home", hidden=True)
def home_command(
    alias: Annotated[str, typer.Argument(help="Motion resource alias in the bench.")],
    axes: Annotated[list[str] | None, typer.Argument(help="Optional axes to home.")] = None,
    wait: Annotated[bool, typer.Option("--wait")] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Emit machine-readable output.")] = False,
    bench_path: Annotated[Path | None, _bench_option()] = None,
):
    """Home all or selected axes through a MotionDevice capability."""
    bench = _open_cli_bench(bench_path, aliases={alias})
    try:
        result = _motion_resource(bench, alias).home(axes or None, wait=wait)
        _report_motion_result(result, as_json=as_json)
    except _CAPABILITY_ERRORS as exc:
        rich.print(f"[bold red]Error: {exc}[/bold red]")
        raise typer.Exit(code=1) from None
    finally:
        _close_cli_bench(bench)


@app.command("set-home", hidden=True)
def set_home_command(
    alias: Annotated[str, typer.Argument(help="Motion resource alias in the bench.")],
    axes: Annotated[
        list[str] | None, typer.Argument(help="Optional axes to set as the home origin.")
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Emit machine-readable output.")] = False,
    bench_path: Annotated[Path | None, _bench_option()] = None,
):
    """Set the controller's saved home origin for all or selected axes."""
    bench = _open_cli_bench(bench_path, aliases={alias})
    try:
        resource = _motion_resource(bench, alias)
        set_home = getattr(resource, "set_home", None)
        if not callable(set_home):
            raise TypeError(motion_error.format(alias=alias))
        result = set_home(axes=axes or None)
        _report_motion_result(result, as_json=as_json)
    except _CAPABILITY_ERRORS as exc:
        rich.print(f"[bold red]Error: {exc}[/bold red]")
        raise typer.Exit(code=1) from None
    finally:
        _close_cli_bench(bench)


@app.command("move-home", hidden=True)
def move_home_command(
    alias: Annotated[str, typer.Argument(help="Motion resource alias in the bench.")],
    axes: Annotated[
        list[str] | None, typer.Argument(help="Optional axes to move to saved home.")
    ] = None,
    wait: Annotated[bool, typer.Option("--wait")] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Emit machine-readable output.")] = False,
    bench_path: Annotated[Path | None, _bench_option()] = None,
):
    """Move all or selected axes to the controller's saved home origin."""
    bench = _open_cli_bench(bench_path, aliases={alias})
    try:
        resource = _motion_resource(bench, alias)
        move_home = getattr(resource, "move_home", None)
        if not callable(move_home):
            raise TypeError(motion_error.format(alias=alias))
        result = move_home(axes=axes or None, wait=wait)
        _report_motion_result(result, as_json=as_json)
    except _CAPABILITY_ERRORS as exc:
        rich.print(f"[bold red]Error: {exc}[/bold red]")
        raise typer.Exit(code=1) from None
    finally:
        _close_cli_bench(bench)


@app.command("rotate", hidden=True)
def rotate_command(
    alias: Annotated[str, typer.Argument(help="Motion resource alias in the bench.")],
    theta_deg: Annotated[float, typer.Argument(help="Absolute chuck angle in degrees.")],
    wait: Annotated[bool, typer.Option("--wait")] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Emit machine-readable output.")] = False,
    bench_path: Annotated[Path | None, _bench_option()] = None,
):
    """Rotate a typed rotary chuck axis without opening a raw instrument channel."""
    bench = _open_cli_bench(bench_path, aliases={alias})
    try:
        resource = _motion_resource(bench, alias)
        rotate = getattr(resource, "rotate_absolute", None)
        if not callable(rotate):
            raise TypeError(motion_error.format(alias=alias))
        result = rotate(theta_deg, wait=wait)
        _report_motion_result(result, as_json=as_json)
    except _CAPABILITY_ERRORS as exc:
        rich.print(f"[bold red]Error: {exc}[/bold red]")
        raise typer.Exit(code=1) from None
    finally:
        _close_cli_bench(bench)


@motion_app.command("position")
@app.command("position", hidden=True)
def position_command(
    alias: Annotated[str, typer.Argument(help="Motion resource alias in the bench.")],
    frame: Annotated[str, typer.Option("--frame")] = "machine",
    units: Annotated[str, typer.Option("--units")] = "mm",
    as_json: Annotated[bool, typer.Option("--json", help="Emit machine-readable output.")] = False,
    bench_path: Annotated[Path | None, _bench_option()] = None,
):
    """Read the current position through a MotionDevice capability."""
    bench = _open_cli_bench(bench_path, aliases={alias})
    try:
        value = _motion_resource(bench, alias).get_position(frame=frame, units=units)
        if as_json:
            typer.echo(json.dumps(value, sort_keys=True))
        else:
            coordinates = ", ".join(f"{axis}={number:g}" for axis, number in sorted(value.items()))
            rich.print(
                f"[cyan]{rich_escape(alias)}[/cyan] "
                f"({rich_escape(frame)}, {rich_escape(units)}): {rich_escape(coordinates)}"
            )
    except _CAPABILITY_ERRORS as exc:
        _report_motion_error(exc)
        raise typer.Exit(code=1) from None
    finally:
        _close_cli_bench(bench)


@app.command("stop", hidden=True)
def stop_command(
    alias: Annotated[str, typer.Argument(help="Motion resource alias in the bench.")],
    mode: Annotated[
        str,
        typer.Option("--mode", help="Stop semantics: controlled, quick, or abort."),
    ] = "controlled",
    as_json: Annotated[bool, typer.Option("--json", help="Emit machine-readable output.")] = False,
    bench_path: Annotated[Path | None, _bench_option()] = None,
):
    """Stop a MotionDevice through its generic controller stop operation."""
    bench = _open_cli_bench(bench_path, aliases={alias})
    try:
        result = _motion_resource(bench, alias).stop(mode)
        _report_motion_result(result, as_json=as_json)
    except _CAPABILITY_ERRORS as exc:
        rich.print(f"[bold red]Error: {exc}[/bold red]")
        raise typer.Exit(code=1) from None
    finally:
        _close_cli_bench(bench)


@app.command("abort", hidden=True)
def abort_command(
    alias: Annotated[str, typer.Argument(help="Motion resource alias in the bench.")],
    as_json: Annotated[bool, typer.Option("--json", help="Emit machine-readable output.")] = False,
    bench_path: Annotated[Path | None, _bench_option()] = None,
):
    """Abort a controller operation; this is not a safety-rated emergency stop."""

    bench = _open_cli_bench(bench_path, aliases={alias})
    try:
        result = _motion_resource(bench, alias).abort()
        _report_motion_result(result, as_json=as_json)
    except _CAPABILITY_ERRORS as exc:
        rich.print(f"[bold red]Error: {exc}[/bold red]")
        raise typer.Exit(code=1) from None
    finally:
        _close_cli_bench(bench)


@app.command("jog", hidden=True)
def jog_command(
    alias: Annotated[str, typer.Argument(help="Motion resource alias in the bench.")],
    axis: Annotated[str, typer.Argument(help="Axis name.")],
    velocity: Annotated[float, typer.Argument(help="Signed velocity.")],
    units: Annotated[str, typer.Option("--units")] = "mm/s",
    frame: Annotated[str, typer.Option("--frame")] = "machine",
    as_json: Annotated[bool, typer.Option("--json", help="Emit machine-readable output.")] = False,
    bench_path: Annotated[Path | None, _bench_option()] = None,
):
    """Jog one axis using the generic motion capability."""

    bench = _open_cli_bench(bench_path, aliases={alias})
    try:
        result = _motion_resource(bench, alias).jog(axis, velocity, units=units, frame=frame)
        _report_motion_result(result, as_json=as_json)
    except _CAPABILITY_ERRORS as exc:
        rich.print(f"[bold red]Error: {exc}[/bold red]")
        raise typer.Exit(code=1) from None
    finally:
        _close_cli_bench(bench)


@motion_app.command("status")
@app.command("status", hidden=True)
def status_command(
    alias: Annotated[str, typer.Argument(help="Motion resource alias in the bench.")],
    as_json: Annotated[bool, typer.Option("--json", help="Emit machine-readable output.")] = False,
    bench_path: Annotated[Path | None, _bench_option()] = None,
):
    """Read normalized status from a MotionDevice."""

    bench = _open_cli_bench(bench_path, aliases={alias})
    try:
        status = _motion_resource(bench, alias).get_status()
        payload = {
            "state": status.state,
            "settled": status.settled,
            "homed": status.homed,
            "enabled": status.enabled,
            "fault": status.fault,
            "target_reached": status.target_reached,
            "operation_id": status.operation_id,
            "details": status.details,
        }
        if as_json:
            typer.echo(json.dumps(payload, sort_keys=True))
        else:
            color = "red" if status.fault else "green" if status.settled else "yellow"
            readbacks = [f"settled: {'yes' if status.settled else 'no'}"]
            if status.fault:
                readbacks.append("fault reported")
            rich.print(
                f"[cyan]{rich_escape(alias)}[/cyan]: [{color}]{rich_escape(status.state)}[/{color}] "
                f"({', '.join(readbacks)})"
            )
    except _CAPABILITY_ERRORS as exc:
        _report_motion_error(exc)
        raise typer.Exit(code=1) from None
    finally:
        _close_cli_bench(bench)


@app.callback()
def main_callback(
    version: bool | None = typer.Option(
        None, "--version", callback=version_callback, is_eager=True, help="Show version and exit."
    ),
):
    """PyTestLab: Scientific test & measurement toolbox CLI."""


profile_app = typer.Typer(name="profile", help="Manage device profiles.")
device_app = typer.Typer(name="device", help="Interact with lab devices.")
instrument_app = typer.Typer(name="instrument", help="Interact with instruments.")
bench_app = typer.Typer(name="bench", help="Manage bench configurations.")
sim_profile_app = typer.Typer(name="sim-profile", help="Manage simulation profiles.")
visa_app = typer.Typer(name="visa", help="Discover VISA resources.")
lamb_app = typer.Typer(name="lamb", help="Interact with LAMB instrument server.")
sim_app = typer.Typer(name="sim", help="Circuit simulation lane utilities (pytestlab.sim.circuit).")
evidence_app = typer.Typer(
    name="evidence", help="Generate and check PyTestLab validation evidence artifacts."
)
twin_app = typer.Typer(
    name="twin", help="Digital-twin oracle, residual, and characterized-evidence utilities."
)

# Create a new Typer app for replay commands
replay_app = typer.Typer(name="replay", help="Record and replay complex measurement sessions.")
app.add_typer(replay_app)

app.add_typer(profile_app)
app.add_typer(device_app)
app.add_typer(instrument_app)
app.add_typer(bench_app)
app.add_typer(sim_profile_app)
app.add_typer(visa_app)
app.add_typer(lamb_app)
app.add_typer(sim_app)
app.add_typer(evidence_app)
app.add_typer(twin_app)


@evidence_app.command("generate")
def evidence_generate(
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="Directory where evidence artifacts are written."),
    ] = Path(".omx/evidence/current"),
    section: Annotated[
        str,
        typer.Option("--section", help="Evidence section to generate: all or jcgm."),
    ] = "all",
    check: Annotated[
        bool,
        typer.Option("--check", help="Check the generated bundle after writing it."),
    ] = False,
):
    """Generate deterministic validation-evidence artifacts."""

    from pytestlab.evidence import check_evidence
    from pytestlab.evidence import generate_evidence

    bundle = generate_evidence(output, section=section)
    rich.print(f"[green]Evidence manifest:[/] {bundle.manifest_path}")
    rich.print(f"[green]Evidence report:[/] {bundle.report_path}")
    rich.print(f"Payload SHA256: {bundle.manifest['payload_sha256']}")
    if check:
        check_evidence(output)
        rich.print("[green]Evidence check passed[/]")


@evidence_app.command("check")
def evidence_check(
    path: Annotated[Path, typer.Argument(help="Directory containing an evidence manifest.")],
):
    """Check an evidence bundle against the current repository state."""

    from pytestlab.evidence import EvidenceDriftError
    from pytestlab.evidence import check_evidence

    try:
        result = check_evidence(path)
    except EvidenceDriftError as exc:
        rich.print(f"[bold red]Evidence drift:[/] {rich_escape(str(exc))}")
        raise typer.Exit(code=1) from None
    except FileNotFoundError as exc:
        rich.print(f"[bold red]Evidence bundle missing:[/] {rich_escape(str(exc))}")
        raise typer.Exit(code=1) from None
    rich.print(f"[green]Evidence OK:[/] {result['manifest']}")
    rich.print(f"Payload SHA256: {result['payload_sha256']}")


@evidence_app.command("scope-twin")
def evidence_scope_twin(
    output: Annotated[
        Path,
        typer.Option(
            "--output",
            "-o",
            help="Directory where scope-twin known-truth validation artifacts are written.",
        ),
    ] = Path(".omx/evidence/scope-twin"),
    mc_samples: Annotated[
        int,
        typer.Option("--mc-samples", help="Monte Carlo samples for Vpp validation."),
    ] = 3000,
    check: Annotated[
        bool,
        typer.Option("--check", help="Check the generated bundle after writing it."),
    ] = False,
):
    """Generate deterministic oscilloscope digital-twin known-truth evidence."""

    from pytestlab.validation.scope_twin import check_scope_twin_known_truth_validation
    from pytestlab.validation.scope_twin import run_scope_twin_known_truth_validation

    report = run_scope_twin_known_truth_validation(output, mc_samples=mc_samples)
    rich.print(f"[green]Scope-twin report:[/] {report.report_path}")
    rich.print(f"[green]Scope-twin manifest:[/] {report.manifest_path}")
    rich.print(f"Payload SHA256: {report.payload_sha256}")
    if not report.passed:
        rich.print("[bold red]Scope-twin known-truth validation failed.[/bold red]")
        raise typer.Exit(code=1)
    if check:
        check_report = check_scope_twin_known_truth_validation(output)
        rich.print(f"[green]Scope-twin evidence check passed[/] ({check_report.payload_sha256})")


@evidence_app.command("scope-oracle")
def evidence_scope_oracle(
    output: Annotated[
        Path,
        typer.Option(
            "--output",
            "-o",
            help="Directory where scope-oracle known-truth validation artifacts are written.",
        ),
    ] = Path(".omx/evidence/scope-oracle"),
    mc_samples: Annotated[
        int,
        typer.Option("--mc-samples", help="Monte Carlo samples for Vpp validation."),
    ] = 3000,
    check: Annotated[
        bool,
        typer.Option("--check", help="Check the generated bundle after writing it."),
    ] = False,
):
    """Generate deterministic oscilloscope validation-oracle evidence."""

    evidence_scope_twin(output=output, mc_samples=mc_samples, check=check)


@evidence_app.command("hardware-parity")
def evidence_hardware_parity(
    fixture: Annotated[
        Path,
        typer.Argument(help="Hardware replay fixture JSON."),
    ],
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="Directory where parity evidence is written."),
    ] = Path(".omx/evidence/hardware-parity"),
    coverage_factor: Annotated[
        float,
        typer.Option("--coverage-factor", help="Coverage factor for combined uncertainty."),
    ] = 2.0,
):
    """Replay a hardware capture fixture and compare it with expected/simulator metrics."""

    from pytestlab.validation.hardware_parity import write_hardware_parity_report

    report = write_hardware_parity_report(
        fixture,
        output,
        coverage_factor=coverage_factor,
    )
    rich.print(f"[green]Hardware parity report:[/] {output / 'hardware_parity_report.json'}")
    rich.print(f"Payload SHA256: {report.payload_sha256}")
    if not report.passed:
        rich.print("[bold red]Hardware replay parity failed.[/bold red]")
        raise typer.Exit(code=1)
    rich.print(f"[green]{len(report.rows)} parity checks passed[/]")


@twin_app.command("oracle")
def twin_oracle(
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="Directory where oracle artifacts are written."),
    ] = Path(".omx/evidence/twin-oracle"),
    mc_samples: Annotated[
        int,
        typer.Option("--mc-samples", help="Monte Carlo samples for Vpp validation."),
    ] = 3000,
    check: Annotated[
        bool,
        typer.Option("--check", help="Check the generated oracle bundle after writing it."),
    ] = False,
):
    """Run the known-truth oscilloscope validation oracle."""

    from pytestlab.validation.scope_twin import check_scope_twin_known_truth_validation
    from pytestlab.validation.scope_twin import run_scope_twin_known_truth_validation

    report = run_scope_twin_known_truth_validation(output, mc_samples=mc_samples)
    rich.print(f"[green]Twin oracle report:[/] {report.report_path}")
    rich.print(f"[green]Twin oracle manifest:[/] {report.manifest_path}")
    rich.print("Claim: software validation oracle; not characterized hardware")
    rich.print(f"Payload SHA256: {report.payload_sha256}")
    if not report.passed:
        rich.print("[bold red]Twin oracle validation failed.[/bold red]")
        raise typer.Exit(code=1)
    if check:
        check_report = check_scope_twin_known_truth_validation(output)
        rich.print(f"[green]Twin oracle evidence check passed[/] ({check_report.payload_sha256})")


@twin_app.command("residual-from-replay")
def twin_residual_from_replay(
    fixture: Annotated[Path, typer.Argument(help="Hardware replay fixture JSON.")],
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="Directory where residual evidence is written."),
    ] = Path(".omx/evidence/twin-residual"),
    coverage_factor: Annotated[
        float,
        typer.Option("--coverage-factor", help="Coverage factor for residual acceptance."),
    ] = 2.0,
    check: Annotated[
        bool,
        typer.Option("--check", help="Check the residual report after writing it."),
    ] = False,
):
    """Generate a twin residual report from a replay fixture.

    Fixture self-consistency reports are intentionally labeled replay-regression
    evidence. Only fixtures classified as independent parity become
    twin-validation evidence suitable for characterized-twin claims.
    """

    from pytestlab.twin import check_residual_report
    from pytestlab.twin import residual_report_from_replay_fixture
    from pytestlab.twin import write_residual_report

    report = residual_report_from_replay_fixture(fixture, coverage_factor=coverage_factor)
    path = write_residual_report(output / "twin_residual_report.json", report)
    rich.print(f"[green]Twin residual report:[/] {path}")
    rich.print(f"Status: {report.status.value}")
    rich.print(f"Origin/purpose: {report.data_origin} / {report.evidence_purpose}")
    rich.print(f"Payload SHA256: {report.payload_sha256}")
    if check:
        check_residual_report(path)
        rich.print("[green]Twin residual evidence check passed[/]")
    if report.status.value not in {"pass", "incomplete"}:
        raise typer.Exit(code=1)


@twin_app.command("characterize-scope")
def twin_characterize_scope(
    residual_report: Annotated[
        Path,
        typer.Argument(help="Passing twin-validation residual report JSON."),
    ],
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="Directory where characterized evidence is written."),
    ] = Path(".omx/evidence/characterized-scope"),
    check: Annotated[
        bool,
        typer.Option("--check", help="Check the characterized evidence after writing it."),
    ] = False,
):
    """Create characterized scope-twin evidence from a passing residual report."""

    from pytestlab.twin import CharacterizedScopeTwin
    from pytestlab.twin import check_twin_evidence
    from pytestlab.twin import load_residual_report
    from pytestlab.twin import write_twin_evidence

    report = load_residual_report(residual_report)
    try:
        twin = CharacterizedScopeTwin(
            identity=report.twin_identity,
            domain=report.domain,
            residual_report=report,
        )
    except ValueError as exc:
        rich.print(f"[bold red]Cannot characterize scope twin:[/] {rich_escape(str(exc))}")
        raise typer.Exit(code=1) from None
    evidence = twin.validation_evidence()
    path = write_twin_evidence(output / "characterized_scope_twin_evidence.json", evidence)
    rich.print(f"[green]Characterized scope-twin evidence:[/] {path}")
    rich.print("Claim: validation evidence only; not a measured calibration result or certificate")
    rich.print(f"Payload SHA256: {evidence.payload_sha256}")
    if check:
        check_twin_evidence(path)
        rich.print("[green]Characterized scope-twin evidence check passed[/]")


@twin_app.command("check")
def twin_check(
    path: Annotated[Path, typer.Argument(help="Twin evidence or residual-report JSON.")],
):
    """Check a twin evidence JSON artifact for tampering and claim-boundary labels."""

    from pytestlab.twin import TwinEvidenceError
    from pytestlab.twin import check_residual_report
    from pytestlab.twin import check_twin_evidence

    try:
        payload = check_residual_report(path)
        rich.print(f"[green]Residual report OK:[/] {path}")
    except TwinEvidenceError as residual_error:
        try:
            payload = check_twin_evidence(path)
            rich.print(f"[green]Twin evidence OK:[/] {path}")
        except TwinEvidenceError as twin_error:
            rich.print(
                "[bold red]Twin artifact invalid:[/] "
                f"residual={rich_escape(str(residual_error))}; "
                f"evidence={rich_escape(str(twin_error))}"
            )
            raise typer.Exit(code=1) from None
    rich.print(f"Payload SHA256: {payload['payload_sha256']}")


@sim_app.command("doctor")
def sim_doctor() -> None:
    """Check that the circuit simulation lane is ready to run.

    Verifies the Python lane imports and that an ``ngspice`` binary is on PATH,
    printing actionable install guidance (system package / Docker) when it is
    missing. Exits non-zero if the environment is not ready, so it can gate CI.
    """
    import subprocess

    console = rich.get_console()
    ready = True

    try:
        import pytestlab.sim.circuit  # noqa: F401

        console.print("[green]✓[/green] pytestlab.sim.circuit importable")
    except Exception as exc:
        ready = False
        console.print(f"[red]✗[/red] cannot import pytestlab.sim.circuit: {exc}")

    from pytestlab.sim.circuit.spice import _NGSPICE_INSTALL_HELP
    from pytestlab.sim.circuit.spice import resolve_ngspice

    cmd = os.getenv("SIMBENCH_NGSPICE_CMD", "ngspice")
    resolved = resolve_ngspice(cmd)
    if resolved:
        version = ""
        try:
            out = subprocess.run([resolved, "-v"], capture_output=True, text=True, timeout=10)
            for line in (out.stdout or out.stderr or "").splitlines():
                stripped = line.strip().lstrip("*").strip()
                if "ngspice" in stripped.lower():
                    version = stripped
                    break
        except Exception:
            pass
        console.print(f"[green]✓[/green] ngspice found: {resolved}")
        if version:
            console.print(f"    {version}")
    else:
        ready = False
        console.print(f"[red]✗[/red] ngspice binary not found (looked for {cmd!r})")
        # markup=False: the help text contains "pytestlab[circuit]", which rich
        # would otherwise parse as a style tag and drop.
        console.print(_NGSPICE_INSTALL_HELP, markup=False)

    if ready:
        console.print("\n[bold green]Circuit simulation lane is ready.[/bold green]")
    else:
        console.print("\n[bold red]Circuit simulation lane is NOT ready.[/bold red]")
        raise typer.Exit(code=1)


# Package managers that can provide ngspice, in priority order. ``user_space``
# means the install needs no root privileges. PyTestLab only runs user-space
# managers for you (with consent); root-requiring managers are printed for you
# to run yourself. PyTestLab never invokes sudo and never assumes you have it.
_NGSPICE_MANAGERS: list[tuple[str, list[str], bool]] = [
    ("conda", ["conda", "install", "-y", "-c", "conda-forge", "ngspice"], True),
    ("micromamba", ["micromamba", "install", "-y", "-c", "conda-forge", "ngspice"], True),
    ("pixi", ["pixi", "global", "install", "ngspice"], True),
    ("brew", ["brew", "install", "ngspice"], True),
    ("apt-get", ["apt-get", "install", "-y", "ngspice"], False),
    ("dnf", ["dnf", "install", "-y", "ngspice"], False),
    ("pacman", ["pacman", "-S", "--noconfirm", "ngspice"], False),
    ("zypper", ["zypper", "install", "-y", "ngspice"], False),
    ("choco", ["choco", "install", "-y", "ngspice"], False),
]


def _detect_ngspice_manager() -> tuple[str, list[str], bool] | None:
    """Return (manager, argv, user_space) for the first available manager."""
    for name, argv, user_space in _NGSPICE_MANAGERS:
        if shutil.which(name):
            return name, argv, user_space
    return None


def _is_root() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0


@sim_app.command("install-ngspice")
def sim_install_ngspice(
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Run the install without confirmation (user-space managers only).",
    ),
) -> None:
    """Help install the ngspice binary using a detected package manager.

    PyTestLab runs sudo-free, user-space managers (conda/micromamba/pixi/brew)
    for you, with consent. Managers that need root (apt-get/dnf/pacman/zypper/
    choco) are only printed for you to run yourself: PyTestLab never invokes
    sudo and never assumes you have it. Falls back to manual/Docker guidance
    when no manager is found, and is a no-op when ngspice is already present.
    """
    import subprocess

    from pytestlab.sim.circuit.spice import resolve_ngspice

    console = rich.get_console()
    cmd_name = os.getenv("SIMBENCH_NGSPICE_CMD", "ngspice")
    existing = resolve_ngspice(cmd_name)
    if existing:
        console.print(f"[green]✓[/green] ngspice is already installed ({existing}).")
        raise typer.Exit(0)

    # On platforms with no upstream/conda-forge build (Linux arm64/armv7) fetch a
    # prebuilt, relocatable bundle from the mirror -- no package manager, no root.
    from pytestlab.sim.circuit._mirror import install_from_mirror
    from pytestlab.sim.circuit._mirror import mirror_asset

    asset = mirror_asset()
    if asset is not None:
        console.print(
            f"Detected [bold]{asset}[/bold] (no system/conda-forge ngspice exists "
            "for it). PyTestLab can fetch a prebuilt bundle into ~/.pytestlab/ "
            "(no package manager or root needed)."
        )
        if not yes and (not sys.stdin.isatty() or not typer.confirm("Download it now?")):
            console.print("Not downloading. Re-run with --yes to fetch it.")
            raise typer.Exit(1)
        try:
            path = install_from_mirror(asset, log=lambda m: console.print(f"  {m}"))
        except Exception as exc:  # network/checksum/extract failure
            console.print(f"[red]Mirror install failed: {exc}[/red]")
            raise typer.Exit(1) from None
        console.print(f"[green]✓ ngspice installed at {path}[/green]")
        raise typer.Exit(0)

    detected = _detect_ngspice_manager()
    if detected is None:
        from pytestlab.sim.circuit.spice import _NGSPICE_INSTALL_HELP

        console.print(
            "[yellow]No supported package manager found on PATH "
            "(conda/micromamba/pixi/brew/apt-get/dnf/pacman/zypper/choco).[/yellow]"
        )
        console.print(_NGSPICE_INSTALL_HELP, markup=False)
        console.print("Or use the bundled dev container in .devcontainer/.")
        raise typer.Exit(1)

    manager, argv, user_space = detected
    console.print(f"Detected package manager: [bold]{manager}[/bold]")
    console.print("Install command: [cyan]" + " ".join(argv) + "[/cyan]")

    # Only run it ourselves if no privilege escalation is required.
    if not (user_space or _is_root()):
        console.print(
            f"[yellow]{manager} needs root privileges. Run the command above "
            "yourself (as root, or via your system administrator). PyTestLab "
            "will not run sudo or assume you can.[/yellow]"
        )
        raise typer.Exit(1)

    if not yes:
        if not sys.stdin.isatty() or not typer.confirm("Run it now?"):
            console.print("Not running it. Re-run with --yes, or run the command above yourself.")
            raise typer.Exit(1)

    try:
        subprocess.run(argv, check=True)
    except FileNotFoundError:
        console.print(f"[red]Could not run {argv[0]!r}.[/red]")
        raise typer.Exit(1) from None
    except subprocess.CalledProcessError as exc:
        console.print(f"[red]Install command failed (exit {exc.returncode}).[/red]")
        raise typer.Exit(exc.returncode) from None

    if shutil.which(cmd_name):
        console.print("[green]✓ ngspice installed.[/green]")
    else:
        console.print(
            "[yellow]Install ran but ngspice is still not on PATH; "
            "open a new shell or check the manager output.[/yellow]"
        )
        raise typer.Exit(1)


# --- Simulation Profile Helpers ---
def get_user_override_path(profile_key: str) -> Path:
    """Gets the path to the user's override profile."""
    home_dir = Path.home()
    key_path = Path(profile_key.replace("/", os.sep) + ".yaml")
    return home_dir / ".config" / "pytestlab" / "profiles" / key_path


def get_user_recorded_profile_path(profile_key: str) -> Path:
    """Gets the path for a recorded simulation profile in the user's cache."""
    home_dir = Path.home()
    key_path = Path(profile_key.replace("/", os.sep) + ".yaml")
    return home_dir / ".config" / "pytestlab" / "recorded_sim_profiles" / key_path


# --- VISA Discovery Commands ---
def _create_visa_resource_manager() -> Any:
    try:
        import pyvisa
    except ImportError as exc:
        raise RuntimeError(
            "PyVISA is not installed. Install it with 'pip install pyvisa', then install "
            "a VISA library such as NI-VISA or Keysight IO Libraries."
        ) from exc

    try:
        return pyvisa.ResourceManager()
    except Exception as exc:
        raise RuntimeError(
            "Could not initialize a VISA resource manager. Check that a VISA library is "
            "installed, then run 'python -m pyvisa info' for details."
        ) from exc


@visa_app.command("list")
def visa_list(
    idn: Annotated[
        bool,
        typer.Option("--idn", help="Query *IDN? for each discovered message-based resource."),
    ] = False,
    timeout_ms: Annotated[
        int,
        typer.Option(help="Timeout in milliseconds for optional --idn probes."),
    ] = 2000,
):
    """List VISA resource strings visible to PyVISA."""
    if timeout_ms <= 0:
        rich.print("[bold red]Error:[/] --timeout-ms must be positive.")
        raise typer.Exit(code=1)

    try:
        rm = _create_visa_resource_manager()
        resources = tuple(rm.list_resources())
    except RuntimeError as exc:
        rich.print(f"[bold red]Error:[/] {rich_escape(str(exc))}")
        raise typer.Exit(code=1) from None
    except Exception as exc:
        rich.print(f"[bold red]Error listing VISA resources:[/] {rich_escape(str(exc))}")
        raise typer.Exit(code=1) from None

    if not resources:
        rich.print(
            "No VISA resources found. Check instrument power, cabling/network, USB/GPIB/LAN "
            "drivers, and run 'python -m pyvisa info'."
        )
        return

    table = Table(title="VISA Resources")
    table.add_column("Resource", style="cyan", overflow="fold")
    if idn:
        table.add_column("*IDN? Response", style="green", overflow="fold")

    for resource_name in resources:
        if not idn:
            table.add_row(str(resource_name))
            continue

        idn_response = ""
        resource = None
        try:
            resource = rm.open_resource(resource_name)
            if hasattr(resource, "timeout"):
                resource.timeout = timeout_ms
            if not hasattr(resource, "query"):
                idn_response = "[yellow]Not query-capable[/yellow]"
            else:
                idn_response = str(resource.query("*IDN?")).strip()
        except Exception as exc:
            idn_response = f"[red]Error: {rich_escape(str(exc))}[/red]"
        finally:
            if resource is not None and hasattr(resource, "close"):
                try:
                    resource.close()
                except Exception:
                    pass
        table.add_row(str(resource_name), idn_response)

    rich.print(table)


@lamb_app.command("list")
def lamb_list(
    url: Annotated[
        str | None,
        typer.Option(
            help="LAMB server base URL. Defaults to LAMB_SERVER or http://lamb-server:8000."
        ),
    ] = None,
    timeout_ms: Annotated[
        int,
        typer.Option(help="Timeout in milliseconds for server requests."),
    ] = 5000,
):
    """List instrument resources available via a LAMB server."""
    import httpx

    if timeout_ms <= 0:
        rich.print("[bold red]Error:[/] --timeout-ms must be positive.")
        raise typer.Exit(code=1)

    base_url = resolve_lamb_url(url)
    try:
        with httpx.Client(timeout=timeout_ms / 1000.0) as client:
            response = client.get(f"{base_url}/list_resources")
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        rich.print(
            f"[bold red]Error:[/] LAMB server returned {exc.response.status_code} - {rich_escape(exc.response.text)}"
        )
        raise typer.Exit(code=1) from None
    except httpx.RequestError as exc:
        rich.print(
            f"[bold red]Error:[/] Could not connect to LAMB server at {base_url}: {rich_escape(str(exc))}"
        )
        raise typer.Exit(code=1) from None
    except Exception as exc:
        rich.print(f"[bold red]Error listing LAMB resources:[/] {rich_escape(str(exc))}")
        raise typer.Exit(code=1) from None

    active = data.get("active", [])
    inactive = data.get("inactive", [])

    if not active and not inactive:
        rich.print("No instrument resources found on the LAMB server.")
        return

    table = Table(title=f"LAMB Resources — {base_url}")
    table.add_column("Resource", style="cyan", overflow="fold")
    table.add_column("Status", style="green")

    for resource in active:
        table.add_row(str(resource), "[green]active[/green]")
    for resource in inactive:
        table.add_row(str(resource), "[yellow]inactive[/yellow]")

    rich.print(table)
    rich.print(f"\nTotal: {len(active)} active, {len(inactive)} inactive")


@lamb_app.command("verify-scopes")
def lamb_verify_scopes(
    url: Annotated[
        str | None,
        typer.Option(help="LAMB server base URL. Overrides LAMB_SERVER environment variable."),
    ] = None,
    timeout_ms: Annotated[
        int,
        typer.Option(help="Timeout in milliseconds for each LAMB operation."),
    ] = 5000,
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            help="Directory for JSON evidence with command metadata and response length/hash.",
        ),
    ] = None,
    capture_waveform: Annotated[
        bool,
        typer.Option(
            "--capture-waveform",
            help="Opt into query_raw(:WAVeform:DATA?) binary waveform transfer.",
        ),
    ] = False,
    non_strict: Annotated[
        bool,
        typer.Option(
            "--non-strict",
            help="Represent missing/unresponsive expected instruments as skips instead of failures.",
        ),
    ] = False,
):
    """Verify the MXR404A/HD304MSO remote LAMB oscilloscope acceptance rig."""

    from pytestlab.hardware.lamb_scope import run_lamb_scope_checks

    resolved_url = url or os.getenv("LAMB_SERVER") or os.getenv("PYTESTLAB_LAMB_URL")
    if not resolved_url:
        rich.print(
            "[bold red]Error:[/] LAMB URL is required for live scope verification. "
            "Pass --url or set LAMB_SERVER/PYTESTLAB_LAMB_URL."
        )
        raise typer.Exit(code=2)

    report = run_lamb_scope_checks(
        url=resolved_url,
        timeout_ms=timeout_ms,
        capture_waveform=capture_waveform,
        strict=not non_strict,
        output_dir=output,
    )

    table = Table(title=f"LAMB Oscilloscope Verification — {report.lamb_url}")
    table.add_column("Model", style="cyan")
    table.add_column("Check", style="magenta")
    table.add_column("Status")
    table.add_column("Command")
    table.add_column("Detail", overflow="fold")
    for row in report.rows:
        if row.status == "pass":
            status = "[green]pass[/green]"
        elif row.status == "skip":
            status = "[yellow]skip[/yellow]"
        else:
            status = "[red]fail[/red]"
        table.add_row(
            row.model,
            row.check,
            status,
            row.command or "-",
            row.detail if row.response_len is None else f"{row.detail}; len={row.response_len}",
        )
    rich.print(table)
    if report.artifact_path:
        rich.print(f"Evidence artifact: {report.artifact_path}")
    if report.failures:
        rich.print(f"[bold red]{len(report.failures)} LAMB oscilloscope checks failed.[/bold red]")
        raise typer.Exit(code=1)
    rich.print(
        f"[bold green]{len(report.passes)} checks passed[/bold green]"
        f" ({len(report.skips)} skipped)."
    )


# --- Simulation Profile Commands ---


@sim_profile_app.command("edit")
def sim_profile_edit(
    profile_key: Annotated[str, typer.Argument(help="Profile key (e.g., keysight/DSOX1204G).")],
):
    """Opens the user's override profile in their default text editor."""
    from pytestlab.config.loader import resolve_profile_key_to_path

    try:
        official_path = resolve_profile_key_to_path(profile_key)
        override_path = get_user_override_path(profile_key)

        if not override_path.exists():
            rich.print(
                f"No user override found for '{profile_key}'. Creating one from the official profile."
            )
            override_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(official_path, override_path)
            rich.print(f"Copied official profile to: {override_path}")

        rich.print(f"Opening '{override_path}' in your default editor...")
        typer.launch(str(override_path))

    except FileNotFoundError:
        rich.print(
            f"[bold red]Error: Official profile for key '{profile_key}' not found.[/bold red]"
        )
        raise typer.Exit(code=1) from None
    except Exception as e:
        rich.print(f"[bold red]An unexpected error occurred: {e}[/bold red]")
        raise typer.Exit(code=1) from None


@sim_profile_app.command("reset")
def sim_profile_reset(profile_key: Annotated[str, typer.Argument(help="Profile key to reset.")]):
    """Deletes the user's override profile, reverting to the official one."""
    override_path = get_user_override_path(profile_key)
    if override_path.exists():
        try:
            os.remove(override_path)
            rich.print(
                f"[bold green]Successfully deleted override profile:[/bold green] {override_path}"
            )
            rich.print(f"Simulations for '{profile_key}' will now use the official profile.")
        except OSError as e:
            rich.print(f"[bold red]Error deleting file '{override_path}': {e}[/bold red]")
            raise typer.Exit(code=1) from None
    else:
        rich.print(
            f"[bold yellow]No user override profile to reset for '{profile_key}'.[/bold yellow]"
        )


@sim_profile_app.command("diff")
def sim_profile_diff(profile_key: Annotated[str, typer.Argument(help="Profile key to compare.")]):
    """Shows a diff between the user's override and the official profile."""
    from pytestlab.config.loader import resolve_profile_key_to_path

    try:
        official_path = resolve_profile_key_to_path(profile_key)
        override_path = get_user_override_path(profile_key)

        if not override_path.exists():
            rich.print(
                f"[bold yellow]No user override profile found for '{profile_key}'. Nothing to compare.[/bold yellow]"
            )
            raise typer.Exit()

        with open(official_path) as f_official, open(override_path) as f_override:
            official_lines = f_official.readlines()
            override_lines = f_override.readlines()

        diff = difflib.unified_diff(
            official_lines,
            override_lines,
            fromfile=f"official/{profile_key}",
            tofile=f"user/{profile_key}",
        )

        diff_str = "".join(diff)
        if not diff_str:
            rich.print(
                "[bold green]No differences found between the official and user profiles.[/bold green]"
            )
            return

        rich.print(f"[bold]Diff for {profile_key}:[/bold]")
        syntax = Syntax(diff_str, "diff", theme="monokai")
        rich.print(syntax)

    except FileNotFoundError:
        rich.print(
            f"[bold red]Error: Official profile for key '{profile_key}' not found.[/bold red]"
        )
        raise typer.Exit(code=1) from None
    except Exception as e:
        rich.print(f"[bold red]An unexpected error occurred: {e}[/bold red]")
        raise typer.Exit(code=1) from None


@sim_profile_app.command("record")
def sim_profile_record(
    profile_key: Annotated[str, typer.Argument(help="Profile key of the device to record.")],
    address: Annotated[str | None, typer.Option(help="VISA address of the device.")] = None,
    output_path: Annotated[
        Path | None,
        typer.Option(
            help="Output path for the recorded YAML profile. If not provided, it will be saved to the user's cache."
        ),
    ] = None,
    script: Annotated[
        Path | None, typer.Option(help="Path to a Python script to run against the device.")
    ] = None,
    simulate: Annotated[bool, typer.Option(help="Use a simulated device for recording.")] = False,
):
    """Records device interactions to create a simulation profile."""
    from pytestlab.config.loader import load_device_profile
    from pytestlab.devices import AutoDevice
    from pytestlab.devices import DeviceIO
    from pytestlab.instruments.backends.recording_backend import RecordingBackend

    device = None
    final_output_path = output_path  # Ensure defined even if an early exception occurs
    try:
        if not simulate and not address:
            rich.print(
                "[bold red]Error: The --address option is required for recording from a real device.[/bold red]"
            )
            raise typer.Exit(code=1)

        final_output_path = output_path
        if not final_output_path:
            final_output_path = get_user_recorded_profile_path(profile_key)
            final_output_path.parent.mkdir(parents=True, exist_ok=True)
            rich.print(
                f"[yellow]No output path provided. Saving to user cache:[/yellow] {final_output_path}"
            )

        if simulate:
            rich.print(f"Connecting to simulated device '{profile_key}'...")
        else:
            rich.print(f"Connecting to device '{profile_key}' at address '{address}'...")

        device = AutoDevice.from_config(
            config_source=profile_key, simulate=simulate, address_override=address
        )
        device.connect_backend()

        # Wrap the real backend with the recording backend
        base_profile_model = load_device_profile(profile_key)
        dump_internal = getattr(base_profile_model, "model_dump_internal", None)
        base_profile = (
            dump_internal(mode="json")
            if callable(dump_internal)
            else base_profile_model.model_dump(mode="json")
        )
        recording_backend = RecordingBackend(
            device._backend, str(final_output_path), base_profile=base_profile
        )
        device._backend = cast(DeviceIO, recording_backend)

        rich.print("[bold green]Connection successful. Recording started.[/bold green]")

        if script:
            rich.print(f"\n[bold]Running script:[/bold] {script}")
            spec = importlib.util.spec_from_file_location("script_module", script)
            if spec and spec.loader:
                script_module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(script_module)
                if hasattr(script_module, "main"):
                    script_module.main(device)
                else:
                    rich.print(
                        "[bold yellow]Warning: No 'main(device)' function found in script.[/bold yellow]"
                    )
            else:
                rich.print(f"[bold red]Error: Could not load script '{script}'.[/bold red]")
        else:
            rich.print(
                "\n[bold]Starting interactive REPL. Press Ctrl+D or type 'exit()' to quit.[/bold]"
            )
            # Basic REPL for demonstration
            code.interact(
                banner="PyTestLab Interactive Recording Session",
                local=dict(globals(), **{"device": device}),
                exitmsg="REPL finished.",
            )

    except Exception as e:
        import traceback

        rich.print(f"[bold red]An unexpected error occurred: {e}[/bold red]")
        traceback.print_exc()
        raise typer.Exit(code=1) from None
    finally:
        if device:
            rich.print("\nClosing connection and saving profile...")
            device.close()
            rich.print(f"[bold green]Profile saved to {final_output_path}.[/bold green]")


# --- Profile Commands ---
@profile_app.command("list")
def list_profiles(
    profile_dir: Annotated[Path | None, typer.Option(help="Custom directory for profiles.")] = None,
):
    """Lists available YAML device profiles."""
    try:
        profile_paths = []
        # Logic to find profiles in default package dir (pytestlab/profiles)
        spec = importlib.util.find_spec("pytestlab.profiles")
        if spec and spec.origin:
            default_profile_pkg_path = Path(spec.origin).parent
            for vendor_dir in default_profile_pkg_path.iterdir():
                if vendor_dir.is_dir() and vendor_dir.name != "__pycache__":
                    for profile_file in vendor_dir.glob("*.yaml"):
                        # Store as key like "vendor/file_name"
                        profile_key = f"{vendor_dir.name}/{profile_file.stem}"
                        profile_paths.append(profile_key)
        else:
            rich.print("[bold red]Error: Could not find the default profiles package.[/bold red]")
            raise typer.Exit(code=1)

        # Add logic for custom_dir if provided
        if profile_dir:
            if profile_dir.is_dir():
                for profile_file in profile_dir.glob(
                    "*.yaml"
                ):  # Assuming flat structure in custom_dir for now
                    profile_paths.append(str(profile_file.resolve()))
            else:
                rich.print(
                    f"[bold yellow]Warning: Custom profile directory '{profile_dir}' not found.[/bold yellow]"
                )

        if not profile_paths:
            rich.print("[bold yellow]No profiles found.[/bold yellow]")
            return

        table = Table(title="[bold]Available Profiles[/bold]")
        table.add_column("Profile Key", style="cyan", no_wrap=True)
        for p_path in sorted(
            list(set(profile_paths))
        ):  # Use set to avoid duplicates if custom overlaps
            table.add_row(p_path)
        rich.print(table)
    except Exception as e:
        rich.print(f"[bold red]An unexpected error occurred while listing profiles: {e}[/bold red]")
        raise typer.Exit(code=1) from None


@profile_app.command("show")
def show_profile(
    profile_key_or_path: Annotated[
        str,
        typer.Argument(help="Profile key (e.g., keysight/DSOX1204G) or direct path to YAML file."),
    ],
    field: Annotated[
        str | None,
        typer.Option("--field", help="Emit one top-level or dotted YAML field as JSON."),
    ] = None,
):
    """Shows a profile, or emits one selected field as JSON."""
    from pytestlab.config.loader import resolve_profile_key_to_path

    try:
        profile_path = Path(profile_key_or_path)
        if not profile_path.is_file():
            profile_path = resolve_profile_key_to_path(profile_key_or_path)

        with open(profile_path) as f:
            content = f.read()
            if field is not None:
                data = yaml.safe_load(content)
                value = data
                for part in field.split("."):
                    if isinstance(value, dict) and part in value:
                        value = value[part]
                    elif isinstance(value, list) and part.isdecimal() and int(part) < len(value):
                        value = value[int(part)]
                    else:
                        typer.echo(
                            json.dumps(
                                {
                                    "error": {
                                        "code": "profile_field_not_found",
                                        "field": field,
                                        "message": f"Profile field '{field}' was not found.",
                                    }
                                },
                                indent=2,
                                ensure_ascii=False,
                            )
                        )
                        raise typer.Exit(code=1)
                typer.echo(json.dumps(value, indent=2, ensure_ascii=False, default=str))
                return
            rich.print(f"[bold]Profile: {profile_key_or_path}[/bold]")
            syntax = Syntax(content, "yaml", theme="monokai", line_numbers=True)
            rich.print(syntax)
    except typer.Exit:
        raise
    except FileNotFoundError:
        rich.print(
            f"[bold red]Error: Profile '{profile_key_or_path}' not found.[/bold red]\n"
            "Please check for typos or ensure the profile exists in the 'pytestlab/profiles' directory."
        )
        raise typer.Exit(code=1) from None
    except yaml.YAMLError as e:
        rich.print(f"[bold red]Error parsing YAML file '{profile_key_or_path}': {e}[/bold red]")
        raise typer.Exit(code=1) from None
    except Exception as e:
        rich.print(
            f"[bold red]An unexpected error occurred while showing profile '{profile_key_or_path}': {e}[/bold red]"
        )
        raise typer.Exit(code=1) from None


@profile_app.command("validate")
def validate_profiles(
    profiles_path: Annotated[
        Path, typer.Argument(help="Path to a directory of profiles or a single profile file.")
    ],
    operation_contract: Annotated[
        bool,
        typer.Option(
            "--operation-contract",
            help="Also validate high-level instrument operation contract support.",
        ),
    ] = False,
    check_parameters: Annotated[
        bool,
        typer.Option(
            "--check-parameters",
            help="With --operation-contract, require declared operation parameter metadata.",
        ),
    ] = False,
    strict: Annotated[
        bool,
        typer.Option("--strict", help="Fail on operation contract warnings."),
    ] = False,
):
    """Validates YAML profiles against their corresponding Pydantic models."""
    from pytestlab.config.loader import load_device_profile

    if not profiles_path.exists():
        rich.print(f"[bold red]Error: Path '{profiles_path}' does not exist.[/bold red]")
        raise typer.Exit(code=1)

    profile_files = []
    if profiles_path.is_dir():
        profile_files.extend(list(profiles_path.glob("*.yaml")))
        profile_files.extend(list(profiles_path.glob("*.yml")))
    elif profiles_path.is_file():
        if profiles_path.suffix in [".yaml", ".yml"]:
            profile_files.append(profiles_path)
        else:
            rich.print(f"[bold red]Error: '{profiles_path}' is not a YAML file.[/bold red]")
            raise typer.Exit(code=1)

    if not profile_files:
        rich.print(f"[bold yellow]No YAML profiles found in '{profiles_path}'.[/bold yellow]")
        raise typer.Exit()

    rich.print(f"[bold]Validating {len(profile_files)} profile(s) in '{profiles_path}'...[/bold]")

    success_count = 0
    error_count = 0

    for profile_file in profile_files:
        try:
            load_device_profile(profile_file)
            if operation_contract:
                from pytestlab import AutoInstrument

                with contextlib.redirect_stdout(sys.stderr):
                    instrument = AutoInstrument.from_config(str(profile_file), simulate=True)
                instrument.validate_operation_contract(
                    strict=strict,
                    include_unsupported=True,
                    check_parameters=check_parameters,
                )
            rich.print(f"  [green]✔[/green] [cyan]{profile_file.name}[/cyan] - Valid")
            success_count += 1
        except Exception as e:
            rich.print(
                f"  [bold red]✖[/bold red] [cyan]{profile_file.name}[/cyan] - [red]Invalid[/red]"
            )
            rich.print(f"    [dim]Reason: {e}[/dim]")
            error_count += 1

    if error_count > 0:
        rich.print(
            f"\n[bold]Validation complete:[/bold] [green]{success_count} valid[/green], [red]{error_count} invalid[/red]."
        )
        raise typer.Exit(code=1)
    else:
        rich.print(f"\n[bold green]All {success_count} profiles are valid.[/bold green]")


@profile_app.command("schema")
def profile_schema(
    device_type: Annotated[
        str, typer.Argument(help="Device type (e.g., oscilloscope, power_supply)")
    ],
    output_file: Annotated[
        Path | None, typer.Option("--output", "-o", help="Output file for the schema")
    ] = None,
    no_format: Annotated[
        bool, typer.Option("--no-format", "-n", help="Don't format JSON output")
    ] = False,
):
    """Outputs the JSON schema for a given device type."""
    from pytestlab.config.schema_validator import SchemaValidator

    try:
        validator = SchemaValidator()
        schema = validator.get_device_schema(device_type, format_output=not no_format)

        if output_file:
            with open(output_file, "w") as f:
                f.write(schema)
            rich.print(f"[bold green]Schema written to:[/bold green] {output_file}")
        else:
            rich.print(f"[bold]Schema for {device_type}:[/bold]")
            syntax = Syntax(schema, "json", theme="monokai", line_numbers=True)
            rich.print(syntax)

    except ValueError as e:
        rich.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(code=1) from e
    except Exception as e:
        rich.print(f"[bold red]An unexpected error occurred: {e}[/bold red]")
        raise typer.Exit(code=1) from e


@profile_app.command("schema-info")
def profile_schema_info(
    device_type: Annotated[
        str, typer.Argument(help="Device type (e.g., oscilloscope, power_supply)")
    ],
):
    """Shows information about a schema without the full content."""
    from pytestlab.config.schema_validator import SchemaValidator

    try:
        validator = SchemaValidator()
        info = validator.get_schema_info(device_type)

        table = Table(title=f"Schema Information for {device_type}")
        table.add_column("Property", style="cyan")
        table.add_column("Value", style="green")

        table.add_row("Device Type", info["device_type"])
        table.add_row("Model Class", info["model_class"])
        table.add_row("Module", info["module"])
        table.add_row("Description", info["description"] or "N/A")

        rich.print(table)

    except ValueError as e:
        rich.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(code=1) from e
    except Exception as e:
        rich.print(f"[bold red]An unexpected error occurred: {e}[/bold red]")
        raise typer.Exit(code=1) from e


@profile_app.command("validate-schema")
def profile_validate_schema(
    yaml_file: Annotated[Path, typer.Argument(help="Path to the YAML file to validate")],
    device_type: Annotated[
        str | None,
        typer.Option("--device-type", "-t", help="Explicit device type override"),
    ] = None,
):
    """Validates a YAML profile against the appropriate device schema."""
    if not yaml_file.exists():
        rich.print(f"[bold red]Error: YAML file not found: {yaml_file}[/bold red]")
        raise typer.Exit(code=1) from None

    from pytestlab.config.schema_validator import SchemaValidator

    try:
        validator = SchemaValidator()
        result = validator.validate_yaml_profile(yaml_file, device_type)

        rich.print(f"[bold]Validation result for {yaml_file.name}:[/bold]")
        rich.print(f"  Device type: {result.device_type}")
        rich.print(f"  Schema used: {result.schema_used}")

        if result.is_valid:
            rich.print("  [bold green]Valid: ✓ Yes[/bold green]")
        else:
            rich.print("  [bold red]Valid: ✗ No[/bold red]")

            if result.errors:
                rich.print("\n[bold red]Errors:[/bold red]")
                for error in result.errors:
                    rich.print(f"  - {error}")

            if result.warnings:
                rich.print("\n[bold yellow]Warnings:[/bold yellow]")
                for warning in result.warnings:
                    rich.print(f"  - {warning}")

        if not result.is_valid:
            raise typer.Exit(code=1)

    except Exception as e:
        rich.print(f"[bold red]An unexpected error occurred: {e}[/bold red]")
        raise typer.Exit(code=1) from e


@profile_app.command("list-schemas")
def profile_list_schemas():
    """Lists all supported device types and their aliases."""
    from pytestlab.config.schema_validator import SchemaValidator

    try:
        validator = SchemaValidator()
        devices = validator.list_supported_devices()

        table = Table(title="Supported Device Types")
        table.add_column("Primary Name", style="cyan")
        table.add_column("Aliases", style="magenta")
        table.add_column("Configuration Class", style="green")

        # Group by primary names and aliases
        primary_names = {
            "oscilloscope": ["OscilloscopeConfig"],
            "waveform_generator": ["WaveformGeneratorConfig", "awg"],
            "power_supply": ["PowerSupplyConfig", "psu"],
            "dc_active_load": ["DCActiveLoadConfig", "electronic_load"],
            "multimeter": ["MultimeterConfig", "dmm"],
        }

        for primary, aliases in primary_names.items():
            if primary in devices:
                alias_list = [alias for alias in aliases[1:] if alias in devices]
                alias_str = ", ".join(alias_list) if alias_list else "None"
                table.add_row(primary, alias_str, aliases[0])

        rich.print(table)

    except Exception as e:
        rich.print(f"[bold red]An unexpected error occurred: {e}[/bold red]")
        raise typer.Exit(code=1) from e


# --- Device / Instrument Commands ---
def _device_idn_impl(profile_key_or_path: str, address: str | None, simulate: bool) -> None:
    from pytestlab.config.loader import load_device_profile
    from pytestlab.devices import AutoDevice

    device = None
    try:
        config_model = load_device_profile(profile_key_or_path)
        device = AutoDevice.from_config(
            config_source=config_model, simulate=simulate, address_override=address
        )
        idn = getattr(device, "id", None)
        if not callable(idn):
            raise NotImplementedError("Resource does not expose an identity capability.")
        device.connect_backend()
        idn_response = idn()
        rich.print(f"[bold green]IDN Response:[/] {idn_response}")
    except FileNotFoundError:
        rich.print(
            f"[bold red]Error: Profile '{rich_escape(str(profile_key_or_path))}' not found.[/]\n"
            "Please check for typos or ensure the profile exists in the 'pytestlab/profiles' directory."
        )
        raise typer.Exit(code=1) from None
    except Exception as e:
        rich.print(
            f"[bold red]An error occurred during the device IDN query: {rich_escape(str(e))}[/]"
        )
        raise typer.Exit(code=1) from None
    finally:
        if device:
            device.close()


def _resolve_profile_path(profile_key_or_path: str) -> Path:
    from pytestlab.config.loader import resolve_profile_key_to_path

    potential_path = Path(profile_key_or_path)
    if potential_path.suffix in {".yaml", ".yml", ".json"} and potential_path.is_file():
        return potential_path
    return resolve_profile_key_to_path(profile_key_or_path)


def _load_instrument_profile(profile_key_or_path: str):
    """Validate a local/profile source, then construct a normal instrument."""

    from pytestlab import AutoInstrument
    from pytestlab.config.loader import load_device_profile

    return AutoInstrument.from_config(load_device_profile(profile_key_or_path))


def _parse_operation_context(raw_context: str | None) -> dict[str, Any] | None:
    if raw_context is None:
        return None
    try:
        parsed = json.loads(raw_context)
    except json.JSONDecodeError as exc:
        raise ValueError(f"--context must contain valid JSON: {exc.msg}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("--context must be a JSON object")
    return parsed


def _print_operation_json(payload: Any) -> None:
    """Emit one JSON representation, adding only terminal syntax highlighting."""
    serialized = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=str)
    if sys.stdout.isatty() and "NO_COLOR" not in os.environ:
        Console(file=sys.stdout).print(JSONHighlighter()(serialized), soft_wrap=True)
    else:
        typer.echo(serialized)


def _print_operation_error(exc: Exception) -> None:
    from pytestlab.errors import InstrumentParameterError
    from pytestlab.errors import OperationDiscoveryError

    if isinstance(exc, InstrumentParameterError | OperationDiscoveryError):
        payload = exc.to_dict()
    else:
        code = "invalid_context" if "context" in str(exc).lower() else "operation_error"
        error: dict[str, Any] = {"code": code, "message": str(exc)}
        for name in ("parameter", "valid_range"):
            value = getattr(exc, name, None)
            if value is not None:
                error[name] = value
        payload = {"error": error}
    _print_operation_json(payload)


def _parse_json_object(raw: str | None, option_name: str) -> dict[str, Any]:
    """Parse a CLI JSON option that must contain an object."""

    if raw is None:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{option_name} must contain valid JSON: {exc.msg}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{option_name} must be a JSON object")
    return parsed


def _print_execute_operation_error(code: str, message: str, **details: Any) -> None:
    error: dict[str, Any] = {"code": code, "message": message}
    error.update({key: value for key, value in details.items() if value is not None})
    _print_operation_json({"error": error})


def _close_existing_backend(device: Any) -> None:
    """Close an already allocated backend without forcing lazy allocation."""
    from pytestlab.devices.base import _BackendFactory

    if isinstance(getattr(device, "_backend_source", None), _BackendFactory):
        return
    close = getattr(device, "close", None)
    if callable(close):
        close()


def _operation_instrument(
    profile_key_or_path: str,
    *,
    backend: str,
    address: str | None,
    lamb_url: str | None,
    serial_number: str | None,
    timeout_ms: int,
):
    """Build an instrument with a deferred backend for execute-operation."""
    from pytestlab import AutoInstrument

    backend_override = None
    backend_type_hint: str | None = backend
    if backend == "lamb" and lamb_url is not None:
        from pytestlab.config.loader import load_device_profile
        from pytestlab.devices.base import _BackendFactory
        from pytestlab.instruments.backends.lamb import LambBackend

        config = load_device_profile(profile_key_or_path)
        model_name = str(getattr(config, "model", Path(profile_key_or_path).stem))
        effective_serial = serial_number or getattr(config, "serial_number", None)
        backend_override = _BackendFactory(
            lambda: LambBackend(
                address=address,
                url=lamb_url,
                timeout_ms=timeout_ms,
                model_name=model_name,
                serial_number=effective_serial,
            )
        )
        backend_type_hint = None
    return AutoInstrument.from_config(
        profile_key_or_path,
        simulate=False,
        address_override=address,
        timeout_override_ms=timeout_ms,
        backend_type_hint=backend_type_hint,
        backend_override=backend_override,
        serial_number=serial_number,
    )


def _declared_operation(device: Any, operation_id: str) -> Any:
    """Return an exact declared descriptor; never infer operations by getattr."""
    for descriptor in device.operation_descriptors():
        if descriptor.operation_id == operation_id:
            return descriptor
    raise ValueError(f"Operation '{operation_id}' is not declared by the driver.")


def _preflight_operation_call(device: Any, descriptor: Any, params: dict[str, Any]) -> None:
    """Validate operation support, arguments, and Python call shape offline."""
    operation_id = str(descriptor.operation_id)
    if getattr(descriptor, "python_only", False):
        reason = (
            "requires caller-provided Python objects"
            if getattr(descriptor, "python_arguments", ())
            else "is available only as a direct Python call"
        )
        raise OperationDiscoveryError(
            f"Operation '{operation_id}' {reason}. Call its typed method directly.",
            code="python_only_operation",
            operation_id=operation_id,
        )
    description = device.describe_operation(operation_id)
    support = description.get("support", {})
    if isinstance(support, dict) and not support.get("supported", True):
        raise ValueError(support.get("reason") or f"Operation '{operation_id}' is unsupported.")
    method_name = str(descriptor.public_method or operation_id)
    if method_name.startswith("_"):
        raise ValueError(f"Operation '{operation_id}' resolves to a private method.")
    method = getattr(device, method_name, None)
    if not callable(method):
        raise ValueError(f"Declared public method '{method_name}' is unavailable.")
    options = getattr(getattr(device, "config", None), "operation_options", None)
    operation_lookup = getattr(options, "operation", None)
    operation = operation_lookup(operation_id) if callable(operation_lookup) else None
    if operation is not None:
        resolver = getattr(device, "_resolve_operation_arguments", None)
        if callable(resolver):
            resolver(operation_id, params)
    if method_name == "execute_profile_operation":
        return
    inspect.signature(method).bind(**params)


@instrument_app.command("execute-operation")
def instrument_execute_operation(
    profile_key_or_path: Annotated[str, typer.Argument(help="Profile key or YAML path.")],
    operation_id: Annotated[str, typer.Argument(help="Declared operation ID to execute.")],
    params: Annotated[
        str | None, typer.Option("--params", help="JSON object containing operation parameters.")
    ] = None,
    safety_context: Annotated[
        str | None,
        typer.Option(
            "--safety-context", help="JSON object containing explicit safety-context approvals."
        ),
    ] = None,
    address: Annotated[
        str | None,
        typer.Option(
            "--address",
            "-a",
            help="Real instrument address. For LAMB, this is the server-side resource string.",
        ),
    ] = None,
    backend: Annotated[
        str, typer.Option("--backend", help="Real backend to use: visa or lamb.")
    ] = "lamb",
    lamb_url: Annotated[
        str | None,
        typer.Option(
            "--lamb-url",
            help="LAMB server base URL. Defaults to LAMB_SERVER or http://lamb-server:8000.",
        ),
    ] = None,
    serial_number: Annotated[
        str | None,
        typer.Option("--serial-number", "--serial", help="Instrument serial number for LAMB."),
    ] = None,
    timeout_ms: Annotated[
        int, typer.Option("--timeout-ms", help="Communication timeout for the real instrument.")
    ] = 5000,
):
    """Execute one declared profile or driver operation on a real instrument."""
    try:
        parsed_params = _parse_json_object(params, "--params")
        parsed_context = _parse_json_object(safety_context, "--safety-context")
    except ValueError as exc:
        code = "invalid_safety_context" if "safety-context" in str(exc) else "invalid_params"
        _print_execute_operation_error(code, str(exc))
        raise typer.Exit(code=1) from None
    backend_lc = backend.lower()
    if backend_lc not in {"visa", "lamb"}:
        _print_execute_operation_error("invalid_backend", "--backend must be 'visa' or 'lamb'.")
        raise typer.Exit(code=1)
    if backend_lc == "visa" and not address:
        _print_execute_operation_error(
            "missing_address", "--address is required for --backend visa."
        )
        raise typer.Exit(code=1)
    if timeout_ms <= 0:
        _print_execute_operation_error("invalid_timeout", "--timeout-ms must be positive.")
        raise typer.Exit(code=1)
    device = None
    try:
        device = _operation_instrument(
            profile_key_or_path,
            backend=backend_lc,
            address=address,
            lamb_url=lamb_url,
            serial_number=serial_number,
            timeout_ms=timeout_ms,
        )
        descriptor = _declared_operation(device, operation_id)
        _preflight_operation_call(device, descriptor, parsed_params)
        method_name = str(descriptor.public_method or operation_id)
        method = getattr(device, method_name)
        if method_name == "execute_profile_operation":
            result = method(operation_id, safety_context=parsed_context, **parsed_params)
        else:
            result = method(**parsed_params)
    except FileNotFoundError:
        _print_execute_operation_error(
            "profile_not_found", f"Profile '{profile_key_or_path}' was not found."
        )
        raise typer.Exit(code=1) from None
    except Exception as exc:
        message = str(exc)
        lowered = message.lower()
        if isinstance(exc, OperationDiscoveryError) and exc.code == "python_only_operation":
            error_code = exc.code
        elif "not declared" in lowered:
            error_code = "unknown_operation"
        elif "safety context" in lowered:
            error_code = "missing_safety_context"
        elif "invalid parameter" in lowered or isinstance(exc, TypeError):
            error_code = "invalid_parameters"
        elif "unsupported" in lowered:
            error_code = "unsupported_operation"
        else:
            error_code = "operation_error"
        _print_execute_operation_error(error_code, message, operation_id=operation_id)
        raise typer.Exit(code=1) from None
    finally:
        if device is not None:
            _close_existing_backend(device)
    _print_operation_json({"operation_id": operation_id, "result": result})


def _active_scpi_blocks(
    scpi_section: dict[str, Any], *, variant: str | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    variants = scpi_section.get("variants")
    if isinstance(variants, dict):
        variant = variant or scpi_section.get("default_variant")
        if not variant:
            raise ValueError("SCPI section defines variants but no default_variant.")
        selected = variants.get(variant)
        if not isinstance(selected, dict):
            raise ValueError(f"SCPI default_variant {variant!r} is not defined.")
        scpi_section = selected
    commands = scpi_section.get("commands") or {}
    queries = scpi_section.get("queries") or {}
    if not isinstance(commands, dict) or not isinstance(queries, dict):
        raise ValueError("SCPI commands and queries must be mappings.")
    return commands, queries


def _template_placeholders(raw_spec: Any) -> set[str]:
    import string

    if isinstance(raw_spec, str):
        templates = [raw_spec]
    elif isinstance(raw_spec, dict):
        sequence = raw_spec.get("sequence")
        template = raw_spec.get("template") or raw_spec.get("command") or raw_spec.get("query")
        if isinstance(sequence, list):
            templates = [item for item in sequence if isinstance(item, str)]
        elif isinstance(template, str):
            templates = [template]
        else:
            templates = []
    else:
        templates = []

    placeholders: set[str] = set()
    formatter = string.Formatter()
    for template in templates:
        for _, field_name, *_ in formatter.parse(template):
            if not field_name:
                continue
            placeholders.add(field_name.split(".", 1)[0].split("[", 1)[0])
    return placeholders


def _sample_value_for_param(
    name: str, raw_spec: Any, parameter_spec: dict[str, Any] | None = None
) -> Any:
    spec: dict[str, Any] = raw_spec if isinstance(raw_spec, dict) else {}

    raw_defaults = spec.get("defaults")
    defaults: dict[str, Any] = raw_defaults if isinstance(raw_defaults, dict) else {}
    if name in defaults:
        return defaults[name]

    if isinstance(parameter_spec, dict):
        if "default" in parameter_spec and parameter_spec["default"] is not None:
            return parameter_spec["default"]
        examples = parameter_spec.get("examples")
        if isinstance(examples, list) and examples:
            return examples[0]
        choices = parameter_spec.get("choices")
        if isinstance(choices, list):
            for choice in choices:
                if isinstance(choice, dict) and "token" in choice:
                    return choice["token"]
                if choice is not None:
                    return choice
        if parameter_spec.get("kind") == "bool":
            return True
        if parameter_spec.get("kind") == "range" and parameter_spec.get("min") is not None:
            min_val = parameter_spec["min"]
            return int(min_val) if float(min_val).is_integer() else float(min_val)
        if parameter_spec.get("kind") == "open_string":
            return "TEST"

    raise ValueError(
        f"No sample value metadata for parameter '{name}'. "
        "Declare a default, examples, choices, range, or validator in the profile."
    )


def _sample_params_for_spec(
    raw_spec: Any, parameter_metadata: dict[str, dict[str, Any]] | None = None
) -> dict[str, Any]:
    parameter_metadata = parameter_metadata or {}
    return {
        name: _sample_value_for_param(name, raw_spec, parameter_metadata.get(name))
        for name in sorted(_template_placeholders(raw_spec))
    }


def _is_bulk_query(message: str) -> bool:
    """Accept one SCPI query, never an embedded write or a service/actuation command."""
    match = re.fullmatch(r"(:?[*A-Z][A-Z0-9*:]*\?)(?: [^;\x00-\x1f\x7f]*)?", message.strip(), re.I)
    if not match:
        return False
    header = match[1].upper().lstrip(":")
    if header in {"*TST?", "*TRG?", "*RST?", "*CLS?"} or re.search(
        r"(?:^|:)(?:SELFTEST|TST|CAL(?:IBRATE)?)(?=[:?])", header
    ):
        return False
    return not re.search(
        r"(?:^|:)(?:ABOR|PRES|RESE|RST|ZERO|INIT|SING|CONT)\w*\?$",
        header,
    )


def _profile_scpi_command_rows(
    profile_key_or_path: str,
    *,
    device: Any | None = None,
    include_writes: bool = False,
    mapping_only: bool = False,
    strict_response: bool,
) -> tuple[Path, list[dict[str, str]], int, int, int]:
    from pytestlab.instruments.scpi_engine import SCPIEngine

    profile_path = _resolve_profile_path(profile_key_or_path)
    with profile_path.open(encoding="utf-8") as fh:
        profile_data = yaml.safe_load(fh) or {}
    if not isinstance(profile_data, dict):
        raise ValueError("Profile file must contain a YAML mapping.")

    scpi_section = profile_data.get("scpi")
    if not isinstance(scpi_section, dict):
        raise ValueError("Profile does not define an scpi section.")

    variant = getattr(getattr(device, "config", None), "scpi_variant", None)
    commands, queries = _active_scpi_blocks(scpi_section, variant=variant)
    engine = SCPIEngine(scpi_section, variant=variant)
    # Live bulk checks must not run state-changing fragments of a direct operation.
    direct_writes: set[str] = set()
    direct_queries: set[str] = set()
    if device is not None:
        descriptors = getattr(device, "operation_descriptors", None)
        options = getattr(getattr(device, "config", None), "operation_options", None)
        operation_lookup = getattr(options, "operation", None)
        if callable(descriptors) and callable(operation_lookup):
            for descriptor in descriptors():
                if not getattr(descriptor, "direct_python_only", False):
                    continue
                operation = operation_lookup(descriptor.operation_id)
                if operation is not None:
                    direct_writes.update(
                        alias for alias in operation.transport.values() if alias in commands
                    )
                    direct_queries.update(
                        alias
                        for key, alias in operation.transport.items()
                        if key in getattr(descriptor, "direct_transport_queries", ())
                        and alias in queries
                    )
    rows: list[dict[str, str]] = []
    failures = 0
    warnings = 0
    skipped = 0

    for kind, entries in (("command", commands), ("query", queries)):
        for alias, raw_spec in entries.items():
            reserved = direct_writes if kind == "command" else direct_queries
            if device is not None and not mapping_only and alias in reserved:
                # Direct fragments need typed validation/context, not raw sample values.
                skipped += 1
                rows.append(
                    {
                        "alias": str(alias),
                        "kind": kind,
                        "status": "skip",
                        "sample": "-",
                        "detail": "reserved for a direct Python operation",
                    }
                )
                continue
            params: dict[str, Any] = {}
            try:
                description = engine.describe(str(alias))
                params = _sample_params_for_spec(
                    raw_spec, cast(dict[str, dict[str, Any]], description["parameters"])
                )
                rendered = engine.build(alias, **params)
                response = ""
                if device is not None and not mapping_only:
                    if kind == "command" or len(rendered) != 1 or not _is_bulk_query(rendered[0]):
                        skipped += 1
                        rows.append(
                            {
                                "alias": str(alias),
                                "kind": kind,
                                "status": "skip",
                                "sample": ", ".join(f"{k}={v!r}" for k, v in params.items()) or "-",
                                "detail": "mapping checked only; raw writes and unsafe queries are never sent",
                            }
                        )
                        continue
                    response = device.query(rendered[0])
                    if kind == "query":
                        if response == "":
                            warnings += 1
                            if strict_response:
                                raise RuntimeError("instrument returned an empty response")
                        elif isinstance(raw_spec, dict) and raw_spec.get("response") is not None:
                            engine.parse(alias, response)
                status = "ok"
                detail = response if response else ", ".join(rendered)
            except Exception as exc:
                failures += 1
                status = "fail"
                detail = str(exc)
            rows.append(
                {
                    "alias": str(alias),
                    "kind": "mapping" if mapping_only else kind,
                    "status": status,
                    "sample": ", ".join(f"{k}={v!r}" for k, v in params.items()) or "-",
                    "detail": detail,
                }
            )

    return profile_path, rows, failures, warnings, skipped


def _sample_semantic_operation_arguments(
    description: dict[str, Any],
) -> dict[str, Any]:
    """Build the smallest semantic call from an operation description.

    This is deliberately driven by the public description rather than by the
    profile's private transport mappings.  Optional parameters are omitted;
    required enumerable parameters use their first supported option.
    """
    keyword_arguments: dict[str, Any] = {}
    for name, raw in description.get("parameters", {}).items():
        if not isinstance(raw, dict) or not raw.get("required", True):
            continue
        options = raw.get("options")
        if isinstance(options, list) and options:
            option = options[0]
            value = option.get("value") if isinstance(option, dict) else option
        elif raw.get("default") is not None:
            value = raw["default"]
        elif raw.get("kind") in {"range", "integer"}:
            value = raw.get("constraints", {}).get("min")
            if isinstance(value, float) and value.is_integer():
                value = int(value)
        else:
            raise ValueError(f"No semantic sample value for required parameter '{name}'.")
        if value is None:
            raise ValueError(f"No semantic sample value for required parameter '{name}'.")
        keyword_arguments[name] = value
    return keyword_arguments


def _semantic_operation_rows(
    device: Any,
    *,
    include_writes: bool,
    skip_operations: Mapping[str, str] | None = None,
) -> tuple[list[dict[str, str]], int, int, int]:
    """Exercise supported high-level read operations using semantic values.

    Profile mapping checks remain separate and continue to cover every private
    mapping.  This second pass verifies the public operation boundary as well.
    """
    import inspect

    rows: list[dict[str, str]] = []
    failures = warnings = skipped = 0
    descriptors = getattr(device, "operation_descriptors", lambda: ())()
    described_methods: set[str] = set()
    for descriptor in descriptors:
        operation_id = str(descriptor.operation_id)
        method_name = str(descriptor.public_method or operation_id)
        described_methods.add(method_name)
        safety = str(descriptor.safety_class)
        method = getattr(device, method_name, None)
        if method is None:
            # A descriptor without a public method is a contract failure when
            # enabled, but optional unsupported legacy descriptors are skipped.
            if descriptor.required:
                failures += 1
                status = "fail"
                detail = f"public operation method '{method_name}' is unavailable"
            else:
                skipped += 1
                status = "skip"
                detail = "optional operation has no public method"
            rows.append(
                {
                    "alias": operation_id,
                    "kind": "operation",
                    "status": status,
                    "sample": "-",
                    "detail": detail,
                }
            )
            continue
        try:
            description = device.describe_operation(operation_id)
            support = description.get("support", {})
            if not support.get("supported", True):
                required = bool(support.get("required", descriptor.required))
                if required:
                    failures += 1
                    status = "fail"
                    detail = support.get("reason") or "required operation unsupported by profile"
                else:
                    skipped += 1
                    status = "skip"
                    detail = "optional operation unsupported by profile"
                rows.append(
                    {
                        "alias": operation_id,
                        "kind": "operation",
                        "status": status,
                        "sample": "-",
                        "detail": detail,
                    }
                )
                continue
            if getattr(descriptor, "python_only", False):
                skipped += 1
                rows.append(
                    {
                        "alias": operation_id,
                        "kind": "operation",
                        "status": "skip",
                        "sample": "-",
                        "detail": (
                            "requires caller-provided Python objects; call its typed method"
                            if getattr(descriptor, "python_arguments", ())
                            else "available only as a direct Python call"
                        ),
                    }
                )
                continue
            if method_name == "execute_profile_operation":
                execution = description.get("execution") or {}
                required_context = execution.get("requires_context", [])
                if required_context or safety != "read":
                    skipped += 1
                    rows.append(
                        {
                            "alias": operation_id,
                            "kind": "operation",
                            "status": "skip",
                            "sample": "-",
                            "detail": (
                                "requires explicit safety context; use instrument execute-operation"
                                if required_context
                                else "state-changing profile operation skipped; use instrument execute-operation"
                            ),
                        }
                    )
                    continue
            skip_reason = (skip_operations or {}).get(operation_id)
            if safety != "read":
                skip_reason = skip_reason or (
                    "no qualified guarded live write; mapping only"
                    if include_writes
                    else "state-changing operation skipped"
                )
            if skip_reason is not None:
                skipped += 1
                rows.append(
                    {
                        "alias": operation_id,
                        "kind": "operation",
                        "status": "skip",
                        "sample": "-",
                        "detail": skip_reason,
                    }
                )
                continue
            keyword_arguments = _sample_semantic_operation_arguments(description)
            if method_name == "execute_profile_operation":
                method(operation_id, safety_context={}, **keyword_arguments)
                rows.append(
                    {
                        "alias": operation_id,
                        "kind": "operation",
                        "status": "ok",
                        "sample": ", ".join(f"{k}={v!r}" for k, v in keyword_arguments.items())
                        or "-",
                        "detail": "semantic operation passed",
                    }
                )
                continue
            signature = inspect.signature(method)
            positional: list[Any] = []
            keywords: dict[str, Any] = {}
            for name, parameter in signature.parameters.items():
                if name not in keyword_arguments:
                    continue
                value = keyword_arguments[name]
                # Profiles describe channels semantically (for example
                # ``channel_1``), while a few stable public facades accept the
                # channel number as an integer.  Adapt only at this Python
                # signature boundary; never inspect or manufacture transport
                # values here.
                if parameter.annotation in (int, "int") and isinstance(value, str):
                    match = re.fullmatch(r"channel[_ -]?(\d+)", value, re.IGNORECASE)
                    if match:
                        value = int(match.group(1))
                if parameter.kind is inspect.Parameter.POSITIONAL_ONLY:
                    positional.append(value)
                elif parameter.kind is inspect.Parameter.VAR_POSITIONAL:
                    if isinstance(value, list | tuple):
                        positional.extend(value)
                    else:
                        positional.append(value)
                else:
                    keywords[name] = value
            method(*positional, **keywords)
            rows.append(
                {
                    "alias": operation_id,
                    "kind": "operation",
                    "status": "ok",
                    "sample": ", ".join(f"{k}={v!r}" for k, v in keyword_arguments.items()) or "-",
                    "detail": "semantic operation passed",
                }
            )
        except Exception as exc:
            failures += 1
            rows.append(
                {
                    "alias": operation_id,
                    "kind": "operation",
                    "status": "fail",
                    "sample": "-",
                    "detail": str(exc),
                }
            )
    coverage_rows, coverage_failures = _public_method_coverage_rows(device, described_methods)
    rows.extend(coverage_rows)
    failures += coverage_failures
    return rows, failures, warnings, skipped


def _public_method_coverage_rows(
    device: Any, described_methods: set[str]
) -> tuple[list[dict[str, str]], int]:
    """Report profile-backed public methods missing semantic descriptors.

    ``check-commands`` proves that every private profile command renders, but it
    cannot prove that a public method has a discoverable semantic contract.
    Canonical profile operations that name callable public methods must also
    have a static descriptor; diagnostic error retrieval is excluded.
    """
    operation_options = getattr(getattr(device, "config", None), "operation_options", None)
    operations = getattr(operation_options, "operations", {}) if operation_options else {}
    if not isinstance(operations, dict):
        operations = {}
    rows: list[dict[str, str]] = []
    failures = 0
    for method_name in sorted(set(operations) - described_methods):
        method = getattr(device, method_name, None)
        if not callable(method) or method_name.startswith("_") or method_name == "get_error":
            continue
        failures += 1
        rows.append(
            {
                "alias": method_name,
                "kind": "operation",
                "status": "fail",
                "sample": "-",
                "detail": "public I/O method has no semantic operation descriptor",
            }
        )
    return rows, failures


@device_app.command("status-byte")
def device_status_byte(
    alias: Annotated[str, typer.Argument(help="Resource alias in the bench.")],
    as_json: Annotated[bool, typer.Option("--json")] = False,
    bench_path: Annotated[Path | None, _bench_option()] = None,
):
    """Read a native status byte without issuing a text protocol command."""
    bench = _open_cli_bench(bench_path, aliases={alias})
    try:
        resources = getattr(bench, "resources", None)
        if not isinstance(resources, Mapping):
            resources = getattr(bench, "devices", {})
        resource = resources.get(alias)
        reader = getattr(resource, "read_status_byte", None)
        if not callable(reader):
            raise TypeError(f"Resource '{alias}' does not provide native status-byte reading.")
        value = reader()
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 255:
            raise ValueError("Native status byte must be an integer from 0 to 255.")
        payload = {"status_byte": value, "status_hex": f"0x{value:02X}"}
        typer.echo(json.dumps(payload) if as_json else payload["status_hex"])
    except _CAPABILITY_ERRORS as exc:
        rich.print(f"[bold red]Error: {rich_escape(str(exc))}[/bold red]")
        raise typer.Exit(code=1) from None
    finally:
        _close_cli_bench(bench)


@device_app.command("idn")
def device_idn(
    profile_key_or_path: Annotated[str, typer.Argument(help="Profile key or path.")],
    address: Annotated[
        str | None, typer.Option(help="VISA address. Overrides profile if provided.")
    ] = None,
    simulate: Annotated[bool, typer.Option(help="Run in simulation mode.")] = False,
):
    """Connect to a device and read identity through its profile-defined protocol."""
    _device_idn_impl(profile_key_or_path, address, simulate)


@instrument_app.command("idn")
def instrument_idn(
    profile_key_or_path: Annotated[str, typer.Argument(help="Profile key or path.")],
    address: Annotated[
        str | None, typer.Option(help="VISA address. Overrides profile if provided.")
    ] = None,
    simulate: Annotated[bool, typer.Option(help="Run in simulation mode.")] = False,
):
    """Read instrument identity through its profile-defined protocol."""
    _device_idn_impl(profile_key_or_path, address, simulate)


def _print_instrument_check_table(
    *,
    title: str,
    profile_path: Path,
    rows: list[dict[str, str]],
    failures: int,
    warnings: int,
    skipped: int,
) -> None:
    table = Table(title=f"{title}: {profile_path.name}")
    table.add_column("Alias", style="cyan")
    table.add_column("Kind", style="magenta")
    table.add_column("Status", style="green")
    table.add_column("Sample Params")
    table.add_column("Result")
    for row in rows:
        if row["status"] == "ok":
            status_style = "[green]ok[/green]"
        elif row["status"] == "skip":
            status_style = "[yellow]skip[/yellow]"
        else:
            status_style = "[red]fail[/red]"
        table.add_row(row["alias"], row["kind"], status_style, row["sample"], row["detail"])
    rich.print(table)

    total = len(rows)
    if failures:
        rich.print(f"[bold red]{failures}/{total} instrument command checks failed.[/bold red]")
        raise typer.Exit(code=1)
    notes = []
    if warnings:
        notes.append(f"{warnings} empty query responses")
    if skipped:
        notes.append(f"{skipped} checks skipped")
    note_text = f" ({', '.join(notes)})" if notes else ""
    rich.print(f"[bold green]All {total} instrument command checks passed[/bold green]{note_text}.")


@instrument_app.command("check-commands")
def instrument_check_commands(
    profile_key_or_path: Annotated[str, typer.Argument(help="Profile key or YAML path.")],
):
    """Validate every profile operation mapping without touching an instrument."""
    try:
        profile_path, rows, failures, warnings, skipped = _profile_scpi_command_rows(
            profile_key_or_path,
            strict_response=False,
        )
    except FileNotFoundError:
        rich.print(f"[bold red]Error: Profile '{rich_escape(profile_key_or_path)}' not found.[/]")
        raise typer.Exit(code=1) from None
    except Exception as exc:
        rich.print(f"[bold red]Instrument command check failed: {rich_escape(str(exc))}[/]")
        raise typer.Exit(code=1) from None

    _print_instrument_check_table(
        title="Instrument Command Build Check",
        profile_path=profile_path,
        rows=rows,
        failures=failures,
        warnings=warnings,
        skipped=skipped,
    )


@instrument_app.command("check-operation-contract")
def instrument_check_operation_contract(
    profile_key_or_path: Annotated[str, typer.Argument(help="Profile key or YAML path.")],
    strict: Annotated[
        bool,
        typer.Option(
            "--strict", help="Exit non-zero when enabled operations miss required aliases."
        ),
    ] = False,
    check_parameters: Annotated[
        bool,
        typer.Option(
            "--check-parameters",
            help="Also require declared operation parameters to have SCPI metadata.",
        ),
    ] = False,
):
    """Check the loaded profile against its driver's high-level operation contract."""

    try:
        from pytestlab import AutoInstrument

        instrument = AutoInstrument.from_config(profile_key_or_path, simulate=True)
        report = instrument.validate_operation_contract(
            strict=False, include_unsupported=True, check_parameters=check_parameters
        )
    except FileNotFoundError:
        rich.print(f"[bold red]Error: Profile '{rich_escape(profile_key_or_path)}' not found.[/]")
        raise typer.Exit(code=1) from None
    except Exception as exc:
        rich.print(f"[bold red]Operation contract check failed: {rich_escape(str(exc))}[/]")
        raise typer.Exit(code=1) from None

    table = Table(title=f"Instrument Operation Contract Check: {instrument.config.model}")
    table.add_column("Operation", style="cyan")
    table.add_column("Capability", style="magenta")
    table.add_column("Required")
    table.add_column("Status", style="green")
    table.add_column("Reason")
    table.add_column("Missing Semantic Parameters")

    missing_required_enabled = 0
    for operation_id, operation_report in report.items():
        descriptor = instrument.describe_operation(operation_id)
        missing_parameters = operation_report.get("missing_parameters", [])
        capability = descriptor["capability"] or "-"
        required = bool(operation_report["required"])
        if not operation_report["capability_enabled"]:
            status = "[yellow]unsupported[/yellow]"
        elif not operation_report["supported"]:
            if required:
                status = "[red]fail[/red]"
                missing_required_enabled += 1
            else:
                status = "[yellow]warn[/yellow]"
        else:
            status = "[green]ok[/green]"
        table.add_row(
            operation_id,
            capability,
            "yes" if required else "no",
            status,
            operation_report.get("reason") or "-",
            ", ".join(missing_parameters) or "-",
        )
    rich.print(table)

    if missing_required_enabled:
        rich.print(
            f"[bold red]{missing_required_enabled} required enabled operations are unsupported.[/bold red]"
        )
        if strict:
            raise typer.Exit(code=1)
    else:
        rich.print("[bold green]All enabled operation contract checks passed[/bold green].")


@instrument_app.command("list-operations")
def instrument_list_operations(
    profile_key_or_path: Annotated[str, typer.Argument(help="Profile key or YAML path.")],
    include_unsupported: Annotated[
        bool,
        typer.Option(
            "--include-unsupported/--supported-only",
            help="Include operations unsupported by this profile (default).",
        ),
    ] = True,
    grouped: Annotated[
        bool,
        typer.Option("--grouped", help="Return operation descriptions grouped by capability."),
    ] = False,
    group: Annotated[
        str | None,
        typer.Option("--group", help="Filter by semantic group ID; implies --grouped."),
    ] = None,
    scope: Annotated[
        str | None,
        typer.Option("--scope", help="Filter to family or model operations; implies --grouped."),
    ] = None,
):
    """List semantic operations declared by a profile without touching hardware."""

    try:
        if scope not in (None, "family", "model"):
            raise ValueError("--scope must be 'family' or 'model'.")
        instrument = _load_instrument_profile(profile_key_or_path)
        if grouped or group is not None or scope is not None:
            result = instrument.describe_operations(
                group=group,
                scope=scope,
                include_unsupported=include_unsupported,
            )
        else:
            result = instrument.list_operations(include_unsupported=include_unsupported)
    except Exception as exc:
        _print_operation_error(exc)
        raise typer.Exit(code=1) from None
    _print_operation_json(result)


@instrument_app.command("describe-operation")
def instrument_describe_operation(
    profile_key_or_path: Annotated[str, typer.Argument(help="Profile key or YAML path.")],
    operation_id: Annotated[str, typer.Argument(help="Operation ID to describe.")],
    context: Annotated[
        str | None,
        typer.Option("--context", help="JSON object containing dependent parameter values."),
    ] = None,
    include_unsupported: Annotated[
        bool,
        typer.Option("--include-unsupported", help="Include disabled options and reasons."),
    ] = False,
):
    """Describe one semantic operation for a profile, offline."""

    try:
        parsed_context = _parse_operation_context(context)
        instrument = _load_instrument_profile(profile_key_or_path)
        result = instrument.describe_operation(
            operation_id,
            context=parsed_context,
            include_unsupported=include_unsupported,
        )
    except Exception as exc:
        _print_operation_error(exc)
        raise typer.Exit(code=1) from None

    _print_operation_json(result)


@instrument_app.command("list-options")
def instrument_list_options(
    profile_key_or_path: Annotated[str, typer.Argument(help="Profile key or YAML path.")],
    operation_id: Annotated[str, typer.Argument(help="Operation ID.")],
    parameter: Annotated[str, typer.Argument(help="Operation parameter name.")],
    context: Annotated[
        str | None,
        typer.Option("--context", help="JSON object containing dependent parameter values."),
    ] = None,
    include_unsupported: Annotated[
        bool,
        typer.Option("--include-unsupported", help="Include disabled options and reasons."),
    ] = False,
):
    """List semantic profile options without constructing a simulator or backend."""

    try:
        parsed_context = _parse_operation_context(context)
        instrument = _load_instrument_profile(profile_key_or_path)
        result = instrument.list_operation_options(
            operation_id,
            parameter,
            context=parsed_context,
            include_unsupported=include_unsupported,
        )
    except Exception as exc:
        _print_operation_error(exc)
        raise typer.Exit(code=1) from None

    _print_operation_json(result)


def _bundled_full_test_profile(profile_path: Path) -> bool:
    return profile_path.resolve().is_relative_to(Path(__file__).resolve().parent / "profiles")


def _full_test_is_psu(device: Any) -> bool:
    from pytestlab.config.power_supply_config import PowerSupplyConfig

    return isinstance(getattr(device, "config", None), PowerSupplyConfig)


def _full_test_semantic_rows(
    device: Any, *, include_writes: bool, profile_path: Path
) -> tuple[list[dict[str, str]], int, int, int]:
    if not _bundled_full_test_profile(profile_path):
        return (
            [
                {
                    "alias": "live operations",
                    "kind": "operation",
                    "status": "skip",
                    "sample": "-",
                    "detail": "custom profile: no qualified live operations; mappings checked offline",
                }
            ],
            0,
            0,
            1,
        )
    if not _full_test_is_psu(device):
        return _semantic_operation_rows(device, include_writes=include_writes)

    # The read-only configuration snapshot measures actual V/I; it cannot restore setpoints.
    skip_operations = {
        "set_voltage": "programmed voltage readback/restoration not qualified; no live write",
        "set_current": "programmed current readback/restoration not qualified; no live write",
        "identify": "use the separate PSU identity and status checks",
        "get_configuration": "use the separate per-channel PSU status checks",
        "measure_voltage": "use the separate per-channel PSU status checks",
        "measure_current": "use the separate per-channel PSU status checks",
        "get_output_state": "use the separate per-channel PSU status checks",
    }
    rows, failures, warnings, skipped = _semantic_operation_rows(
        device, include_writes=include_writes, skip_operations=skip_operations
    )
    # Only this stock driver/profile path has single, explicitly channel-addressed reads.
    # For example, the NGE102B profile needs a write to select a channel before reading it.
    supported_profile = _resolve_profile_path("keysight/EDU36311A").resolve()
    if profile_path.resolve() != supported_profile:
        rows.append(
            {
                "alias": "channels",
                "kind": "PSU readback",
                "status": "skip",
                "sample": "-",
                "detail": "channel-addressed readback not qualified for this profile",
            }
        )
        return rows, failures, warnings, skipped + 1

    try:
        identity = device.id()
        fields = [field.strip() for field in identity.split(",")]
        expected_serial = device.config.serial_number
        if (
            len(fields) < 4
            or fields[0].upper() not in {"KEYSIGHT", "KEYSIGHT TECHNOLOGIES"}
            or fields[1].upper() != "EDU36311A"
            or not fields[2]
            or (expected_serial is not None and fields[2] != expected_serial)
        ):
            raise ValueError("live model or serial does not match the selected profile and binding")
    except Exception as exc:
        rows.append(
            {
                "alias": "identify",
                "kind": "PSU readback",
                "status": "fail",
                "sample": "-",
                "detail": str(exc),
            }
        )
        return rows, failures + 1, warnings, skipped
    rows.append(
        {
            "alias": "identify",
            "kind": "PSU readback",
            "status": "ok",
            "sample": "-",
            "detail": identity,
        }
    )

    limit_spec = getattr(device, "safety_limits", None)
    channel_limits = (limit_spec.channels or {}) if limit_spec is not None else {}
    channel_numbers = set(range(1, len(device.config.channels or []) + 1))
    if unknown := set(channel_limits) - channel_numbers:
        rows.append(
            {
                "alias": "safety_limits",
                "kind": "bench limits",
                "status": "fail",
                "sample": "-",
                "detail": f"limits name unavailable channels: {sorted(unknown)}",
            }
        )
        return rows, failures + 1, warnings, skipped
    for channel in sorted(channel_numbers):
        try:
            state = device.get_output_state(channel)
            volts = device.read_voltage(channel).nominal
            amps = device.read_current(channel).nominal
            if type(state) is not bool or not (math.isfinite(volts) and math.isfinite(amps)):
                raise ValueError("output state or voltage/current reading is not valid")
            state_label = "on" if state else "off"
            status, detail = (
                "ok",
                f"output {state_label}; measured {volts:g} V, {amps:g} A (not setpoints)",
            )
            if limits := channel_limits.get(channel):
                for name, value, unit in (("voltage", volts, "V"), ("current", amps, "A")):
                    bound = getattr(limits, name, None) or {}
                    max_value, max_abs = bound.get("max"), bound.get("max_abs")
                    if max_value is not None and value > max_value:
                        detail += (
                            f"; observed {name} exceeds the configured {max_value:g} {unit} cap"
                        )
                        status = "fail"
                    if max_abs is not None and abs(value) > max_abs:
                        detail += f"; absolute {name} exceeds the configured {max_abs:g} {unit} cap"
                        status = "fail"
            if status == "fail":
                failures += 1
        except Exception as exc:
            failures += 1
            status, detail = "fail", f"PSU state/readback not verified: {exc}"
        rows.append(
            {
                "alias": f"channel {channel}",
                "kind": "PSU readback",
                "status": status,
                "sample": "-",
                "detail": detail,
            }
        )
    return rows, failures, warnings, skipped


def _full_test_bench(
    alias: str, bench_path: Path | None, *, include_writes: bool, strict_response: bool
) -> None:
    from pytestlab.config.bench_loader import entry_backend_options
    from pytestlab.config.bench_loader import load_bench_yaml

    bench = None
    try:
        resolved = resolve_bench_path(bench_path)
        config = load_bench_yaml(resolved)
        entry = config.devices.get(alias) or config.instruments.get(alias)
        if entry is None or not entry.source:
            raise ValueError(f"No instrument profile for bench alias '{alias}'.")
        profile_source = str(entry.resolved_source(base_path=resolved.parent))
        profile_path = _resolve_profile_path(profile_source)
        device = None
        if _bundled_full_test_profile(profile_path):
            bench = _open_cli_bench(resolved, aliases={alias})
            device = bench.instruments.get(alias)
            if device is None:
                raise ValueError(f"Bench resource '{alias}' is not an instrument.")
        profile_path, rows, failures, warnings, skipped = _profile_scpi_command_rows(
            profile_source,
            device=device,
            mapping_only=True,
            strict_response=strict_response,
        )
        if entry.safety_limits is not None:
            limits = device.safety_limits if device is not None else entry.safety_limits
            rich.print(
                "Bench safety limits (not a setpoint or DUT-safety verification): "
                + rich_escape(limits.model_dump_json(exclude_none=True))
            )
        semantic_rows, sf, sw, ss = _full_test_semantic_rows(
            device,
            include_writes=include_writes,
            profile_path=profile_path,
        )
        simulated = config.simulation_only or entry_backend_options(config, entry)[0]
    except (OSError, *_CAPABILITY_ERRORS) as exc:
        rich.print(f"[bold red]Bench instrument full test failed: {rich_escape(str(exc))}[/]")
        raise typer.Exit(code=1) from None
    finally:
        if bench is not None:
            _close_cli_bench(bench)
    _print_instrument_check_table(
        title=f"Bench Instrument Full Test ({alias})" + (" (simulated)" if simulated else ""),
        profile_path=profile_path,
        rows=[*rows, *semantic_rows],
        failures=failures + sf,
        warnings=warnings + sw,
        skipped=skipped + ss,
    )


@instrument_app.command("full-test")
def instrument_full_test(
    profile_key_or_path: Annotated[
        str, typer.Argument(help="Bench alias with --bench, otherwise profile key or YAML path.")
    ],
    bench_path: Annotated[Path | None, _bench_option()] = None,
    address: Annotated[
        str | None,
        typer.Option(
            "--address",
            "-a",
            help="Real instrument address. For LAMB, this is the server-side resource string.",
        ),
    ] = None,
    backend: Annotated[
        str | None,
        typer.Option(
            "--backend",
            help="Profile mode backend: visa or lamb (default).",
        ),
    ] = None,
    lamb_url: Annotated[
        str | None,
        typer.Option(
            "--lamb-url",
            help="LAMB server base URL. Defaults to LAMB_SERVER or http://lamb-server:8000.",
        ),
    ] = None,
    serial_number: Annotated[
        str | None,
        typer.Option(
            "--serial-number",
            "--serial",
            help="Instrument serial number for LAMB auto-connect when no address is provided.",
        ),
    ] = None,
    include_writes: Annotated[
        bool,
        typer.Option(
            "--include-writes",
            help="Request guarded live write coverage. Unsafe or unqualified writes are skipped.",
        ),
    ] = False,
    timeout_ms: Annotated[
        int | None,
        typer.Option("--timeout-ms", help="Profile mode communication timeout (default 5000 ms)."),
    ] = None,
    strict_response: Annotated[
        bool,
        typer.Option("--strict-response", help="Fail when a real query returns an empty response."),
    ] = True,
):
    """Check profile mappings and live reads. Queries can acquire data or consume diagnostics."""
    from pytestlab.devices import AutoDevice

    explicit_target = any(
        value is not None for value in (address, lamb_url, serial_number, backend, timeout_ms)
    )
    if bench_path is not None or (
        os.environ.get("PYTESTLAB_BENCH")
        and not explicit_target
        and re.fullmatch(r"[A-Za-z0-9_-]+", profile_key_or_path)
    ):
        if explicit_target:
            rich.print("[bold red]Error: --bench uses the bench's backend, address and timeout.[/]")
            raise typer.Exit(code=1)
        _full_test_bench(
            profile_key_or_path,
            bench_path,
            include_writes=include_writes,
            strict_response=strict_response,
        )
        return

    backend_lc = (backend or "lamb").lower()
    timeout_ms = 5000 if timeout_ms is None else timeout_ms
    if backend_lc not in {"visa", "lamb"}:
        rich.print("[bold red]Error: --backend must be 'visa' or 'lamb'.[/bold red]")
        raise typer.Exit(code=1)
    if backend_lc == "visa" and not address:
        rich.print("[bold red]Error: --address is required for --backend visa.[/bold red]")
        raise typer.Exit(code=1)

    device = None
    try:
        profile_path = _resolve_profile_path(profile_key_or_path)
        bundled = _bundled_full_test_profile(profile_path)
        backend_override = None
        backend_type_hint = backend_lc
        if bundled and backend_lc == "lamb":
            from pytestlab.instruments.backends.lamb import LambBackend

            with profile_path.open(encoding="utf-8") as fh:
                profile_data = yaml.safe_load(fh) or {}
            model_name = str(profile_data.get("model") or profile_path.stem)
            backend_override = LambBackend(
                address=address,
                url=lamb_url,
                timeout_ms=timeout_ms,
                model_name=model_name,
                serial_number=serial_number,
            )
            backend_type_hint = None
        if bundled:
            device = AutoDevice.from_config(
                profile_key_or_path,
                simulate=False,
                address_override=address,
                timeout_override_ms=timeout_ms,
                backend_type_hint=backend_type_hint,
                backend_override=backend_override,
            )
            device.connect_backend()
        profile_path, rows, failures, warnings, skipped = _profile_scpi_command_rows(
            profile_key_or_path,
            device=device,
            mapping_only=not bundled or _full_test_is_psu(device),
            strict_response=strict_response,
        )
        semantic_rows, semantic_failures, semantic_warnings, semantic_skipped = (
            _full_test_semantic_rows(
                device, include_writes=include_writes, profile_path=profile_path
            )
        )
        rows.extend(semantic_rows)
        failures += semantic_failures
        warnings += semantic_warnings
        skipped += semantic_skipped
    except FileNotFoundError:
        rich.print(f"[bold red]Error: Profile '{rich_escape(profile_key_or_path)}' not found.[/]")
        raise typer.Exit(code=1) from None
    except Exception as exc:
        rich.print(f"[bold red]Real instrument full test failed: {rich_escape(str(exc))}[/]")
        raise typer.Exit(code=1) from None
    finally:
        if device is not None:
            device.close()

    _print_instrument_check_table(
        title="Real Instrument Full Test" if bundled else "Instrument Full Test (mapping only)",
        profile_path=profile_path,
        rows=rows,
        failures=failures,
        warnings=warnings,
        skipped=skipped,
    )


@instrument_app.command("verify-profile")
def instrument_verify_profile(
    profile_key_or_path: Annotated[str, typer.Argument(help="Profile key or path.")],
    address: Annotated[
        str | None, typer.Option(help="VISA address. Overrides profile if provided.")
    ] = None,
    probe_mode: Annotated[
        str,
        typer.Option(
            help="Verification probe mode: 'read-only' or 'safe-write'.",
        ),
    ] = "read-only",
    allow_output_enable: Annotated[
        bool,
        typer.Option(help="Allow output-affecting checks for devices such as PSUs or AWGs."),
    ] = False,
    timeout_ms: Annotated[
        int | None,
        typer.Option(help="Communication timeout override in milliseconds."),
    ] = None,
    fail_fast: Annotated[
        bool,
        typer.Option(help="Stop after the first failed verification check."),
    ] = False,
):
    """Verify that a real instrument adheres to the selected YAML profile."""
    from pytestlab.verification import render_verification_report
    from pytestlab.verification import verify_instrument_profile

    if probe_mode not in {"read-only", "safe-write"}:
        rich.print("[bold red]Error:[/] --probe-mode must be 'read-only' or 'safe-write'.")
        raise typer.Exit(code=2)

    try:
        report = verify_instrument_profile(
            profile_key_or_path,
            address=address,
            probe_mode=cast(Any, probe_mode),
            allow_output_enable=allow_output_enable,
            timeout_ms=timeout_ms,
            fail_fast=fail_fast,
        )
    except FileNotFoundError:
        rich.print(
            f"[bold red]Error:[/] Profile '{rich_escape(str(profile_key_or_path))}' was not found."
        )
        raise typer.Exit(code=2) from None
    except Exception as e:
        rich.print(f"[bold red]Verification setup failed:[/] {rich_escape(str(e))}")
        raise typer.Exit(code=2) from None

    render_verification_report(report)
    if report.has_failures:
        raise typer.Exit(code=1)
    raise typer.Exit(code=0)


@instrument_app.command("test")
def instrument_test(
    profile_or_kind: Annotated[
        str,
        typer.Argument(help="Profile key/path, or a legacy instrument kind followed by a profile."),
    ],
    profile: Annotated[
        str | None,
        typer.Argument(help="Profile key/path when using the legacy two-argument form."),
    ] = None,
):
    """Run the source checkout's profile-selected real-hardware pytest suite."""
    tests_dir = Path(__file__).parent.parent / "tests" / "instruments"
    if not tests_dir.is_dir():
        rich.print(
            "[bold red]The instrument test suite is not installed with pytestlab.[/bold red]\n"
            "Run this command from a source checkout, or use 'instrument full-test' "
            "for installed-package SCPI checks."
        )
        raise typer.Exit(code=1)

    legacy_aliases = {
        "mm": "multimeter",
        "multimeter": "multimeter",
        "supply": "psu",
        "power": "psu",
        "power-supply": "psu",
        "psu": "psu",
        "scope": "oscilloscope",
        "osc": "oscilloscope",
        "oscilloscope": "oscilloscope",
        "waveform": "awg",
        "generator": "awg",
        "awg": "awg",
        "dc-load": "dc_active_load",
        "load": "dc_active_load",
    }
    suites = {
        "multimeter": "test_multimeter.py",
        "power_supply": "test_psu.py",
        "oscilloscope": "test_oscilloscope.py",
        "waveform_generator": "test_awg.py",
        "dc_active_load": "test_dc_load.py",
    }

    profile_value = profile_or_kind if profile is None else profile
    legacy_kind = None if profile is None else profile_or_kind.lower()
    if legacy_kind == "all":
        rich.print(
            "[bold red]'all' cannot use one profile for multiple instrument kinds.[/bold red]"
        )
        raise typer.Exit(code=1)

    from pytestlab.config.loader import load_device_profile

    try:
        config = load_device_profile(profile_value)
    except Exception as exc:
        rich.print(f"[bold red]Could not load profile: {rich_escape(str(exc))}[/bold red]")
        raise typer.Exit(code=1) from None

    device_type = str(config.device_type).lower()
    filename = suites.get(device_type)
    if filename is None:
        rich.print(
            "[bold red]No real-hardware pytest suite is registered for profile "
            f"device_type '{rich_escape(device_type)}'.[/bold red]"
        )
        raise typer.Exit(code=1)

    if legacy_kind is not None:
        requested_type = legacy_aliases.get(legacy_kind, legacy_kind)
        expected_legacy_type = {
            "power_supply": "psu",
            "waveform_generator": "awg",
        }.get(device_type, device_type)
        if requested_type != expected_legacy_type:
            rich.print(
                f"[bold red]Requested kind '{rich_escape(profile_or_kind)}' does not match "
                f"profile device_type '{rich_escape(device_type)}'.[/bold red]"
            )
            raise typer.Exit(code=1)

    targets = [str(tests_dir / filename)]
    previous_profile = os.environ.get("PYTESTLAB_INSTRUMENT_TEST_PROFILE")
    os.environ["PYTESTLAB_INSTRUMENT_TEST_PROFILE"] = profile_value
    try:
        import pytest

        rich.print("[bold cyan]Running real-hardware tests:[/bold cyan] " + ", ".join(targets))
        exit_code = int(pytest.main(["-m", "requires_real_hw", *targets]))
    finally:
        if previous_profile is None:
            os.environ.pop("PYTESTLAB_INSTRUMENT_TEST_PROFILE", None)
        else:
            os.environ["PYTESTLAB_INSTRUMENT_TEST_PROFILE"] = previous_profile
    raise typer.Exit(code=exit_code)


def _choose_bench_argument(positional: Path | None, option: Path | None) -> Path | None:
    if positional is not None and option is not None:
        raise typer.BadParameter("Specify the bench path once, as PATH or --bench.")
    return option if option is not None else positional


@bench_app.command("ls")
def bench_ls(
    path: Annotated[Path | None, typer.Argument(help="Bench descriptor (optional).")] = None,
    bench_path: Annotated[Path | None, _bench_option()] = None,
    as_json: Annotated[
        bool, typer.Option("--json", help="Emit machine-readable inventory.")
    ] = False,
):
    """List declared bench resources without probing or connecting."""
    from pytestlab.config.bench_loader import load_bench_yaml

    explicit = _choose_bench_argument(path, bench_path)
    try:
        resolved = resolve_bench_path(explicit)
        config = load_bench_yaml(resolved)
        rows: list[dict[str, Any]] = []
        for kind, entries in (("device", config.devices), ("instrument", config.instruments)):
            for alias, entry in entries.items():
                backend = entry.backend or {}
                resource_string = backend.get("resource_string")
                rows.append(
                    {
                        "alias": alias,
                        "kind": kind,
                        "source": entry.source or None,
                        "address": entry.address
                        or (resource_string if isinstance(resource_string, str) else None),
                        "backend": backend.get("type"),
                        "simulate": config.simulate if entry.simulate is None else entry.simulate,
                    }
                )

        if as_json:
            typer.echo(
                json.dumps(
                    {"bench": config.bench_name, "path": str(resolved), "resources": rows},
                    sort_keys=True,
                )
            )
            return

        table = Table(title=f"Bench: {config.bench_name}")
        for label in ("Alias", "Profile / file", "Kind", "Address", "Backend", "Simulate flag"):
            table.add_column(label)
        for row in rows:
            table.add_row(
                str(row["alias"]),
                str(row["source"] or "Inline"),
                str(row["kind"]),
                str(row["address"] or "Unknown"),
                str(row["backend"] or "Unknown"),
                "Not declared" if row["simulate"] is None else str(row["simulate"]),
            )
        rich.print(table)
    except Exception as exc:
        rich.print(f"[bold red]Error listing bench resources: {rich_escape(str(exc))}[/bold red]")
        raise typer.Exit(code=1) from None


@bench_app.command("validate")
def bench_validate_cli(
    path: Annotated[Path | None, typer.Argument(help="Bench descriptor (optional).")] = None,
    strict: Annotated[
        bool,
        typer.Option(
            "--strict", help="Check custom rules, LAMB camera bindings and routes offline."
        ),
    ] = False,
    bench_path: Annotated[Path | None, _bench_option()] = None,
):
    """Validates a bench configuration file (dry-run)."""
    from pytestlab.config.bench_config import BenchConfigExtended
    from pytestlab.config.bench_loader import build_validation_context
    from pytestlab.config.bench_loader import run_custom_validations
    from pytestlab.config.bench_loader import validate_lamb_camera_binding
    from pytestlab.config.camera_config import CameraConfig
    from pytestlab.config.loader import load_device_profile
    from pytestlab.devices.registry import builtin_simulation_scope
    from pytestlab.measurement_plan import validate_declared_measurements
    from pytestlab.measurement_plan import validate_declared_routes

    explicit = _choose_bench_argument(path, bench_path)
    try:
        bench_yaml_path = resolve_bench_path(explicit)
        display_path = explicit if explicit is not None else bench_yaml_path
        with bench_yaml_path.open() as f:
            data = yaml.safe_load(f)
        config = BenchConfigExtended.model_validate(data)
        if strict:
            rich.print(f"Parsed bench descriptor '{rich_escape(str(display_path))}'.")
        else:
            rich.print(f"[bold green]Bench configuration '{display_path}' is valid.[/bold green]")

        with builtin_simulation_scope() if strict else contextlib.nullcontext():
            rich.print("Validating individual device profiles...")
            all_profiles_valid = True
            entries = list(config.devices.items()) + list(config.instruments.items())
            for alias, entry in entries:
                try:
                    profile = None
                    if entry.device_type is None:
                        profile = load_device_profile(
                            entry.resolved_source(base_path=bench_yaml_path.parent)
                        )
                    elif strict:
                        profile = CameraConfig()
                    if strict and profile is not None:
                        try:
                            validate_lamb_camera_binding(config, entry, profile)
                        except ValueError as exc:
                            all_profiles_valid = False
                            rich.print(
                                f"  [bold red]✖ Error:[/bold red] Invalid camera binding for alias "
                                f"'[cyan]{alias}[/cyan]': {rich_escape(str(exc))}"
                            )
                            continue
                    rich.print(
                        f"  [green]✔[/green] {entry.source_kind.title()} '[magenta]{entry.source}[/magenta]' for alias '[cyan]{alias}[/cyan]' loaded successfully."
                    )
                except FileNotFoundError:
                    all_profiles_valid = False
                    rich.print(
                        f"  [bold red]✖ Error:[/bold red] {entry.source_kind.title()} '[magenta]{entry.source}[/magenta]' for alias '[cyan]{alias}[/cyan]' not found."
                    )
                except Exception as e_profile:
                    all_profiles_valid = False
                    rich.print(
                        f"  [bold red]✖ Error:[/bold red] Failed to load {entry.source_kind} '[magenta]{entry.source}[/magenta]' for alias '[cyan]{alias}[/cyan]': {e_profile}"
                    )

            if strict:
                try:
                    run_custom_validations(config, build_validation_context(config))
                except ValueError as exc:
                    all_profiles_valid = False
                    rich.print(
                        f"[bold red]Custom validation failed:[/bold red] {rich_escape(str(exc))}"
                    )

            semantic_errors = validate_declared_measurements(
                config,
                base_path=bench_yaml_path.parent,
                include_route_validation=strict,
                static_profiles_only=strict,
            )
            if semantic_errors:
                all_profiles_valid = False
                rich.print("[bold red]Measurement plan validation failed:[/bold red]")
                for error in semantic_errors:
                    rich.print(f"  [bold red]✖[/bold red] {error}")
            if config.routes:
                rich.print("Validating declared routes...")
                if strict:
                    route_errors = validate_declared_routes(
                        config, base_path=bench_yaml_path.parent
                    )
                    if route_errors:
                        all_profiles_valid = False
                        rich.print("  [bold red]✖[/bold red] Strict route validation failed:")
                        for error in route_errors:
                            rich.print(f"    [bold red]✖[/bold red] {error}")
                    else:
                        for route_name in config.routes:
                            rich.print(
                                f"  [green]✔[/green] Route '[cyan]{route_name}[/cyan]' dry-run validated."
                            )
                else:
                    for route_name in config.routes:
                        rich.print(
                            f"  [yellow]•[/yellow] Route '[cyan]{route_name}[/cyan]' syntax loaded; "
                            "use --strict for pre-hardware route validation."
                        )

            if not all_profiles_valid:
                raise typer.Exit(code=1)
            if strict:
                rich.print(
                    f"[bold green]Strict offline validation passed for "
                    f"'{rich_escape(str(display_path))}'.[/bold green]"
                )

    except typer.Exit:
        raise
    except FileNotFoundError as exc:
        rich.print(f"[bold red]Error: {rich_escape(str(exc))}[/bold red]")
        raise typer.Exit(code=1) from None
    except yaml.YAMLError as e:
        rich.print(f"[bold red]Error parsing YAML file '{bench_yaml_path}': {e}[/bold red]")
        raise typer.Exit(code=1) from None
    except Exception as e:
        rich.print(
            f"[bold red]An unexpected error occurred during bench validation: {e}[/bold red]"
        )
        raise typer.Exit(code=1) from None


@bench_app.command("measurements")
def bench_measurements_cli(
    bench_yaml_path: Annotated[Path, typer.Argument(help="Path to the bench.yaml file.")],
):
    """Lists executable measurements declared in measurement_plan."""
    from pytestlab.config.bench_config import BenchConfigExtended
    from pytestlab.measurement_plan import prepare_declared_measurements

    try:
        with open(bench_yaml_path) as f:
            data = yaml.safe_load(f)
        config = BenchConfigExtended.model_validate(data)
        prepared = prepare_declared_measurements(config, base_path=bench_yaml_path.parent)
        if prepared.errors:
            rich.print("[bold red]Measurement plan validation failed:[/bold red]")
            for error in prepared.errors:
                rich.print(f"  [bold red]✖[/bold red] {error}")
            raise typer.Exit(code=1)
        table = Table(title=f"Measurements: {config.bench_name}")
        table.add_column("Name")
        table.add_column("Resource")
        table.add_column("Target")
        table.add_column("Route")
        table.add_column("Accessories")
        for entry in config.measurement_plan or []:
            if entry.execution_target is None:
                continue
            table.add_row(
                entry.name,
                entry.target_alias,
                entry.execution_target.model_dump_json(),
                entry.route or "-",
                ", ".join(entry.accessories) or "-",
            )
        rich.print(table)
    except typer.Exit:
        raise
    except Exception as e:
        rich.print(f"[bold red]Error listing measurements: {e}[/bold red]")
        raise typer.Exit(code=1) from None


@bench_app.command("measurement")
def bench_measurement_cli(
    bench_yaml_path: Annotated[Path, typer.Argument(help="Path to the bench.yaml file.")],
    name: Annotated[str, typer.Argument(help="Measurement name from measurement_plan.")],
):
    """Describes one declared measurement without touching hardware."""
    from pytestlab.config.bench_config import BenchConfigExtended
    from pytestlab.measurement_plan import describe_declared_measurement
    from pytestlab.measurement_plan import prepare_declared_measurements

    try:
        with open(bench_yaml_path) as f:
            data = yaml.safe_load(f)
        config = BenchConfigExtended.model_validate(data)
        entries = {entry.name: entry for entry in config.measurement_plan or []}
        if name not in entries:
            rich.print(f"[bold red]Measurement '{name}' not found.[/bold red]")
            raise typer.Exit(code=1)
        entry = entries[name]
        prepared = prepare_declared_measurements(config, base_path=bench_yaml_path.parent)
        if prepared.errors:
            rich.print("[bold red]Measurement plan validation failed:[/bold red]")
            for error in prepared.errors:
                rich.print(f"  [bold red]✖[/bold red] {error}")
            raise typer.Exit(code=1)
        rich.print(describe_declared_measurement(entry, prepared.bound_accessories, config.routes))
    except typer.Exit:
        raise
    except Exception as e:
        rich.print(f"[bold red]Error describing measurement: {e}[/bold red]")
        raise typer.Exit(code=1) from None


@bench_app.command("routes")
def bench_routes_cli(
    bench_yaml_path: Annotated[Path, typer.Argument(help="Path to the bench.yaml file.")],
):
    """Lists dry-run routes declared in a bench file."""
    from pytestlab.config.bench_config import BenchConfigExtended
    from pytestlab.measurement_plan import validate_declared_routes

    try:
        with open(bench_yaml_path) as f:
            data = yaml.safe_load(f)
        config = BenchConfigExtended.model_validate(data)
        errors = validate_declared_routes(config, base_path=bench_yaml_path.parent)
        if errors:
            rich.print("[bold red]Route validation failed:[/bold red]")
            for error in errors:
                rich.print(f"  [bold red]✖[/bold red] {error}")
            raise typer.Exit(code=1)
        table = Table(title=f"Routes: {config.bench_name}")
        table.add_column("Name")
        table.add_column("Device")
        table.add_column("Connections")
        table.add_column("Accessories")
        for name, route in config.routes.items():
            connections = "; ".join(
                f"{connection.from_endpoint}->{connection.to}" for connection in route.connects
            )
            table.add_row(
                name,
                route.device or "-",
                connections,
                ", ".join(route.accessories) or "-",
            )
        rich.print(table)
    except typer.Exit:
        raise
    except Exception as e:
        rich.print(f"[bold red]Error listing routes: {e}[/bold red]")
        raise typer.Exit(code=1) from None


@bench_app.command("route")
def bench_route_cli(
    bench_yaml_path: Annotated[Path, typer.Argument(help="Path to the bench.yaml file.")],
    name: Annotated[str, typer.Argument(help="Route name from routes.")],
):
    """Describes one dry-run route without touching hardware."""
    from pytestlab.config.bench_config import BenchConfigExtended
    from pytestlab.measurement_plan import describe_declared_route
    from pytestlab.measurement_plan import validate_declared_routes

    try:
        with open(bench_yaml_path) as f:
            data = yaml.safe_load(f)
        config = BenchConfigExtended.model_validate(data)
        if name not in config.routes:
            rich.print(f"[bold red]Route '{name}' not found.[/bold red]")
            raise typer.Exit(code=1)
        errors = validate_declared_routes(config, base_path=bench_yaml_path.parent)
        if errors:
            rich.print("[bold red]Route validation failed:[/bold red]")
            for error in errors:
                rich.print(f"  [bold red]✖[/bold red] {error}")
            raise typer.Exit(code=1)
        rich.print(describe_declared_route(name, config.routes[name]))
    except typer.Exit:
        raise
    except Exception as e:
        rich.print(f"[bold red]Error describing route: {e}[/bold red]")
        raise typer.Exit(code=1) from None


@bench_app.command("id")
def bench_id_cli(
    bench_yaml_path: Annotated[Path, typer.Argument(help="Path to the bench.yaml file.")],
):
    """Connects to real devices in a bench and prints their *IDN? responses."""
    bench = None
    try:
        bench = _open_cli_bench(bench_yaml_path)
        rich.print(f"Querying *IDN? for devices in bench: [bold]{bench._config.bench_name}[/bold]")

        table = Table(title="Device IDN Responses")
        table.add_column("Alias", style="cyan")
        table.add_column("Profile", style="magenta")
        table.add_column("IDN Response / Status", style="green")

        config_entries = bench._config.devices | bench._config.instruments
        for alias, device in bench.devices.items():
            entry = config_entries[alias]
            is_simulated = bench._config.simulate
            if entry.simulate is not None:
                is_simulated = entry.simulate

            if not is_simulated:
                try:
                    idn = getattr(device, "id", None)
                    idn_str = idn() if callable(idn) else device.query("*IDN?")
                    table.add_row(alias, entry.source, idn_str)
                except Exception as e_idn:
                    table.add_row(
                        alias, entry.source, f"[bold red]Error querying IDN - {e_idn}[/bold red]"
                    )
            else:
                table.add_row(alias, entry.source, "[blue]Simulated[/blue]")

        rich.print(table)
    except FileNotFoundError:
        rich.print(
            f"[bold red]Error: Bench configuration file not found at '{bench_yaml_path}'.[/bold red]"
        )
        raise typer.Exit(code=1) from None
    except Exception as e:
        rich.print(
            f"[bold red]An unexpected error occurred during the bench ID query: {e}[/bold red]"
        )
        raise typer.Exit(code=1) from None
    finally:
        if bench:
            bench.close_all()


@bench_app.command("sim")
def bench_sim_cli(
    bench_yaml_path: Annotated[Path, typer.Argument(help="Path to the bench.yaml file.")],
    output_path: Annotated[
        Path | None, typer.Option(help="Output path for the simulated descriptor.")
    ] = None,
):
    """Export a bench that only opens with built-in simulators."""
    from pytestlab.config.bench_loader import load_bench_yaml
    from pytestlab.config.simulation_only import normalize_simulation_config
    from pytestlab.devices.registry import builtin_simulation_scope

    try:
        with builtin_simulation_scope():
            config = normalize_simulation_config(
                load_bench_yaml(bench_yaml_path), base_path=bench_yaml_path.parent
            )
        sim_yaml = yaml.safe_dump(
            config.model_dump(mode="json", exclude_none=True), sort_keys=False
        )

        if output_path:
            with open(output_path, "w") as f_out:
                f_out.write(sim_yaml)
            rich.print(
                f"[bold green]Simulated bench descriptor saved to:[/bold green] {output_path}"
            )
        else:
            typer.echo(sim_yaml, nl=False)

    except FileNotFoundError:
        typer.echo(f"Error: Bench configuration file not found at '{bench_yaml_path}'.", err=True)
        raise typer.Exit(code=1) from None
    except yaml.YAMLError as e:
        typer.echo(f"Error parsing YAML file '{bench_yaml_path}': {e}", err=True)
        raise typer.Exit(code=1) from None
    except Exception as e:
        typer.echo(f"Could not convert the bench to simulation mode: {e}", err=True)
        raise typer.Exit(code=1) from None


# --- Replay Commands ---
@replay_app.command("record")
def replay_record(
    script: Annotated[Path, typer.Argument(help="Path to the Python script to execute.")],
    bench_config: Annotated[
        Path, typer.Option("--bench", help="Path to the bench.yaml configuration file.")
    ],
    output: Annotated[
        Path, typer.Option("--output", help="Path to save the recorded session YAML file.")
    ],
):
    """Record device exchanges while running a script against a bench."""
    from pytestlab.bench import Bench
    from pytestlab.instruments.backends.session_recording_backend import SessionRecordingBackend

    rich.print("[bold cyan]Starting recording session...[/bold cyan]")
    rich.print(f"Bench Config: {bench_config}")
    rich.print(f"Script: {script}")
    rich.print(f"Output File: {output}")

    bench = None
    try:
        bench = Bench.open(bench_config)
        recorded_data = {}
        base_path = Path(bench_config).parent.resolve()
        profiles_path = (Path(__file__).resolve().parent / "profiles").resolve()
        config_entries = bench._config.devices | bench._config.instruments
        for alias in bench.devices:
            source = config_entries[alias].resolved_source(base_path=base_path)
            if not source:
                raise ValueError(
                    f"Replay recording requires a profile or file for device '{alias}'; "
                    "inline devices are not supported."
                )
            if isinstance(source, Path):
                source = source.resolve()
                if source.suffix == ".yaml" and source.is_relative_to(profiles_path):
                    source = source.relative_to(profiles_path).with_suffix("").as_posix()
            recorded_data[alias] = {"profile": str(source), "log": []}

        rich.print("\n[bold]Wrapping device backends for recording:[/bold]")
        for alias, device in bench.devices.items():
            session_log = recorded_data[alias]["log"]
            device._backend = SessionRecordingBackend(device._backend, session_log)
            rich.print(f"  - Wrapped '{alias}'")

        rich.print("\n[bold]Executing script...[/bold]")
        spec = importlib.util.spec_from_file_location("script_module", script)
        if not spec or not spec.loader:
            raise FileNotFoundError(f"Could not load script module from {script}")
        script_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(script_module)

        if hasattr(script_module, "main"):
            script_module.main(bench)
        else:
            raise TypeError("Script must contain function `main(bench)`.")

        rich.print("[bold green]Script execution finished.[/bold green]")

    except Exception as e:
        rich.print(f"[bold red]An error occurred during recording: {e}[/bold red]")
        import traceback

        traceback.print_exc()
        raise typer.Exit(code=1) from None
    finally:
        if bench:
            bench.close_all()

    rich.print(f"\n[bold]Saving recorded session to {output}...[/bold]")
    with open(output, "w") as f:
        yaml.dump(recorded_data, f, sort_keys=False, default_flow_style=False)
    rich.print("[bold green]Recording complete.[/bold green]")


@replay_app.command("run")
def replay_run(
    script: Annotated[Path, typer.Argument(help="Path to the Python script to execute.")],
    session: Annotated[
        Path, typer.Option("--session", help="Path to the recorded session YAML file.")
    ],
):
    """Replays a recorded measurement session against a simulated bench."""
    from pytestlab.devices import AutoDevice
    from pytestlab.instruments.backends.replay_backend import ReplayBackend

    if isinstance(script, str):
        script = Path(script)
    if isinstance(session, str):
        session = Path(session)

    rich.print("[bold cyan]Starting replay session...[/bold cyan]")
    rich.print(f"Session File: {session}")
    rich.print(f"Script: {script}")

    if not session.exists():
        rich.print(f"[bold red]Error: Session file not found at {session}[/bold red]")
        raise typer.Exit(code=1)

    with open(session) as f:
        session_data = yaml.safe_load(f)

    replay_bench = types.SimpleNamespace()
    device_instances = {}
    device_aliases = list(session_data.keys())

    try:
        rich.print("\n[bold]Building replay bench from session file:[/bold]")
        for alias in device_aliases:
            data = session_data[alias]
            profile_source = data["profile"]
            if not isinstance(profile_source, str) or not profile_source:
                raise ValueError(f"Recorded device '{alias}' does not have a profile or file.")
            session_log: list[dict[str, Any]] = data["log"]

            replay_backend = ReplayBackend(session_log, profile_key=alias)
            if Path(profile_source).is_absolute():
                device = AutoDevice.from_file(profile_source, backend_override=replay_backend)
            else:
                device = AutoDevice.from_config(
                    config_source=profile_source, backend_override=replay_backend
                )
            device.connect_backend()

            setattr(replay_bench, alias, device)
            device_instances[alias] = device
            rich.print(f"  - Created device '{alias}' for replay.")

        replay_bench.devices = device_instances

        rich.print("\n[bold]Executing script in replay mode...[/bold]")
        spec = importlib.util.spec_from_file_location("script_module", script)
        if not spec or not spec.loader:
            raise FileNotFoundError(f"Could not load script module from {script}")
        script_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(script_module)

        if hasattr(script_module, "main"):
            script_module.main(replay_bench)
        else:
            raise TypeError("Script must contain an function `main(bench)`.")

        rich.print("[bold green]Script execution finished successfully.[/bold green]")

    except Exception as e:
        rich.print(f"[bold red]An error occurred during replay: {e}[/bold red]")
        import traceback

        traceback.print_exc()
        raise typer.Exit(code=1) from None
    finally:
        for device in device_instances.values():
            device.close()

    rich.print("[bold green]Replay complete.[/bold green]")


@app.command("run")
def run_command(
    script: Annotated[Path, typer.Argument(help="Path to the Python script to execute.")],
    bench_config: Annotated[
        Path, typer.Option("--bench", help="Path to the bench.yaml configuration file.")
    ],
    simulate: Annotated[
        bool,
        typer.Option(
            "--simulate",
            help="Use only built-in simulators for bench devices; not a Python sandbox.",
        ),
    ] = False,
    output: Annotated[
        Path | None, typer.Option("--output", help="Path to save measurement results.")
    ] = None,
):
    """Execute a measurement script against a bench configuration."""
    from pytestlab.bench import Bench

    rich.print("[bold cyan]Running measurement script...[/bold cyan]")
    rich.print(f"Script: {script}")
    rich.print(f"Bench Config: {bench_config}")
    rich.print(f"Simulation Mode: {simulate}")

    if not script.exists():
        rich.print(f"[bold red]Error: Script file not found at {script}[/bold red]")
        raise typer.Exit(code=1)

    if not bench_config.exists():
        rich.print(f"[bold red]Error: Bench config file not found at {bench_config}[/bold red]")
        raise typer.Exit(code=1)

    bench = None
    try:
        if simulate:
            rich.print(
                "Built-in bench simulation only. Run only trusted Python and simulator inputs."
            )
            bench = Bench.open(bench_config, force_simulation=True)
        else:
            bench = Bench.open(bench_config)

        rich.print(f"[bold green]Bench '{bench.name}' loaded successfully[/bold green]")

        spec = importlib.util.spec_from_file_location("measurement_script", script)
        if not spec or not spec.loader:
            raise FileNotFoundError(f"Could not load script module from {script}")

        script_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(script_module)

        if hasattr(script_module, "main"):
            rich.print("[bold]Executing script main function...[/bold]")
            result = script_module.main(bench)

            if output and result:
                rich.print(f"[bold]Saving results to {output}...[/bold]")
                with open(output, "w") as f:
                    if isinstance(result, dict):
                        yaml.dump(result, f)
                    else:
                        f.write(str(result))
                rich.print(f"[bold green]Results saved to {output}[/bold green]")

            rich.print("[bold green]Script execution completed successfully[/bold green]")
        else:
            rich.print(f"[bold yellow]Warning: No 'main' function found in {script}[/bold yellow]")
            rich.print(
                "[bold yellow]Script was loaded but no main function was executed[/bold yellow]"
            )

    except Exception as e:
        rich.print(f"[bold red]Error during execution: {e}[/bold red]")
        import traceback

        traceback.print_exc()
        raise typer.Exit(code=1) from None
    finally:
        if bench:
            bench.close_all()


@app.command("list")
def list_command(
    resource: Annotated[
        str, typer.Argument(help="Resource type to list: 'profiles', 'benches', 'examples'")
    ] = "profiles",
):
    """List available resources (profiles, bench configs, examples)."""

    if resource == "profiles":
        rich.print("[bold cyan]Available device profiles:[/bold cyan]")
        try:
            spec = importlib.util.find_spec("pytestlab.profiles")
            if spec and spec.origin:
                profiles_dir = Path(spec.origin).parent
                table = Table(title="Device Profiles")
                table.add_column("Profile Key", style="cyan")
                table.add_column("Vendor", style="magenta")
                table.add_column("Model", style="green")

                for vendor_dir in profiles_dir.iterdir():
                    if vendor_dir.is_dir() and vendor_dir.name != "__pycache__":
                        vendor = vendor_dir.name
                        for profile_file in vendor_dir.glob("*.yaml"):
                            model = profile_file.stem
                            profile_key = f"{vendor}/{model}"
                            table.add_row(profile_key, vendor, model)

                rich.print(table)
            else:
                rich.print("[bold red]Could not find profiles directory[/bold red]")

        except Exception as e:
            rich.print(f"[bold red]Error listing profiles: {e}[/bold red]")

    elif resource == "benches":
        rich.print("[bold cyan]Searching for bench configurations:[/bold cyan]")
        bench_files: list[Path] = []
        search_paths = [
            Path.cwd(),
            Path.cwd() / "examples",
            Path.cwd() / "configs",
            Path.cwd() / "benches",
        ]
        for search_path in search_paths:
            if search_path.exists():
                bench_files.extend(search_path.glob("*bench*.yaml"))
                bench_files.extend(search_path.glob("bench.yaml"))

        if bench_files:
            table = Table(title="Bench Configurations")
            table.add_column("File", style="cyan")
            table.add_column("Path", style="green")
            for bench_file in sorted(set(bench_files)):
                table.add_row(bench_file.name, str(bench_file.parent))
            rich.print(table)
        else:
            rich.print("[bold yellow]No bench configuration files found[/bold yellow]")
            rich.print("Searched in: " + ", ".join(str(p) for p in search_paths))

    elif resource == "examples":
        rich.print("[bold cyan]Available examples:[/bold cyan]")
        try:
            examples_dir = Path.cwd() / "examples"
            if not examples_dir.exists():
                spec = importlib.util.find_spec("pytestlab")
                if spec and spec.origin:
                    pkg_dir = Path(spec.origin).parent.parent
                    examples_dir = pkg_dir / "examples"

            if examples_dir.exists():
                table = Table(title="Example Scripts")
                table.add_column("Script", style="cyan")
                table.add_column("Description", style="green")

                for script_file in examples_dir.glob("*.py"):
                    description = "Python script"
                    try:
                        with open(script_file) as f:
                            lines = f.readlines()
                            for line in lines[:10]:
                                if '"""' in line and len(line.strip()) > 3:
                                    description = line.strip().replace('"""', "").strip()
                                    if description:
                                        break
                    except Exception:
                        pass

                    table.add_row(
                        script_file.name,
                        description[:60] + "..." if len(description) > 60 else description,
                    )

                rich.print(table)
            else:
                rich.print("[bold yellow]Examples directory not found[/bold yellow]")

        except Exception as e:
            rich.print(f"[bold red]Error listing examples: {e}[/bold red]")

    else:
        rich.print(f"[bold red]Unknown resource type: {resource}[/bold red]")
        rich.print("Available resource types: profiles, benches, examples")
        raise typer.Exit(code=1)


def run_app():
    """Main entry point for the CLI."""
    app()


def main():
    argv = sys.argv[1:]
    # These two groups retain their legacy argument parsing, but help must
    # always be handled by Typer before a device or a script can be opened.
    if "--help" in argv:
        return run_app()
    if argv[:2] == ["sim-profile", "record"]:
        from pytestlab.cli import sim_profile_record

        if len(sys.argv) < 4:
            rich.print("[bold red]Error: Missing profile key for sim-profile record.[/bold red]")
            raise typer.Exit(code=1)

        address: str | None = None
        output_path: Path | None = None
        script: Path | None = None
        simulate_flag = False
        idx = 0
        while idx < len(sys.argv):
            arg = sys.argv[idx]
            if arg == "--address" and idx + 1 < len(sys.argv):
                address = sys.argv[idx + 1]
                idx += 1
            elif arg == "--output-path" and idx + 1 < len(sys.argv):
                output_path = Path(sys.argv[idx + 1])
                idx += 1
            elif arg == "--script" and idx + 1 < len(sys.argv):
                script = Path(sys.argv[idx + 1])
                idx += 1
            elif arg == "--simulate":
                value: bool = True
                if idx + 1 < len(sys.argv) and not sys.argv[idx + 1].startswith("--"):
                    simulate_arg = sys.argv[idx + 1].lower()
                    value = simulate_arg not in {"0", "false", "no"}
                    idx += 1
                simulate_flag = value
            idx += 1

        sim_profile_record(
            profile_key=sys.argv[3],
            address=address,
            output_path=output_path,
            script=script,
            simulate=simulate_flag,
        )
    elif argv[:2] in (["replay", "record"], ["replay", "run"]):
        if argv[1] == "record":
            from pytestlab.cli import replay_record

            script_path = Path(sys.argv[3]) if len(sys.argv) > 3 else None
            bench_config = None
            output = None

            for i, arg in enumerate(sys.argv):
                if arg == "--bench" and i + 1 < len(sys.argv):
                    bench_config = Path(sys.argv[i + 1])
                elif arg == "--output" and i + 1 < len(sys.argv):
                    output = Path(sys.argv[i + 1])

            if script_path and bench_config and output:
                replay_record(script_path, bench_config, output)
            else:
                rich.print(
                    "[bold red]Error: Missing required arguments for replay record[/bold red]"
                )
                sys.exit(1)

        else:
            from pytestlab.cli import replay_run

            script_path = Path(sys.argv[3]) if len(sys.argv) > 3 else None
            session = None

            for i, arg in enumerate(sys.argv):
                if arg == "--session" and i + 1 < len(sys.argv):
                    session = Path(sys.argv[i + 1])

            if script_path and session:
                replay_run(script_path, session)
            else:
                rich.print("[bold red]Error: Missing required arguments for replay run[/bold red]")
                sys.exit(1)
    else:
        run_app()


app.add_typer(prober_app, name="prober")

if __name__ == "__main__":
    main()
