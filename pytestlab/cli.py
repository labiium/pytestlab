# pytestlab/cli.py
from __future__ import annotations

import code
import difflib
import importlib.util  # For finding profile paths
import os
import shutil
import sys
import types  # For creating a simple namespace for the replay bench
from importlib import metadata
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Annotated
from typing import Any
from typing import cast

import rich  # For pretty printing
import typer
import yaml
from rich.markup import escape as rich_escape
from rich.syntax import Syntax
from rich.table import Table

if TYPE_CHECKING:
    pass


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


@app.callback()
def main_callback(
    version: bool | None = typer.Option(
        None, "--version", callback=version_callback, is_eager=True, help="Show version and exit."
    ),
):
    """PyTestLab: Scientific test & measurement toolbox CLI."""
    pass


profile_app = typer.Typer(name="profile", help="Manage device profiles.")
device_app = typer.Typer(name="device", help="Interact with lab devices.")
instrument_app = typer.Typer(name="instrument", help="Interact with instruments.")
bench_app = typer.Typer(name="bench", help="Manage bench configurations.")
sim_profile_app = typer.Typer(name="sim-profile", help="Manage simulation profiles.")
visa_app = typer.Typer(name="visa", help="Discover VISA resources.")
lamb_app = typer.Typer(name="lamb", help="Interact with LAMB instrument server.")

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
    table.add_column("Resource (redacted)", style="cyan", overflow="fold")
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
        str,
        typer.Option(
            help="LAMB server base URL. Overrides LAMB_SERVER environment variable."
        ),
    ] = os.getenv("LAMB_SERVER", "http://lamb-server:8000"),
    timeout_ms: Annotated[
        int,
        typer.Option(help="Timeout in milliseconds for server requests."),
    ] = 5000,
):
    """List VISA resources available via a LAMB instrument server."""
    import httpx

    if timeout_ms <= 0:
        rich.print("[bold red]Error:[/] --timeout-ms must be positive.")
        raise typer.Exit(code=1)

    base_url = url.rstrip("/")
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
        rich.print("No VISA resources found on the LAMB server.")
        return

    table = Table(title=f"LAMB Resources — {base_url}")
    table.add_column("Resource (redacted)", style="cyan", overflow="fold")
    table.add_column("Status", style="green")

    for resource in active:
        table.add_row(str(resource), "[green]active[/green]")
    for resource in inactive:
        table.add_row(str(resource), "[yellow]inactive[/yellow]")

    rich.print(table)
    rich.print(f"\nTotal: {len(active)} active, {len(inactive)} inactive")
    rich.print(
        "[dim]Resource identifiers are redacted by the server; use model/serial auto-connect or a known VISA address for operations.[/]"
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
        base_profile = base_profile_model.model_dump(mode="json")
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
):
    """Shows the content of a specific instrument profile."""
    from pytestlab.config.loader import resolve_profile_key_to_path

    try:
        profile_path = Path(profile_key_or_path)
        if not profile_path.is_file():
            profile_path = resolve_profile_key_to_path(profile_key_or_path)

        with open(profile_path) as f:
            content = f.read()
            rich.print(f"[bold]Profile: {profile_key_or_path}[/bold]")
            syntax = Syntax(content, "yaml", theme="monokai", line_numbers=True)
            rich.print(syntax)
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
        device.connect_backend()
        idn = getattr(device, "id", None)
        idn_response = idn() if callable(idn) else device.query("*IDN?")
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


@device_app.command("idn")
def device_idn(
    profile_key_or_path: Annotated[str, typer.Argument(help="Profile key or path.")],
    address: Annotated[
        str | None, typer.Option(help="VISA address. Overrides profile if provided.")
    ] = None,
    simulate: Annotated[bool, typer.Option(help="Run in simulation mode.")] = False,
):
    """Connects to a device and prints its *IDN? response when supported."""
    _device_idn_impl(profile_key_or_path, address, simulate)


@instrument_app.command("idn")
def instrument_idn(
    profile_key_or_path: Annotated[str, typer.Argument(help="Profile key or path.")],
    address: Annotated[
        str | None, typer.Option(help="VISA address. Overrides profile if provided.")
    ] = None,
    simulate: Annotated[bool, typer.Option(help="Run in simulation mode.")] = False,
):
    """Connects to an instrument and prints its *IDN? response."""
    _device_idn_impl(profile_key_or_path, address, simulate)


@instrument_app.command("test")
def instrument_test(
    kind: Annotated[
        str,
        typer.Argument(help="Instrument kind to test: multimeter | psu | oscilloscope | awg | all"),
    ],
    profile: Annotated[
        str,
        typer.Argument(help="Instrument profile key to use for tests (e.g., keysight/EDU34450A)"),
    ],
):
    """Run instrument tests for a given profile key by overriding test module constants via a temporary pytest plugin."""
    import sys as _sys
    import tempfile as _tempfile
    from pathlib import Path as _Path

    try:
        base_dir = _Path(__file__).parent  # pytestlab/pytestlab
        # Resolve tests directory robustly for both package and repo layouts
        repo_tests = base_dir.parent / "tests" / "instruments"
        pkg_tests = base_dir / "tests" / "instruments"
        tests_dir = repo_tests if repo_tests.exists() else pkg_tests

        kind_lc = kind.lower()
        targets: list[str] = []
        if kind_lc in ("multimeter", "mm"):
            targets.append(str(tests_dir / "test_multimeter.py"))
        if kind_lc in ("psu", "supply", "power", "power-supply"):
            targets.append(str(tests_dir / "test_psu.py"))
        if kind_lc in ("oscilloscope", "scope", "osc"):
            targets.append(str(tests_dir / "test_oscilloscope.py"))
        if kind_lc in ("awg", "waveform", "generator"):
            targets.append(str(tests_dir / "test_awg.py"))
        if kind_lc in ("all",):
            targets = [
                str(tests_dir / "test_multimeter.py"),
                str(tests_dir / "test_psu.py"),
                str(tests_dir / "test_oscilloscope.py"),
                str(tests_dir / "test_awg.py"),
            ]

        if not targets:
            rich.print(f"[bold red]Unknown instrument kind: {kind}[/bold red]")
            raise typer.Exit(code=1)

        # Create a temporary pytest plugin to override profile constants in test modules.
        import textwrap as _textwrap

        plugin_code = _textwrap.dedent(
            """\
            PROFILE="{PROFILE}"
            KIND="{KIND}"
            def pytest_sessionstart(session):
                import importlib
                # Override profile keys in test modules when available
                if KIND in ("multimeter","mm","all"):
                    try:
                        m = importlib.import_module("pytestlab.tests.devices.test_multimeter")
                        setattr(m, "MM_CONFIG_KEY", PROFILE)
                    except Exception:
                        pass
                if KIND in ("psu","supply","power","power-supply","all"):
                    try:
                        m = importlib.import_module("pytestlab.tests.devices.test_psu")
                        setattr(m, "PSU_CONFIG_KEY", PROFILE)
                    except Exception:
                        pass
                if KIND in ("oscilloscope","scope","osc","all"):
                    try:
                        m = importlib.import_module("pytestlab.tests.devices.test_oscilloscope")
                        setattr(m, "OSC_CONFIG_KEY", PROFILE)
                    except Exception:
                        pass
                if KIND in ("awg","waveform","generator","all"):
                    try:
                        m = importlib.import_module("pytestlab.tests.devices.test_awg")
                        setattr(m, "AWG_PROFILE_KEY", PROFILE)
                    except Exception:
                        pass
            """
        ).format(PROFILE=profile, KIND=kind_lc)
        with _tempfile.TemporaryDirectory() as tmpdir:
            plugin_path = _Path(tmpdir) / "ptl_profile_override.py"
            plugin_path.write_text(plugin_code, encoding="utf-8")
            _sys.path.insert(0, tmpdir)

            import pytest as _pytest

            # Run only real-hardware tests; they gracefully skip if hardware is unavailable.
            args = ["-p", "ptl_profile_override", "-m", "requires_real_hw"] + targets
            rich.print("[bold cyan]Running tests:[/bold cyan] " + ", ".join(targets))
            exit_code = _pytest.main(args)
            raise typer.Exit(code=exit_code)
    except typer.Exit as te:
        # Propagate Typer-controlled exit (normal flow)
        raise te
    except SystemExit as se:
        # Normalize pytest's SystemExit into Typer.Exit with explicit type checks
        code_obj = getattr(se, "code", None)
        if code_obj is None:
            code = 1
        elif isinstance(code_obj, int):
            code = code_obj
        elif isinstance(code_obj, str):
            try:
                code = int(code_obj)
            except ValueError:
                code = 1
        else:
            # Handle IntEnum-like objects (e.g., pytest.ExitCode)
            value = getattr(code_obj, "value", None)
            if isinstance(value, int):
                code = value
            else:
                try:
                    code = int(code_obj)  # Fallback conversion
                except Exception:
                    code = 1
        raise typer.Exit(code=code) from None
    except Exception as e:
        rich.print(f"[bold red]Failed to run instrument tests: {e}[/bold red]")
        raise typer.Exit(code=1) from None


@bench_app.command("ls")
def bench_ls(bench_yaml_path: Annotated[Path, typer.Argument(help="Path to the bench.yaml file.")]):
    """Lists devices in a bench configuration."""
    from pytestlab.config.bench_config import BenchConfigExtended

    try:
        with open(bench_yaml_path) as f:
            data = yaml.safe_load(f)
        config = BenchConfigExtended.model_validate(data)  # Validate
        table = Table(title=f"Bench: {config.bench_name}")
        table.add_column("Alias", style="cyan")
        table.add_column("Profile", style="magenta")
        table.add_column("Kind", style="cyan")
        table.add_column("Address", style="green")
        table.add_column("Backend Type", style="yellow")
        table.add_column("Simulate", style="blue")

        entries = [(alias, entry, "device") for alias, entry in config.devices.items()]
        entries.extend((alias, entry, "instrument") for alias, entry in config.instruments.items())
        for alias, entry, kind in entries:
            sim_status = "Global" if entry.simulate is None else str(entry.simulate)
            addr = entry.address or "N/A (simulated)"
            backend_type = (
                entry.backend.get("type")
                if entry.backend and entry.backend.get("type")
                else config.backend_defaults.get("type", "visa")
                if config.backend_defaults
                else "visa"
            )
            table.add_row(alias, entry.source, kind, addr, backend_type, sim_status)
        rich.print(table)
    except FileNotFoundError:
        rich.print(
            f"[bold red]Error: Bench configuration file not found at '{bench_yaml_path}'.[/bold red]"
        )
        raise typer.Exit(code=1) from None
    except yaml.YAMLError as e:
        rich.print(f"[bold red]Error parsing YAML file '{bench_yaml_path}': {e}[/bold red]")
        raise typer.Exit(code=1) from None
    except Exception as e:
        rich.print(
            f"[bold red]An unexpected error occurred while listing the bench devices: {e}[/bold red]"
        )
        raise typer.Exit(code=1) from None


@bench_app.command("validate")
def bench_validate_cli(
    bench_yaml_path: Annotated[Path, typer.Argument(help="Path to the bench.yaml file.")],
    strict: Annotated[
        bool,
        typer.Option("--strict", help="Enable strict pre-hardware validation checks."),
    ] = False,
):
    """Validates a bench configuration file (dry-run)."""
    from pytestlab.config.bench_config import BenchConfigExtended
    from pytestlab.config.loader import load_device_profile
    from pytestlab.measurement_plan import validate_declared_measurements
    from pytestlab.measurement_plan import validate_declared_routes

    try:
        with open(bench_yaml_path) as f:
            data = yaml.safe_load(f)
        config = BenchConfigExtended.model_validate(data)
        rich.print(f"[bold green]Bench configuration '{bench_yaml_path}' is valid.[/bold green]")

        rich.print("Validating individual device profiles...")
        all_profiles_valid = True
        entries = list(config.devices.items()) + list(config.instruments.items())
        for alias, entry in entries:
            try:
                load_device_profile(entry.resolved_source(base_path=bench_yaml_path.parent))
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

        semantic_errors = validate_declared_measurements(
            config,
            base_path=bench_yaml_path.parent,
            include_route_validation=strict,
        )
        if semantic_errors:
            all_profiles_valid = False
            rich.print("[bold red]Measurement plan validation failed:[/bold red]")
            for error in semantic_errors:
                rich.print(f"  [bold red]✖[/bold red] {error}")
        if config.routes:
            rich.print("Validating declared routes...")
            if strict:
                route_errors = validate_declared_routes(config, base_path=bench_yaml_path.parent)
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

    except typer.Exit:
        raise
    except FileNotFoundError:
        rich.print(
            f"[bold red]Error: Bench configuration file not found at '{bench_yaml_path}'.[/bold red]"
        )
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
    from pytestlab.bench import Bench

    bench = None
    try:
        bench = Bench.open(bench_yaml_path)
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
    """Converts a bench descriptor to full simulation mode."""
    from pytestlab.config.bench_config import BenchConfigExtended

    try:
        with open(bench_yaml_path) as f:
            data = yaml.safe_load(f)
        config = BenchConfigExtended.model_validate(data)

        sim_config_data = config.model_dump(mode="python")
        sim_config_data["simulate"] = True
        for alias_key in sim_config_data["devices"]:
            sim_config_data["devices"][alias_key]["simulate"] = True
            sim_config_data["devices"][alias_key]["address"] = "sim"
            if sim_config_data["devices"][alias_key].get("backend"):
                sim_config_data["devices"][alias_key]["backend"]["type"] = "sim"
            else:
                sim_config_data["devices"][alias_key]["backend"] = {
                    "type": "sim",
                    "timeout_ms": 5000,
                }

        sim_yaml = yaml.dump(sim_config_data, sort_keys=False)

        if output_path:
            with open(output_path, "w") as f_out:
                f_out.write(sim_yaml)
            rich.print(
                f"[bold green]Simulated bench descriptor saved to:[/bold green] {output_path}"
            )
        else:
            syntax = Syntax(sim_yaml, "yaml", theme="monokai", line_numbers=True)
            rich.print(syntax)

    except FileNotFoundError:
        rich.print(
            f"[bold red]Error: Bench configuration file not found at '{bench_yaml_path}'.[/bold red]"
        )
        raise typer.Exit(code=1) from None
    except yaml.YAMLError as e:
        rich.print(f"[bold red]Error parsing YAML file '{bench_yaml_path}': {e}[/bold red]")
        raise typer.Exit(code=1) from None
    except Exception as e:
        rich.print(
            f"[bold red]An unexpected error occurred while converting the bench to simulation mode: {e}[/bold red]"
        )
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
    """Records a measurement session by running a script against a real bench."""
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

        rich.print("\n[bold]Wrapping device backends for recording:[/bold]")
        config_entries = bench._config.devices | bench._config.instruments
        for alias, device in bench.devices.items():
            profile_key = config_entries[alias].profile
            session_log: list[dict[str, Any]] = []
            recorded_data[alias] = {"profile": profile_key, "log": session_log}
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
            profile_key = data["profile"]
            session_log: list[dict[str, Any]] = data["log"]

            replay_backend = ReplayBackend(session_log, profile_key=alias)

            device = AutoDevice.from_config(
                config_source=profile_key, backend_override=replay_backend
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
    simulate: Annotated[bool, typer.Option("--simulate", help="Force simulation mode.")] = False,
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
            with open(bench_config) as f:
                config_data = yaml.safe_load(f)
            config_data["simulate"] = True
            import tempfile

            with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as temp_file:
                yaml.dump(config_data, temp_file)
                temp_bench_config = Path(temp_file.name)
            bench = Bench.open(temp_bench_config)
            temp_bench_config.unlink()
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
    if "sim-profile" in sys.argv and "record" in sys.argv:
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
    elif "replay" in sys.argv and ("record" in sys.argv or "run" in sys.argv):
        if "record" in sys.argv:
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

        elif "run" in sys.argv:
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


if __name__ == "__main__":
    main()
