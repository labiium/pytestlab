# Circuit Simulation

Circuit simulation is the first **simulator lane** in PyTestLab
(`pytestlab.sim.circuit`). Simulators are a first-class PyTestLab feature; the
circuit lane drives a real SPICE engine (ngspice) so you can develop and test
experiments against actual circuit behaviour without hardware. Additional
science lanes (bio, chem, mech) are planned as siblings under `pytestlab.sim`.

## Requirements

The lane has two separate requirements:

1. **The Python lane** — install the extra:

    ```bash
    pip install "pytestlab[circuit]"
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

Node names are validated against the netlist as you reference them, so a typo
fails immediately instead of silently floating:

```python
from pytestlab.sim.circuit import Netlist, Port, SimSession

net = Netlist.from_file("amp.sp")

with SimSession.from_netlist(net) as sim:
    sim.ports(
        vin=Port.signal(net.vin),
        vcc=Port.supply(net.vcc),
        vout=Port.voltage_measurement(net.vout),
    )
    sim.psu("vcc", voltage=5.0, current_limit=0.05).on()
    sim.awg("vin").dc(level=0.8)
    print(sim.dmm("vout").read_dc_voltage())
```

The same lane also backs `circuit_sim` benches, so unchanged driver code can run
against the simulator — see [Simulation Mode](simulation.md).

## Containerised setup

A ready-to-use dev container with ngspice preinstalled lives in
`.devcontainer/`. Open the repository in VS Code (or any Dev Containers host) and
"Reopen in Container", or build the image directly:

```bash
docker build -t pytestlab-circuit -f .devcontainer/Dockerfile .
docker run --rm -it pytestlab-circuit ptl sim doctor
```
