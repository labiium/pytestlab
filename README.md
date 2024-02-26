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

db = Database("osc_reading")

print(data)

# A codename is a unique identifier for the measurement
db.store_measurement("osc_reading", data)

# A codename is a unique identifier for the measurement
measurement_data = db.retrieve_measurement("osc_reading")

print(measurement_data)

osc.close()
```

Here is an example of a sweep on a power supply:

```python
from pytestlab.instruments import AutoInstrument
from pytestlab.experiments import Experiment, Database
import numpy as np

# loading the instruments
psu = AutoInstrument.from_config("keysight/EDU36311A")
dmm = AutoInstrument.from_config("keysight/EDU34450A")

experiment = Experiment(
    name="sweep",
    description="Sweeping the voltage of the PSU and measuring the voltage with the DMM."
)

# setting up the experiment
experiment.add_parameter("psu_voltage", "V", "Voltage of the PSU.")


psu.set_voltage(2, 5)
psu.set_current(2, 0.05)

psu.set_voltage(1, 1.8)
psu.set_current(1, 0.05)

# psu.set_voltage(3, 3.0)
psu.set_current(3, 0.05)
psu.output(3)


for psu_voltage in np.linspace(0, 5, 100):
    psu.set_voltage(3, psu_voltage)
    # DMM measure command is a blocking command
    experiment.add_trial(dmm.measure(int_time="Fast"), psu_voltage=psu_voltage)


# saving the results
db = Database("psu_sweep")

# A codename is a unique identifier for the experiment
db.store_experiment("psu_sweep", experiment)

# A codename is a unique identifier for the experiment
experiment_data = db.retrieve_experiment("psu_sweep")


for trial in experiment:
    print(trial)
```

## Acknowledgements

This library was created in part of work funded by Keysight Technologies.
