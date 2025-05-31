# ![PyTestLab](pytestlab_logo.png) PyTestLab

A Python library for test and measurement automation and measurement data management.

`PyTestLab` is a Python library for interfacing with electronic instruments such as oscilloscopes, network analyzers, and arbitrary waveform generators. Designed with ease of use and flexibility in mind, it provides a high-level interface for controlling and acquiring data from these instruments using SCPI commands under the hood.

For comprehensive documentation, including user guides, API references, and tutorials, please visit our **[MkDocs Documentation Site](./docs/index.md)** (link to be updated once site is deployed).

## Key Features

- **Easy Instrument Control**: Simplified interfaces for common instruments.
- **Configurable**: Use pre-defined configurations or define custom settings.
- **Extensible**: Easily extendable to support additional instruments.
- **Simulation Mode**: Develop and test without physical hardware.
- **Uncertainty Handling**: Support for measurements with uncertainties.
- **Data Management**: Tools for organizing and storing experimental data.

## Installation

Install the library using pip:

```bash
pip install pytestlab # Or: pip install .
```
(Note: If installing from a local clone, use `pip install .` or `pip install -e .` for editable mode.)

## Quick Example

```python
from pytestlab.instruments import AutoInstrument

# Load an instrument using its configuration profile
osc = AutoInstrument.from_config("keysight/DSOX1204G") # Assumes profile is available

# Example: Read data from channel 1
channel_readings = osc.read_channels(1)
data_ch1 = channel_readings[1]

print(f"Data from Channel 1: {data_ch1.values}")

# For more examples and detailed usage, please see the full documentation.
```

## Dive Deeper

Explore the full capabilities of PyTestLab:

*   **[Installation Guide](./docs/installation.md)**
*   **[User Guide](./docs/user_guide/getting_started.md)**
*   **[10 Minute Tour](./docs/tutorials/10_minute_tour.ipynb)**
*   **[API Reference](./docs/api/instruments.md)**
*   **[Instrument Profiles](./docs/profiles/gallery.md)**

## Acknowledgements

This library was created in part of work funded by Keysight Technologies.
