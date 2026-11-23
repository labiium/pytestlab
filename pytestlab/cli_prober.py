"""Typed command-line entry points for the generic prober capability."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated
from typing import Any

import rich
import typer
from click.core import ParameterSource

prober_app = typer.Typer(name="prober", help="Inspect and operate a prober capability.")


def _prober_resource(bench: Any, alias: str) -> Any:
    """Resolve a guarded motion handle and require the public prober API."""

    from .cli_typer import _motion_resource

    resource = _motion_resource(bench, alias)
    required = ("get_capabilities", "preflight_recipe")
    if not all(callable(getattr(resource, name, None)) for name in required):
        raise TypeError(f"Bench resource '{alias}' does not provide a Prober capability.")
    return resource


def _capabilities_payload(capabilities: Any) -> dict[str, Any]:
    return {
        "axes": [
            {
                "name": axis.name,
                "units": axis.units,
                "minimum": axis.minimum,
                "maximum": axis.maximum,
            }
            for axis in capabilities.axes
        ],
        "axis_groups": [
            {"name": group.name, "axes": list(group.axes)} for group in capabilities.axis_groups
        ],
        "frames": [{"name": frame.name, "parent": frame.parent} for frame in capabilities.frames],
        "units": list(capabilities.units),
        "supports": sorted(capabilities.supports),
    }


def _bench_open(bench_path: Path | None, alias: str) -> Any:
    from .cli_typer import _open_cli_bench

    return _open_cli_bench(bench_path, aliases={alias})


def _bench_close(bench: Any) -> None:
    from .cli_typer import _close_cli_bench

    _close_cli_bench(bench)


def _emit(value: Any, *, as_json: bool) -> None:
    if as_json:
        typer.echo(json.dumps(value, sort_keys=True, default=str))
    else:
        rich.print(value)


def _errors() -> tuple[type[Exception], ...]:
    from .cli_typer import _CAPABILITY_ERRORS

    return _CAPABILITY_ERRORS


def _report_error(error: Exception) -> None:
    from rich.markup import escape

    rich.print(f"[bold red]Error: {escape(str(error))}[/bold red]")


def _report_motion_result(result: Any, *, as_json: bool) -> None:
    from .cli_typer import _report_motion_result as report

    report(result, as_json=as_json)


def _action(
    alias: str,
    method_name: str,
    *,
    bench_path: Path | None,
    wait: bool,
    as_json: bool,
    kwargs: dict[str, Any] | None = None,
) -> None:
    bench = _bench_open(bench_path, alias)
    try:
        method = getattr(_prober_resource(bench, alias), method_name, None)
        if not callable(method):
            raise TypeError(f"Prober does not provide '{method_name}'.")
        result = method(**(kwargs or {}), wait=wait)
        _report_motion_result(result, as_json=as_json)
    except _errors() as exc:
        _report_error(exc)
        raise typer.Exit(code=1) from None
    finally:
        _bench_close(bench)


@prober_app.command("capabilities", hidden=True)
def prober_capabilities(
    alias: Annotated[str, typer.Argument(help="Prober alias in the bench.")],
    as_json: Annotated[bool, typer.Option("--json")] = False,
    bench_path: Annotated[Path | None, typer.Option("--bench")] = None,
) -> None:
    """Show profile-declared axes, frames, units and prober operations."""

    bench = _bench_open(bench_path, alias)
    try:
        resource = _prober_resource(bench, alias)
        _emit(_capabilities_payload(resource.get_capabilities()), as_json=as_json)
    except _errors() as exc:
        _report_error(exc)
        raise typer.Exit(code=1) from None
    finally:
        _bench_close(bench)


@prober_app.command("preflight", hidden=True)
def prober_preflight(
    alias: Annotated[str, typer.Argument(help="Prober alias in the bench.")],
    required: Annotated[
        list[str] | None,
        typer.Option("--required", help="Limit checking to named action capabilities."),
    ] = None,
    as_json: Annotated[bool, typer.Option("--json")] = False,
    bench_path: Annotated[Path | None, typer.Option("--bench")] = None,
) -> None:
    """Check the full recipe or selected capabilities without connecting."""

    bench = _bench_open(bench_path, alias)
    try:
        ready = _prober_resource(bench, alias).preflight_recipe(
            required=None if required is None else tuple(required)
        )
        _emit({"ready": list(ready)}, as_json=as_json)
    except _errors() as exc:
        _report_error(exc)
        raise typer.Exit(code=1) from None
    finally:
        _bench_close(bench)


def _action_command(method: str, help_text: str):
    def command(
        alias: Annotated[str, typer.Argument(help="Prober alias in the bench.")],
        wait: Annotated[bool, typer.Option("--wait", help="Wait for verified completion.")] = False,
        as_json: Annotated[bool, typer.Option("--json")] = False,
        bench_path: Annotated[Path | None, typer.Option("--bench")] = None,
    ) -> None:
        _action(alias, method, bench_path=bench_path, wait=wait, as_json=as_json)

    command.__name__ = method
    command.__doc__ = help_text
    return command


prober_app.command("contact")(_action_command("contact", "Bring the probe into contact."))
prober_app.command("separate")(_action_command("separate", "Separate the probe from the wafer."))
prober_app.command("move-to-align", hidden=True)(
    _action_command("move_to_align", "Move the chuck to alignment height.")
)
prober_app.command("move-to-load", hidden=True)(
    _action_command("move_to_load", "Move the chuck to its load position.")
)


def _require_explicit_options(ctx: typer.Context, options: dict[str, str]) -> None:
    # Some Click versions treat omitted required paired flags as implicit false.
    # Never open a bench until every state-changing choice was given on the CLI.
    for name, flags in options.items():
        if ctx.get_parameter_source(name) is not ParameterSource.COMMANDLINE:
            raise typer.BadParameter("Choose one of the paired flags explicitly.", param_hint=flags)


@prober_app.command("vacuum", hidden=True)
def prober_vacuum(
    ctx: typer.Context,
    alias: Annotated[str, typer.Argument(help="Prober alias in the bench.")],
    enabled: Annotated[
        bool, typer.Option("--on/--off", help="Explicitly enable or disable vacuum.")
    ],
    wait: Annotated[bool, typer.Option("--wait", help="Wait for verified completion.")] = False,
    as_json: Annotated[bool, typer.Option("--json")] = False,
    bench_path: Annotated[Path | None, typer.Option("--bench")] = None,
) -> None:
    """Set chuck vacuum with an explicit --on or --off choice."""

    _require_explicit_options(ctx, {"enabled": "--on/--off"})
    _action(
        alias,
        "set_vacuum",
        bench_path=bench_path,
        wait=wait,
        as_json=as_json,
        kwargs={"enabled": enabled},
    )


@prober_app.command("configure-chuck", hidden=True)
def prober_configure_chuck(
    ctx: typer.Context,
    alias: Annotated[str, typer.Argument(help="Prober alias in the bench.")],
    overtravel: Annotated[bool, typer.Option("--overtravel/--no-overtravel")],
    auto_z: Annotated[bool, typer.Option("--auto-z/--no-auto-z")],
    interlock: Annotated[bool, typer.Option("--interlock/--no-interlock")],
    edge_sensor: Annotated[bool, typer.Option("--edge-sensor/--no-edge-sensor")],
    wait: Annotated[bool, typer.Option("--wait", help="Wait for verified completion.")] = False,
    as_json: Annotated[bool, typer.Option("--json")] = False,
    bench_path: Annotated[Path | None, typer.Option("--bench")] = None,
) -> None:
    """Set all chuck safety options explicitly."""

    _require_explicit_options(
        ctx,
        {
            "overtravel": "--overtravel/--no-overtravel",
            "auto_z": "--auto-z/--no-auto-z",
            "interlock": "--interlock/--no-interlock",
            "edge_sensor": "--edge-sensor/--no-edge-sensor",
        },
    )
    _action(
        alias,
        "configure_chuck",
        bench_path=bench_path,
        wait=wait,
        as_json=as_json,
        kwargs={
            "overtravel": overtravel,
            "auto_z": auto_z,
            "interlock": interlock,
            "edge_sensor": edge_sensor,
        },
    )


def _readback(alias: str, method_name: str, bench_path: Path | None, as_json: bool) -> None:
    bench = _bench_open(bench_path, alias)
    try:
        method = getattr(_prober_resource(bench, alias), method_name, None)
        if not callable(method):
            raise TypeError(f"Prober does not provide '{method_name}'.")
        _emit({"value": method()}, as_json=as_json)
    except _errors() as exc:
        _report_error(exc)
        raise typer.Exit(code=1) from None
    finally:
        _bench_close(bench)


def _readback_command(method: str, help_text: str):
    def command(
        alias: Annotated[str, typer.Argument(help="Prober alias in the bench.")],
        as_json: Annotated[bool, typer.Option("--json")] = False,
        bench_path: Annotated[Path | None, typer.Option("--bench")] = None,
    ) -> None:
        _readback(alias, method, bench_path, as_json)

    command.__name__ = method
    command.__doc__ = help_text
    return command


prober_app.command("contact-state", hidden=True)(
    _readback_command("get_contact_state", "Read mapped physical contact state.")
)
prober_app.command("vacuum-state", hidden=True)(
    _readback_command("get_vacuum_state", "Read mapped physical vacuum state.")
)
prober_app.command("settled-state", hidden=True)(
    _readback_command("get_settled_state", "Read mapped physical settled state.")
)


__all__ = ["prober_app"]
