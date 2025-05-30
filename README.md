# ![PyTestLab](pytestlab_logo.png) PyTestLab

A Python library for test and measurement  automation and measurement data management.

`PyTestLab` is a Python library for interfacing with electronic instruments such as oscilloscopes, network analyzers, and arbitrary waveform generators. Designed with ease of use and flexibility in mind, it provides a high-level interface for controlling and acquiring data from these instruments using SCPI commands under the hood.

## Features

- **Easy Instrument Control**: Simplified interfaces for common instruments like oscilloscopes and network analyzers.
- **Configurable**: Use pre-defined configurations for popular models or define custom settings.
- **Extensible**: Easily extendable to support additional instruments and features.
- **Example Scripts**: Comes with example scripts demonstrating how to use the library with different instruments.

## Installation

You can install the library using inside the folder of the library:

```bash
pip install .
```

Or, clone this repository and install:

```bash
pip install -e . # install in editable mode
```

Usage
Here's a quick example of how to use the library with an oscilloscope:

```python
from pytestlab.instruments import AutoInstrument
from pytestlab.experiments import Database

# loading the instruments
osc = AutoInstrument.from_config("keysight/DSOX1204G")

channel_readings = osc.read_channels(1)

data = channel_readings[1]


print(channel_readings)
print(data)
# Only works in Python Notebook
channel_readings.plot()
data.plot()
```

Here is an example of a sweep on a power supply:

```python
from pytestlab.instruments import AutoInstrument
from pytestlab.experiments import Experiment, Database
import numpy as np

# loading the instruments
psu1 = AutoInstrument.from_config("keysight/EDU36311A", "SERIAL_NUMBER") # to connect to muliple instruments
psu2 = AutoInstrument.from_config("keysight/EDU36311A", "SERIAL_NUMBER") # to connect to one instrument
dmm = AutoInstrument.from_config("keysight/EDU34450A")


psu1.set_voltage(2, 5)
psu1.set_current(2, 0.05)
psu1.output(2)

psu2.set_voltage(1, 1.8)
psu2.set_current(1, 0.05)
psu2.output(1)

psu.set_voltage(3, 3.0)
psu1.set_current(3, 0.05)
psu1.output(3)

data = dmm.measure()
print(data)
print(data.values)

psu1.output([2,3], state=False)
psu2.output(1, state=False)
```

## Acknowledgements

This library was created in part of work funded by Keysight Technologies.

## Simulation Mode

PyTestLab now includes a simulation backend, allowing for development, testing, and CI runs without requiring physical hardware.

There are two ways to enable simulation mode:

1.  **Environment Variable:** Set the `PYTESTLAB_SIMULATE=1` environment variable before running your script.
    ```bash
    PYTESTLAB_SIMULATE=1 python your_experiment_script.py
    ```

2.  **Programmatic Flag:** Pass the `simulate=True` argument when creating an instrument instance using `AutoInstrument.from_config`:
    ```python
    from pytestlab.instruments import AutoInstrument

    # Example using a config dictionary
    mock_config = {"device_type": "power_supply", "model": "SimPSU", "address": "SIM"}
    psu = AutoInstrument.from_config(mock_config, simulate=True)

    print(psu.query("*IDN?")) # Interacts with the SimBackend
    ```

The simulation backend uses the instrument's configuration profile to provide basic responses. For more complex simulations, the `SimBackend` class in `pytestlab.sim.backend` can be extended or customized.

## Handling Uncertainties

PyTestLab now supports measurements with uncertainties, leveraging the `uncertainties` library. This allows for more rigorous scientific data analysis by propagating errors through calculations.

**Configuration:**
Instrument YAML configuration files can now include an optional `measurement_accuracy` block. This block defines accuracy specifications for different measurement modes or ranges of an instrument.

Example for a multimeter's YAML profile:
```yaml
# ... other config ...
device_type: multimeter
model: ExampleDMM
measurement_accuracy:
  voltage_dc_1V_range: # Key identifying the mode/range
    percent_reading: 0.0005    # 0.05% of reading
    offset_value: 0.0001     # 0.1mV offset
  current_ac_1A_range:
    percent_reading: 0.001
    offset_value: 0.0005
```
The structure of these specifications is defined by the `AccuracySpec` model in `pytestlab.config.accuracy`.

**Usage:**
When an instrument driver performs a measurement for which an accuracy specification is defined and found in its configuration, it will return a `ufloat` object from the `uncertainties` library. This object encapsulates both the nominal value and its associated standard deviation.

```python
from pytestlab.instruments import AutoInstrument
from uncertainties import ufloat

# dmm configured with measurement_accuracy
dmm = AutoInstrument.from_config("path/to/your_dmm_profile.yaml") 

voltage_reading = dmm.read_voltage() # Assuming this method uses the spec

if isinstance(voltage_reading, ufloat):
    print(f"Voltage: {voltage_reading}")
    print(f"Nominal: {voltage_reading.nominal_value:.4f} V")
    print(f"Std Dev: {voltage_reading.std_dev:.4f} V")
else:
    print(f"Voltage: {voltage_reading:.4f} V (no uncertainty)")
```

**MeasurementResult:**
The `MeasurementResult` class (in `pytestlab.experiments.results`) can now store these `ufloat` values. It provides `.nominal` and `.sigma` properties to easily access the nominal value and standard deviation. When saving data to a database (e.g., using the Polars-based database backend), `ufloat` objects are typically serialized into two separate columns (e.g., `value_nominal` and `value_sigma`).
