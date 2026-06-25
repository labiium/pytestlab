# pytestlab/cli.py
from __future__ import annotations

import code
import contextlib
import difflib
import importlib.util  # For finding profile paths
import json
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
        typer.Option(help="LAMB server base URL. Overrides LAMB_SERVER environment variable."),
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


def _resolve_profile_path(profile_key_or_path: str) -> Path:
    from pytestlab.config.loader import resolve_profile_key_to_path

    potential_path = Path(profile_key_or_path)
    if potential_path.suffix in {".yaml", ".yml"} and potential_path.is_file():
        return potential_path
    return resolve_profile_key_to_path(profile_key_or_path)


def _active_scpi_blocks(scpi_section: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    variants = scpi_section.get("variants")
    if isinstance(variants, dict):
        variant = scpi_section.get("default_variant")
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


def _profile_scpi_command_rows(
    profile_key_or_path: str,
    *,
    device: Any | None = None,
    include_writes: bool = False,
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

    commands, queries = _active_scpi_blocks(scpi_section)
    engine = SCPIEngine(scpi_section)
    rows: list[dict[str, str]] = []
    failures = 0
    warnings = 0
    skipped = 0

    for kind, entries in (("command", commands), ("query", queries)):
        for alias, raw_spec in entries.items():
            params: dict[str, Any] = {}
            try:
                description = engine.describe(str(alias))
                params = _sample_params_for_spec(
                    raw_spec, cast(dict[str, dict[str, Any]], description["parameters"])
                )
                rendered = engine.build(alias, **params)
                response = ""
                if device is not None:
                    if kind == "command" and not include_writes:
                        skipped += 1
                        rows.append(
                            {
                                "alias": str(alias),
                                "kind": kind,
                                "status": "skip",
                                "sample": ", ".join(f"{k}={v!r}" for k, v in params.items()) or "-",
                                "detail": "write command skipped; use --include-writes --yes",
                            }
                        )
                        continue
                    for message in rendered:
                        if kind == "query" or message.strip().endswith("?"):
                            response = device.query(message)
                        else:
                            device.write(message)
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
                    "kind": kind,
                    "status": status,
                    "sample": ", ".join(f"{k}={v!r}" for k, v in params.items()) or "-",
                    "detail": detail,
                }
            )

    return profile_path, rows, failures, warnings, skipped


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
        notes.append(f"{skipped} write commands skipped")
    note_text = f" ({', '.join(notes)})" if notes else ""
    rich.print(f"[bold green]All {total} instrument command checks passed[/bold green]{note_text}.")


@instrument_app.command("check-commands")
def instrument_check_commands(
    profile_key_or_path: Annotated[str, typer.Argument(help="Profile key or YAML path.")],
):
    """Build every SCPI command/query alias without touching any instrument."""
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
    table.add_column("Missing Required Aliases")
    table.add_column("Missing Parameters")

    missing_required_enabled = 0
    for operation_id, operation_report in report.items():
        descriptor = instrument.describe_operation(operation_id)
        missing_required = operation_report["missing_required_aliases"]
        missing_parameters = operation_report.get("missing_parameter_metadata", [])
        capability = descriptor["capability"] or "-"
        required = bool(operation_report["required"])
        if not operation_report["capability_enabled"]:
            status = "[yellow]unsupported[/yellow]"
        elif missing_required or missing_parameters:
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
            ", ".join(missing_required) or "-",
            ", ".join(missing_parameters) or "-",
        )
    rich.print(table)

    if missing_required_enabled:
        rich.print(
            f"[bold red]{missing_required_enabled} required enabled operations miss SCPI aliases or parameter metadata.[/bold red]"
        )
        if strict:
            raise typer.Exit(code=1)
    else:
        rich.print("[bold green]All enabled operation contract checks passed[/bold green].")


@instrument_app.command("describe-operation")
def instrument_describe_operation(
    profile_key_or_path: Annotated[str, typer.Argument(help="Profile key or YAML path.")],
    operation_id: Annotated[str, typer.Argument(help="Operation ID to describe.")],
    include_scpi: Annotated[
        bool,
        typer.Option("--include-scpi", help="Include bound SCPI alias metadata."),
    ] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Emit JSON.")] = False,
):
    """Describe one high-level operation for a profile."""

    try:
        from pytestlab import AutoInstrument

        if as_json:
            with contextlib.redirect_stdout(sys.stderr):
                instrument = AutoInstrument.from_config(profile_key_or_path, simulate=True)
        else:
            instrument = AutoInstrument.from_config(profile_key_or_path, simulate=True)
        result = instrument.describe_operation(operation_id, include_scpi=include_scpi)
    except Exception as exc:
        rich.print(f"[bold red]Operation description failed: {rich_escape(str(exc))}[/]")
        raise typer.Exit(code=1) from None

    if as_json:
        rich.print(json.dumps(result, indent=2, sort_keys=True, default=str))
    else:
        rich.print(result)


@instrument_app.command("list-options")
def instrument_list_options(
    profile_key_or_path: Annotated[str, typer.Argument(help="Profile key or YAML path.")],
    operation_id: Annotated[str, typer.Argument(help="Operation ID.")],
    parameter: Annotated[str, typer.Argument(help="Operation parameter name.")],
    as_json: Annotated[bool, typer.Option("--json", help="Emit JSON.")] = False,
):
    """List raw SCPI options for one operation parameter."""

    try:
        from pytestlab import AutoInstrument

        if as_json:
            with contextlib.redirect_stdout(sys.stderr):
                instrument = AutoInstrument.from_config(profile_key_or_path, simulate=True)
        else:
            instrument = AutoInstrument.from_config(profile_key_or_path, simulate=True)
        result = instrument.list_operation_options(operation_id, parameter)
    except Exception as exc:
        rich.print(f"[bold red]Option listing failed: {rich_escape(str(exc))}[/]")
        raise typer.Exit(code=1) from None

    if as_json:
        rich.print(json.dumps(result, indent=2, sort_keys=True, default=str))
    else:
        rich.print(result)


@instrument_app.command("full-test")
def instrument_full_test(
    profile_key_or_path: Annotated[str, typer.Argument(help="Profile key or YAML path.")],
    address: Annotated[
        str | None,
        typer.Option(
            "--address",
            "-a",
            help="Real instrument address. For LAMB, this is the server-side VISA resource string.",
        ),
    ] = None,
    backend: Annotated[
        str,
        typer.Option(
            "--backend",
            help="Real backend to use: visa or lamb.",
        ),
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
            help="Execute profile command aliases that write/change instrument state.",
        ),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            "-y",
            help="Confirm real write commands may change instrument state.",
        ),
    ] = False,
    timeout_ms: Annotated[
        int,
        typer.Option("--timeout-ms", help="Communication timeout for the real instrument."),
    ] = 5000,
    strict_response: Annotated[
        bool,
        typer.Option("--strict-response", help="Fail when a real query returns an empty response."),
    ] = True,
):
    """Run SCPI command/query checks against a real instrument."""
    if include_writes and not yes:
        rich.print(
            "[bold red]Refusing to execute write commands without --yes.[/bold red]\n"
            "Writes can change output state, voltage/current settings, trigger setup, panel locks, "
            "and other instrument state."
        )
        raise typer.Exit(code=1)

    from pytestlab.devices import AutoDevice

    backend_lc = backend.lower()
    if backend_lc not in {"visa", "lamb"}:
        rich.print("[bold red]Error: --backend must be 'visa' or 'lamb'.[/bold red]")
        raise typer.Exit(code=1)
    if backend_lc == "visa" and not address:
        rich.print("[bold red]Error: --address is required for --backend visa.[/bold red]")
        raise typer.Exit(code=1)

    device = None
    try:
        backend_override = None
        backend_type_hint = backend_lc
        if backend_lc == "lamb":
            from pytestlab.instruments.backends.lamb import LambBackend

            profile_path = _resolve_profile_path(profile_key_or_path)
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
            include_writes=include_writes,
            strict_response=strict_response,
        )
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
        title="Real Instrument Full Test",
        profile_path=profile_path,
        rows=rows,
        failures=failures,
        warnings=warnings,
        skipped=skipped,
    )


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
