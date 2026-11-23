# Installation

These examples use **PyTestLab 0.3.0** and **Python 3.11 or newer**. The
simulated first measurement needs no hardware, instrument address, or VISA
runtime.

## Standard Installation

Create a virtual environment and install PyTestLab:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install "pytestlab==0.3.0"
```

In Windows PowerShell, activate with `.\.venv\Scripts\Activate.ps1` instead.
Plotting and scientific-data support are included in the default install.

If PyPI does not list 0.3.0 yet, install from the matching source checkout
with `python -m pip install .` or wait for the release. Earlier versions may
not support these examples.

## Verifying Your Installation

```bash
ptl --version
ptl profile list
```

Then [run your first simulated measurement](user_guide/getting_started.md#2-your-first-measurement-simulated).
The built-in profile list is not a hardware inventory.

## VISA Backend Support

Skip this section unless you are connecting physical equipment through VISA.
The PyVISA Python package is already installed with PyTestLab. Use your
existing VISA backend, or install a suitable one such as
[NI-VISA](https://www.ni.com/visa/) or
[Keysight IO Libraries Suite](https://www.keysight.com/find/iosuites) if needed.

For supported transports, you can install
[PyVISA-py](https://pyvisa.readthedocs.io/projects/pyvisa-py/en/stable/installation.html)
and select it explicitly in your shell:

```bash
python -m pip install pyvisa-py
export PYVISA_LIBRARY=@py
```

Run `pyvisa-info` to check the backend and `ptl visa list` to list visible
resources. Some addresses, such as TCP/IP sockets, do not appear in default
discovery. Copy the exact resource into `address` with
`backend: {type: visa}` in [bench.yaml](bench-yaml.md), then follow
[Connecting to Instruments](user_guide/connecting.md#real-instrument).

## Upgrading

In 0.3.0, `ptl run --simulate` forces supported built-in simulation for the
whole bench or refuses the run. It does not sandbox your Python script. See the
[changelog](changelog.md) for other changes. For development dependencies,
install `".[dev]"` from a source checkout.
