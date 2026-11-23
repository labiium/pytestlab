# Circuit Simulation

Circuit simulation is the first **simulator lane** in PyTestLab
(`pytestlab.sim.circuit`). Simulators are a first-class PyTestLab feature; the
circuit lane drives a real SPICE engine (ngspice) so you can develop and test
experiments against actual circuit behaviour without hardware. Additional
science lanes (bio, chem, mech) are planned as siblings under `pytestlab.sim`.

## Requirements

The lane has two separate requirements:

1. **The Python lane** — install the 0.3.0 extra once available on PyPI (see [installation](../installation.md)):

    ```bash
    python -m pip install "pytestlab[circuit]==0.3.0"
    ```

2. **The `ngspice` binary** — this is a *system* dependency that pip cannot
   install. Provide it one of these ways:

    | Platform | Command |
    |----------|---------|
    | Debian/Ubuntu | `sudo apt-get install ngspice` |
    | macOS (Homebrew) | `brew install ngspice` |
    | conda | `conda install -c conda-forge ngspice` |
    | Docker | `docker run --rm danchitnis/ngspice ngspice -v` |

    If `ngspice` is installed under a non-standard name or path, point the bench
    at it with the `ngspice_cmd` setting (or the `SIMBENCH_NGSPICE_CMD`
    environment variable).

    PyTestLab can also help via a detected package manager:

    ```bash
    ptl sim install-ngspice        # detect a manager and show the command
    ptl sim install-ngspice --yes  # run it (user-space managers only)
    ```

    It prefers sudo-free, user-space managers (`conda`/`micromamba`/`pixi`/
    `brew`) and will run those for you with consent. Managers that need root
    (`apt-get`/`dnf`/`pacman`/`zypper`/`choco`) are only **printed** for you to
    run yourself — PyTestLab never invokes `sudo` and never assumes you have it.
    If no manager is found it prints the manual options.

If you would rather not install ngspice on your host at all, use the bundled
dev container (see [Containerised setup](#containerised-setup)).

## Check your setup

Run the preflight to confirm both requirements are met:

```bash
ptl sim doctor
```

```
✓ pytestlab.sim.circuit importable
✓ ngspice found: /usr/bin/ngspice
    ngspice-46 : Circuit level simulation program

Circuit simulation lane is ready.
```

If `ngspice` is missing, the command prints the install options above and exits
non-zero, so it can gate a CI job.

## Quickstart

This voltage divider uses two equal resistors. With a 2 V simulated input,
the meter should read about 0.976 V with the default source impedance. Save the netlist as `divider.cir`, then run the
Python example from the same directory. Node names are validated against the
netlist.

```text
Voltage divider
R1 vin vout 1k
R2 vout 0 1k
.end
```

```python
from pytestlab.sim.circuit import Netlist, Port, SimSession

net = Netlist.from_file("divider.cir")

with SimSession.from_netlist(net).ports(
    input=Port.signal(net.vin),
    output=Port.voltage_measurement(net.vout),
) as sim:
    sim.awg("input").dc(level=2.0)
    print(sim.dmm("output").read_dc_voltage())
```

The same lane also backs `circuit_sim` benches, so unchanged driver code can run
against the simulator — see [Simulation Mode](simulation.md).

## Simulation telemetry

Reuse `divider.cir` from the quickstart. A local recorder persists the
analysis duration, requested and returned vectors, provenance metadata, and
structural health status.

```python
from pathlib import Path

from pytestlab.sim.circuit import ArtifactStore, Netlist, Port, SimSession, Telemetry

net = Netlist.from_file("divider.cir")
telemetry = Telemetry(ArtifactStore(Path(".pytestlab_sim/telemetry")))

with SimSession.from_netlist(net, telemetry=telemetry).ports(
    input=Port.signal(net.vin),
    output=Port.voltage_measurement(net.vout),
) as sim:
    sim.awg("input").dc(level=2.0)
    sim.dmm("output").read_dc_voltage()

for event in telemetry.events():
    print(event["event"], event["payload"].get("status"))
```

A telemetry `pass` means the simulator returned finite, shape-consistent
requested vectors. It does not prove that the model matches physical hardware;
use calibrated-twin or expected-value validation for that claim.

## Containerised setup

A ready-to-use dev container with ngspice preinstalled lives in
`.devcontainer/`. Open the repository in VS Code (or any Dev Containers host) and
"Reopen in Container", or build the image directly:

```bash
docker build -t pytestlab-circuit -f .devcontainer/Dockerfile .
docker run --rm -it pytestlab-circuit ptl sim doctor
```
