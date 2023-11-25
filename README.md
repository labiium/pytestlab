# ![PyTestLab](pytestlab_logo.png) PyTestLab

A Python library for test and measurement  automation and measurement data management.

`PyTestLab` is a Python library for interfacing with electronic instruments such as oscilloscopes, network analyzers, and arbitrary waveform generators. Designed with ease of use and flexibility in mind, it provides a high-level interface for controlling and acquiring data from these instruments using SCPI commands.

## Features

- **Easy Instrument Control**: Simplified interfaces for common instruments like oscilloscopes and network analyzers.
- **Configurable**: Use pre-defined configurations for popular models or define custom settings.
- **Extensible**: Easily extendable to support additional instruments and features.
- **Example Scripts**: Comes with example scripts demonstrating how to use the library with different instruments.

## Installation

You can install Your Library Name using pip:

```bash
pip install pytestlab
```

Or, clone this repository and install:

```bash
git clone https://github.com/yourgithub/your-library-name.git
cd your-library-name
pip install -e. # install in editable mode
``

Usage
Here's a quick example of how to use the library with an oscilloscope:

```python
from pytestlab.instruments import AutoInstrument

# Connect to an oscilloscope
osc = AutoInstrument.from_preset("keysight/DSOX1204G")

osc.reset()

osc.close()
```

## Acknowledgements

This library was created in part of work funded by Keysight Technologies.
