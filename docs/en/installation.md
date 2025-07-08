# Installation

PyTestLab requires **Python 3.9** or higher.

## Standard Installation

We recommend installing PyTestLab in a virtual environment.

```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

You can install PyTestLab from PyPI using `pip`.

### Core Package

For the core functionality:

```bash
pip install pytestlab
```

### Full Installation

To include all optional dependencies for plotting, extended data formats, and development tools:

```bash
pip install pytestlab[full]
```

## VISA Backend Support

To communicate with most physical instruments, you will need to install a VISA backend library. PyTestLab uses `pyvisa` to interface with these libraries.

1. **Install a VISA implementation** from your hardware vendor:
    - [National Instruments NI-VISA](https://www.ni.com/visa/)
    - [Keysight IO Libraries Suite](https://www.keysight.com/find/iosuites)
    - [Rohde & Schwarz VISA](https://www.rohde-schwarz.com/us/products/test-and-measurement/software/visa-software/visa-software_63493-1066743.html)

2. **Install `pyvisa`**:

    ```bash
    pip install pyvisa
    ```

PyTestLab will automatically detect and use the installed VISA backend.

## Upgrading

To upgrade PyTestLab to the latest version:

```bash
pip install --upgrade pytestlab
```

## Verifying Your Installation

After installation, you can verify that PyTestLab is installed and working:

```bash
pytestlab --version
pytestlab profile list
```

If you see a list of available instrument profiles, your installation is successful.

## Troubleshooting

- If you encounter issues with instrument connectivity, ensure your VISA library is installed and accessible in your system's PATH.
- For simulation-only development, you do **not** need to install any VISA libraries.

## Next Steps

- [Getting Started Guide](getting_started.md)
- [Async vs. Sync Programming](async_vs_sync.md)
- [Connecting to Instruments](connecting.md)