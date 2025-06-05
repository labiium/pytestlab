# pytestlab/cli.py
import typer
from typing_extensions import Annotated # For older Python, or just use `typing.Annotated` for Py 3.9+
from typing import Optional # Ensure Optional is imported
from pathlib import Path
import yaml
import rich # For pretty printing
import importlib.util # For finding profile paths
import pkgutil # For finding profile paths

# Assuming these imports are valid after recent refactors
from pytestlab.config.loader import load_profile
from pytestlab.instruments import AutoInstrument
# For bench commands (anticipating section 6.2)
from pytestlab.config.bench_config import BenchConfigExtended
from pytestlab.bench import Bench
import asyncio # For running async CLI commands

app = typer.Typer(help="PyTestLab: Scientific test & measurement toolbox CLI.")
profile_app = typer.Typer(name="profile", help="Manage instrument profiles.")
instrument_app = typer.Typer(name="instrument", help="Interact with instruments.")
bench_app = typer.Typer(name="bench", help="Manage bench configurations.")

app.add_typer(profile_app)
app.add_typer(instrument_app)
app.add_typer(bench_app)

# --- Profile Commands ---
@profile_app.command("list")
def list_profiles(profile_dir: Annotated[Optional[Path], typer.Option(help="Custom directory for profiles.")] = None):
    """Lists available YAML instrument profiles."""
    profile_paths = []
    # Logic to find profiles in default package dir (pytestlab/profiles)
    try:
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
            typer.echo("Could not find default profiles package.")
    except Exception as e:
        typer.echo(f"Error discovering default profiles: {e}")

    # Add logic for custom_dir if provided
    if profile_dir:
        if profile_dir.is_dir():
            for profile_file in profile_dir.glob("*.yaml"): # Assuming flat structure in custom_dir for now
                profile_paths.append(str(profile_file.resolve()))
        else:
            typer.echo(f"Warning: Custom profile directory '{profile_dir}' not found.")

    if not profile_paths:
        typer.echo("No profiles found.")
        return

    typer.echo("Available profiles:")
    for p_path in sorted(list(set(profile_paths))): # Use set to avoid duplicates if custom overlaps
        typer.echo(f"  {p_path}")

@profile_app.command("show")
def show_profile(profile_key_or_path: Annotated[str, typer.Argument(help="Profile key (e.g., keysight/DSOX1204G) or direct path to YAML file.")]):
    """Shows the content of a specific instrument profile."""
    try:
        # Attempt to load using load_profile, which resolves keys and paths
        # load_profile now returns a Pydantic model. We need its source data or to dump it.
        # For now, let's assume load_profile can give us the raw data or we have a helper.
        # This part needs careful implementation based on how load_profile works or if a new helper is needed.

        # Simplified approach: try direct path first, then key resolution
        profile_path = Path(profile_key_or_path)
        if profile_path.exists() and profile_path.is_file():
            pass # Path is good
        else: # Try to resolve as key
            # This requires a robust key_to_path resolver
            # Placeholder for key_to_path logic:
            try:
                # Assuming load_profile can take a key and we can get path from it, or it raises if not found
                # For now, we'll just try to load it and if it fails, it fails.
                # To show raw content, we'd ideally load the raw YAML before Pydantic parsing.
                # This is a bit tricky with the current load_profile.
                # A dedicated function to get profile path from key might be better.
                # config_model = load_profile(profile_key_or_path) # This validates
                # rich.print(config_model.model_dump(mode='json')) # Print Pydantic model

                # Attempt to find the file path from key for raw display
                parts = profile_key_or_path.split('/')
                resolved_path = None
                if len(parts) == 2:
                    vendor, pfile = parts[0], parts[1] + ".yaml"
                    spec = importlib.util.find_spec("pytestlab.profiles")
                    if spec and spec.origin:
                        base_path = Path(spec.origin).parent
                        test_path = base_path / vendor / pfile
                        if test_path.exists():
                            resolved_path = test_path
                if resolved_path:
                    profile_path = resolved_path
                else:
                    typer.echo(f"Error: Profile key '{profile_key_or_path}' could not be resolved to a file.")
                    raise typer.Exit(code=1)
            except Exception as e: # Catch if load_profile fails
                 typer.echo(f"Error resolving profile key '{profile_key_or_path}': {e}")
                 raise typer.Exit(code=1)

        with open(profile_path, 'r') as f:
            content = yaml.safe_load(f)
            rich.print(content)
    except Exception as e:
        typer.echo(f"Error processing profile '{profile_key_or_path}': {e}")
        raise typer.Exit(code=1)

# --- Instrument Commands ---
@instrument_app.command("idn")
async def instrument_idn( # Make async
    profile_key_or_path: Annotated[str, typer.Option(help="Profile key or path.")], # Use Option for clarity
    address: Annotated[Optional[str], typer.Option(help="VISA address. Overrides profile if provided.")] = None,
    simulate: Annotated[bool, typer.Option(help="Run in simulation mode.")] = False
):
    """Connects to an instrument and prints its *IDN? response."""
    # Note: AutoInstrument.from_config is now async
    # load_profile returns a Pydantic model
    try:
        inst_config_model = load_profile(profile_key_or_path) # This is sync

        # AutoInstrument.from_config expects a Pydantic model or dict
        # It also handles simulation and address override internally now due to bench.yaml prep

        instrument = await AutoInstrument.from_config(
            config_source=inst_config_model, # Pass the Pydantic model
            simulate=simulate,
            address_override=address # Pass address override
        )
        await instrument.connect_backend() # Explicit connect
        idn_response = await instrument.id() # id() is now async
        typer.echo(idn_response)
        await instrument.close()
    except Exception as e:
        typer.echo(f"Error: {e}")
        rich.print_exception() # For more detailed error output during dev
        raise typer.Exit(code=1)

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
    except Exception as e:
        typer.echo(f"Error loading or parsing bench file '{bench_yaml_path}': {e}")
        raise typer.Exit(code=1)

@bench_app.command("validate")
def bench_validate_cli(bench_yaml_path: Annotated[Path, typer.Argument(help="Path to the bench.yaml file.")]):
    """Validates a bench configuration file (dry-run)."""
    try:
        with open(bench_yaml_path, 'r') as f:
            data = yaml.safe_load(f)
        config = BenchConfig.model_validate(data) # This will raise ValidationError on issues
        typer.echo(f"Bench configuration '{bench_yaml_path}' is valid.")
        # Further validation: try to load_profile for each instrument entry
        for alias, entry in config.instruments.items():
            try:
                load_profile(entry.profile)
                typer.echo(f"  - Profile '{entry.profile}' for alias '{alias}' loaded successfully.")
            except Exception as e_profile:
                typer.echo(f"  - Error loading profile '{entry.profile}' for alias '{alias}': {e_profile}")
    except Exception as e:
        typer.echo(f"Error validating bench file '{bench_yaml_path}': {e}")
        raise typer.Exit(code=1)

@bench_app.command("id")
async def bench_id_cli(bench_yaml_path: Annotated[Path, typer.Argument(help="Path to the bench.yaml file.")]):
    """Connects to real instruments in a bench and prints their *IDN? responses."""
    try:
        bench = await Bench.open(bench_yaml_path)
        typer.echo(f"Querying *IDN? for real instruments in bench: {bench.config.bench_name}")
        for alias, instrument in bench._instrument_instances.items():
            entry = bench.config.instruments[alias]
            # Determine if the specific instrument is simulated
            # Global simulate flag (bench.config.simulate)
            # Per-instrument simulate flag (entry.simulate)
            # If entry.simulate is None, global simulate flag is used.
            # If entry.simulate is True/False, it overrides global.
            is_simulated = bench.config.simulate
            if entry.simulate is not None:
                is_simulated = entry.simulate
            
            if not is_simulated:
                try:
                    idn_str = await instrument.id()
                    typer.echo(f"  {alias} ({entry.profile}): {idn_str}")
                except Exception as e_idn:
                    typer.echo(f"  {alias} ({entry.profile}): Error querying IDN - {e_idn}")
            else:
                typer.echo(f"  {alias} ({entry.profile}): Simulated")
        await bench.close_all()
    except Exception as e:
        typer.echo(f"Error during bench ID query for '{bench_yaml_path}': {e}")
        raise typer.Exit(code=1)

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
            typer.echo(f"Simulated bench descriptor saved to: {output_path}")
        else:
            rich.print(sim_yaml)
            
    except Exception as e:
        typer.echo(f"Error converting bench to sim mode for '{bench_yaml_path}': {e}")
        raise typer.Exit(code=1)

# Need an async main for Typer if any command is async
# This is usually handled by Typer itself if you `typer.run(app)`
# For direct script execution:
# if __name__ == "__main__":
#    app() # Typer handles async if any command is async