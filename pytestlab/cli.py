# pytestlab/cli.py
import typer
from typing_extensions import Annotated # For older Python, or just use `typing.Annotated` for Py 3.9+
from typing import Optional # Ensure Optional is imported
from pathlib import Path
import yaml
import rich # For pretty printing
from rich.syntax import Syntax
import importlib.util # For finding profile paths
import pkgutil # For finding profile paths

import os
import shutil
import difflib
import code

# Assuming these imports are valid after recent refactors
from pytestlab.config.loader import load_profile, resolve_profile_key_to_path
from pytestlab.instruments import AutoInstrument
from pytestlab.instruments.backends.recording_backend import RecordingBackend
# For bench commands (anticipating section 6.2)
from pytestlab.config.bench_config import BenchConfigExtended
from pytestlab.bench import Bench
import asyncio # For running async CLI commands

app = typer.Typer(help="PyTestLab: Scientific test & measurement toolbox CLI.")
profile_app = typer.Typer(name="profile", help="Manage instrument profiles.")
instrument_app = typer.Typer(name="instrument", help="Interact with instruments.")
bench_app = typer.Typer(name="bench", help="Manage bench configurations.")
sim_profile_app = typer.Typer(name="sim-profile", help="Manage simulation profiles.")

app.add_typer(profile_app)
app.add_typer(instrument_app)
app.add_typer(bench_app)
app.add_typer(sim_profile_app)

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

# --- Simulation Profile Commands ---

@sim_profile_app.command("edit")
def sim_profile_edit(profile_key: Annotated[str, typer.Argument(help="Profile key (e.g., keysight/DSOX1204G).")]):
   """Opens the user's override profile in their default text editor."""
   try:
       official_path = resolve_profile_key_to_path(profile_key)
       override_path = get_user_override_path(profile_key)

       if not override_path.exists():
           rich.print(f"No user override found for '{profile_key}'. Creating one from the official profile.")
           override_path.parent.mkdir(parents=True, exist_ok=True)
           shutil.copy(official_path, override_path)
           rich.print(f"Copied official profile to: {override_path}")

       rich.print(f"Opening '{override_path}' in your default editor...")
       typer.launch(str(override_path))

   except FileNotFoundError:
       rich.print(f"[bold red]Error: Official profile for key '{profile_key}' not found.[/bold red]")
       raise typer.Exit(code=1)
   except Exception as e:
       rich.print(f"[bold red]An unexpected error occurred: {e}[/bold red]")
       raise typer.Exit(code=1)

@sim_profile_app.command("reset")
def sim_profile_reset(profile_key: Annotated[str, typer.Argument(help="Profile key to reset.")]):
   """Deletes the user's override profile, reverting to the official one."""
   override_path = get_user_override_path(profile_key)
   if override_path.exists():
       try:
           os.remove(override_path)
           rich.print(f"[bold green]Successfully deleted override profile:[/bold green] {override_path}")
           rich.print(f"Simulations for '{profile_key}' will now use the official profile.")
       except OSError as e:
           rich.print(f"[bold red]Error deleting file '{override_path}': {e}[/bold red]")
           raise typer.Exit(code=1)
   else:
       rich.print(f"[bold yellow]No user override profile to reset for '{profile_key}'.[/bold yellow]")


@sim_profile_app.command("diff")
def sim_profile_diff(profile_key: Annotated[str, typer.Argument(help="Profile key to compare.")]):
   """Shows a diff between the user's override and the official profile."""
   try:
       official_path = resolve_profile_key_to_path(profile_key)
       override_path = get_user_override_path(profile_key)

       if not override_path.exists():
           rich.print(f"[bold yellow]No user override profile found for '{profile_key}'. Nothing to compare.[/bold yellow]")
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
           rich.print("[bold green]No differences found between the official and user profiles.[/bold green]")
           return

       rich.print(f"[bold]Diff for {profile_key}:[/bold]")
       syntax = Syntax(diff_str, "diff", theme="monokai")
       rich.print(syntax)

   except FileNotFoundError:
       rich.print(f"[bold red]Error: Official profile for key '{profile_key}' not found.[/bold red]")
       raise typer.Exit(code=1)
   except Exception as e:
       rich.print(f"[bold red]An unexpected error occurred: {e}[/bold red]")
       raise typer.Exit(code=1)


@sim_profile_app.command("record")
async def sim_profile_record(
    profile_key: Annotated[str, typer.Argument(help="Profile key of the instrument to record.")],
    address: Annotated[str, typer.Option(help="VISA address of the instrument.")],
    output_path: Annotated[Optional[Path], typer.Option(help="Output path for the recorded YAML profile. If not provided, it will be saved to the user's cache.")] = None,
    script: Annotated[Optional[Path], typer.Option(help="Path to a Python script to run against the instrument.")] = None,
):
    """Records instrument interactions to create a simulation profile."""
    instrument = None
    try:
        if not address:
            rich.print("[bold red]Error: The --address option is required for recording.[/bold red]")
            raise typer.Exit(code=1)

        final_output_path = output_path
        if not final_output_path:
            final_output_path = get_user_recorded_profile_path(profile_key)
            final_output_path.parent.mkdir(parents=True, exist_ok=True)
            rich.print(f"[yellow]No output path provided. Saving to user cache:[/yellow] {final_output_path}")

        inst_config_model = load_profile(profile_key)
        
        rich.print(f"Connecting to instrument '{profile_key}' at address '{address}'...")
        instrument = await AutoInstrument.from_config(
            config_source=inst_config_model,
            simulate=False,
            address_override=address
        )
        await instrument.connect_backend()

        # Wrap the real backend with the recording backend
        recording_backend = RecordingBackend(instrument.backend, str(final_output_path))
        instrument.backend = recording_backend
        
        rich.print("[bold green]Connection successful. Recording started.[/bold green]")

        if script:
            rich.print(f"Running script: {script}")
            with open(script) as f:
                script_content = f.read()
            # Create a scope for the script to run in
            script_globals = {
                "instrument": instrument,
                "asyncio": asyncio,
                "__name__": "__main__",
            }
            # The script needs to handle asyncio.run() for async calls.
            exec(script_content, script_globals)
            rich.print("Script execution finished.")
        else:
            rich.print("Starting interactive shell. Type 'quit()' or Ctrl-D to exit.")
            rich.print("The instrument is available as the 'instrument' variable.")
            rich.print("Use 'await instrument.some_method()' for async operations.")
            
            local_vars = {"instrument": instrument, "asyncio": asyncio}
            code.interact(local=local_vars, banner="PyTestLab Interactive Recording Shell")

    except FileNotFoundError:
        rich.print(f"[bold red]Error: Profile for key '{profile_key}' not found.[/bold red]")
        raise typer.Exit(code=1)
    except Exception as e:
        rich.print(f"[bold red]An unexpected error occurred: {e}[/bold red]")
        raise typer.Exit(code=1)
    finally:
        if instrument:
            rich.print("\nClosing connection and saving profile...")
            await instrument.close()
            rich.print(f"[bold green]Profile saved to {final_output_path}.[/bold green]")

# --- Profile Commands ---
@profile_app.command("list")
def list_profiles(profile_dir: Annotated[Optional[Path], typer.Option(help="Custom directory for profiles.")] = None):
    """Lists available YAML instrument profiles."""
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
                for profile_file in profile_dir.glob("*.yaml"): # Assuming flat structure in custom_dir for now
                    profile_paths.append(str(profile_file.resolve()))
            else:
                rich.print(f"[bold yellow]Warning: Custom profile directory '{profile_dir}' not found.[/bold yellow]")

        if not profile_paths:
            rich.print("[bold yellow]No profiles found.[/bold yellow]")
            return

        table = rich.table.Table(title="[bold]Available Profiles[/bold]")
        table.add_column("Profile Key", style="cyan", no_wrap=True)
        for p_path in sorted(list(set(profile_paths))): # Use set to avoid duplicates if custom overlaps
            table.add_row(p_path)
        rich.print(table)
    except Exception as e:
        rich.print(f"[bold red]An unexpected error occurred while listing profiles: {e}[/bold red]")
        raise typer.Exit(code=1)

@profile_app.command("show")
def show_profile(profile_key_or_path: Annotated[str, typer.Argument(help="Profile key (e.g., keysight/DSOX1204G) or direct path to YAML file.")]):
    """Shows the content of a specific instrument profile."""
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
        raise typer.Exit(code=1)
    except yaml.YAMLError as e:
        rich.print(f"[bold red]Error parsing YAML file '{profile_key_or_path}': {e}[/bold red]")
        raise typer.Exit(code=1)
    except Exception as e:
        rich.print(f"[bold red]An unexpected error occurred while showing profile '{profile_key_or_path}': {e}[/bold red]")
        raise typer.Exit(code=1)


@profile_app.command("validate")
def validate_profiles(
    profiles_path: Annotated[Path, typer.Argument(help="Path to a directory of profiles or a single profile file.")]
):
    """Validates YAML profiles against their corresponding Pydantic models."""
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
            load_profile(profile_file)
            rich.print(f"  [green]✔[/green] [cyan]{profile_file.name}[/cyan] - Valid")
            success_count += 1
        except Exception as e:
            rich.print(f"  [bold red]✖[/bold red] [cyan]{profile_file.name}[/cyan] - [red]Invalid[/red]")
            rich.print(f"    [dim]Reason: {e}[/dim]")
            error_count += 1
            
    if error_count > 0:
        rich.print(f"\n[bold]Validation complete:[/bold] [green]{success_count} valid[/green], [red]{error_count} invalid[/red].")
        raise typer.Exit(code=1)
    else:
        rich.print(f"\n[bold green]All {success_count} profiles are valid.[/bold green]")


# --- Instrument Commands ---
@instrument_app.command("idn")
async def instrument_idn(
    profile_key_or_path: Annotated[str, typer.Option(help="Profile key or path.")],
    address: Annotated[Optional[str], typer.Option(help="VISA address. Overrides profile if provided.")] = None,
    simulate: Annotated[bool, typer.Option(help="Run in simulation mode.")] = False
):
    """Connects to an instrument and prints its *IDN? response."""
    instrument = None  # Initialize instrument to None
    try:
        inst_config_model = load_profile(profile_key_or_path)

        instrument = await AutoInstrument.from_config(
            config_source=inst_config_model,
            simulate=simulate,
            address_override=address
        )
        await instrument.connect_backend()
        idn_response = await instrument.id()
        rich.print(f"[bold green]IDN Response:[/bold] {idn_response}")

    except FileNotFoundError:
        rich.print(
            f"[bold red]Error: Profile '{profile_key_or_path}' not found.[/bold red]\n"
            "Please check for typos or ensure the profile exists in the 'pytestlab/profiles' directory."
        )
        raise typer.Exit(code=1)
    except Exception as e:
        rich.print(f"[bold red]An error occurred during the instrument IDN query: {e}[/bold red]")
        # rich.print_exception(show_locals=True) # Uncomment for more detailed debug info
        raise typer.Exit(code=1)
    finally:
        if instrument:
            await instrument.close()

# Implement other commands: instrument selftest, instrument config dump, repl
# For REPL:
# @instrument_app.command("repl")
# async def instrument_repl(...):
#     # ... setup instrument ...
#     # import code
#     # local_vars = {"instrument": instrument, "asyncio": asyncio, "np": np}
#     # code.interact(local=local_vars, banner="PyTestLab REPL...")
#     # For async REPL, might need something like aioconsole or handle awaitables carefully
#     typer.echo("Async REPL not yet fully implemented. Instrument is set up.")
#     # await instrument.close()


# --- Bench Commands (Implement if Bench system from 6.2 is ready) ---
@bench_app.command("ls")
def bench_ls(bench_yaml_path: Annotated[Path, typer.Argument(help="Path to the bench.yaml file.")]):
    """Lists instruments in a bench configuration."""
    try:
        with open(bench_yaml_path, 'r') as f:
            data = yaml.safe_load(f)
        config = BenchConfigExtended.model_validate(data) # Validate
        table = rich.table.Table(title=f"Bench: {config.bench_name}")
        table.add_column("Alias", style="cyan")
        table.add_column("Profile", style="magenta")
        table.add_column("Address", style="green")
        table.add_column("Backend Type", style="yellow")
        table.add_column("Simulate", style="blue")

        for alias, entry in config.instruments.items():
            sim_status = "Global" if entry.simulate is None else str(entry.simulate)
            addr = entry.address or "N/A (simulated)"
            backend_type = (entry.backend.get("type") if entry.backend and entry.backend.get("type") else
                          config.backend_defaults.get("type", "visa") if config.backend_defaults else "visa")
            table.add_row(alias, entry.profile, addr, backend_type, sim_status)
        rich.print(table)
    except FileNotFoundError:
        rich.print(f"[bold red]Error: Bench configuration file not found at '{bench_yaml_path}'.[/bold red]")
        raise typer.Exit(code=1)
    except yaml.YAMLError as e:
        rich.print(f"[bold red]Error parsing YAML file '{bench_yaml_path}': {e}[/bold red]")
        raise typer.Exit(code=1)
    except Exception as e:
        rich.print(f"[bold red]An unexpected error occurred while listing the bench instruments: {e}[/bold red]")
        raise typer.Exit(code=1)

@bench_app.command("validate")
def bench_validate_cli(bench_yaml_path: Annotated[Path, typer.Argument(help="Path to the bench.yaml file.")]):
    """Validates a bench configuration file (dry-run)."""
    try:
        with open(bench_yaml_path, 'r') as f:
            data = yaml.safe_load(f)
        config = BenchConfig.model_validate(data) # This will raise ValidationError on issues
        rich.print(f"[bold green]Bench configuration '{bench_yaml_path}' is valid.[/bold green]")
        
        rich.print("Validating individual instrument profiles...")
        all_profiles_valid = True
        for alias, entry in config.instruments.items():
            try:
                load_profile(entry.profile)
                rich.print(f"  [green]✔[/green] Profile '[magenta]{entry.profile}[/magenta]' for alias '[cyan]{alias}[/cyan]' loaded successfully.")
            except FileNotFoundError:
                all_profiles_valid = False
                rich.print(
                    f"  [bold red]✖ Error:[/bold red] Profile '[magenta]{entry.profile}[/magenta]' for alias '[cyan]{alias}[/cyan]' not found."
                )
            except Exception as e_profile:
                all_profiles_valid = False
                rich.print(f"  [bold red]✖ Error:[/bold red] Failed to load profile '[magenta]{entry.profile}[/magenta]' for alias '[cyan]{alias}[/cyan]': {e_profile}")
        
        if not all_profiles_valid:
            raise typer.Exit(code=1)

    except FileNotFoundError:
        rich.print(f"[bold red]Error: Bench configuration file not found at '{bench_yaml_path}'.[/bold red]")
        raise typer.Exit(code=1)
    except yaml.YAMLError as e:
        rich.print(f"[bold red]Error parsing YAML file '{bench_yaml_path}': {e}[/bold red]")
        raise typer.Exit(code=1)
    except Exception as e:
        rich.print(f"[bold red]An unexpected error occurred during bench validation: {e}[/bold red]")
        raise typer.Exit(code=1)

@bench_app.command("id")
async def bench_id_cli(bench_yaml_path: Annotated[Path, typer.Argument(help="Path to the bench.yaml file.")]):
    """Connects to real instruments in a bench and prints their *IDN? responses."""
    bench = None
    try:
        bench = await Bench.open(bench_yaml_path)
        rich.print(f"Querying *IDN? for instruments in bench: [bold]{bench.config.bench_name}[/bold]")
        
        table = rich.table.Table(title="Instrument IDN Responses")
        table.add_column("Alias", style="cyan")
        table.add_column("Profile", style="magenta")
        table.add_column("IDN Response / Status", style="green")

        for alias, instrument in bench._instrument_instances.items():
            entry = bench.config.instruments[alias]
            is_simulated = bench.config.simulate
            if entry.simulate is not None:
                is_simulated = entry.simulate
            
            if not is_simulated:
                try:
                    idn_str = await instrument.id()
                    table.add_row(alias, entry.profile, idn_str)
                except Exception as e_idn:
                    table.add_row(alias, entry.profile, f"[bold red]Error querying IDN - {e_idn}[/bold red]")
            else:
                table.add_row(alias, entry.profile, "[blue]Simulated[/blue]")
        
        rich.print(table)
    except FileNotFoundError:
        rich.print(f"[bold red]Error: Bench configuration file not found at '{bench_yaml_path}'.[/bold red]")
        raise typer.Exit(code=1)
    except Exception as e:
        rich.print(f"[bold red]An unexpected error occurred during the bench ID query: {e}[/bold red]")
        raise typer.Exit(code=1)
    finally:
        if bench:
            await bench.close_all()

@bench_app.command("sim")
def bench_sim_cli(bench_yaml_path: Annotated[Path, typer.Argument(help="Path to the bench.yaml file.")],
                  output_path: Annotated[Optional[Path], typer.Option(help="Output path for the simulated descriptor.")] = None):
    """Converts a bench descriptor to full simulation mode."""
    try:
        with open(bench_yaml_path, 'r') as f:
            data = yaml.safe_load(f)
        config = BenchConfig.model_validate(data)
        
        sim_config_data = config.model_dump(mode='python') # Get dict representation
        sim_config_data['simulate'] = True # Global simulate
        for alias_key in sim_config_data['instruments']:
            sim_config_data['instruments'][alias_key]['simulate'] = True
            sim_config_data['instruments'][alias_key]['address'] = "sim"
            # Ensure backend is also sim if present
            if sim_config_data['instruments'][alias_key].get('backend'):
               sim_config_data['instruments'][alias_key]['backend']['type'] = "sim"
            else: # If no backend entry, create one for sim
               sim_config_data['instruments'][alias_key]['backend'] = {'type': 'sim', 'timeout_ms': 5000} # Default timeout

        sim_yaml = yaml.dump(sim_config_data, sort_keys=False)
        
        if output_path:
            with open(output_path, 'w') as f_out:
                f_out.write(sim_yaml)
            rich.print(f"[bold green]Simulated bench descriptor saved to:[/bold green] {output_path}")
        else:
            syntax = Syntax(sim_yaml, "yaml", theme="monokai", line_numbers=True)
            rich.print(syntax)
            
    except FileNotFoundError:
        rich.print(f"[bold red]Error: Bench configuration file not found at '{bench_yaml_path}'.[/bold red]")
        raise typer.Exit(code=1)
    except yaml.YAMLError as e:
        rich.print(f"[bold red]Error parsing YAML file '{bench_yaml_path}': {e}[/bold red]")
        raise typer.Exit(code=1)
    except Exception as e:
        rich.print(f"[bold red]An unexpected error occurred while converting the bench to simulation mode: {e}[/bold red]")
        raise typer.Exit(code=1)

# Need an async main for Typer if any command is async
# This is usually handled by Typer itself if you `typer.run(app)`
# For direct script execution:
# if __name__ == "__main__":
#    app() # Typer handles async if any command is async