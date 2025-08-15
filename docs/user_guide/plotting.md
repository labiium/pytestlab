## Plotting in PyTestLab

PyTestLab provides a lightweight plotting layer with a default matplotlib backend, designed for quick visualization of experiments, sessions, and measurement results.

Install plotting extras:
```bash
pip install 'pytestlab[plot]'
```

### Key objects
- `pytestlab.plotting.PlotSpec`: Declarative plot configuration (kind, x, y, title, labels, legend, grid).
- `Experiment.plot(...)`: Plots the experiment's `polars.DataFrame`.
- `MeasurementSession.plot(...)`: Plots session data after `run()`.
- `MeasurementResult.plot(...)`: Plots a `polars.DataFrame` or 1D arrays (uses `sampling_rate` for time axis).

### Simple examples
```python
from pytestlab.experiments import Experiment
from pytestlab.plotting import PlotSpec

exp = Experiment("Voltage Sweep")
exp.add_trial({"Time (s)": [0,1,2], "Voltage (V)": [0.0, 1.2, 2.4]})
fig = exp.plot(PlotSpec(title="Experiment Plot"))
```

```python
import numpy as np
from pytestlab.experiments import MeasurementResult
from pytestlab.plotting import PlotSpec

arr = np.sin(np.linspace(0, 2*np.pi, 500))
res = MeasurementResult(values=arr, instrument="sim", units="V", measurement_type="sine", sampling_rate=1000.0)
fig = res.plot(PlotSpec(title="Sine Wave"))
```

```python
from pytestlab.measurements import MeasurementSession
from pytestlab.plotting import PlotSpec

with MeasurementSession("Quick Session") as session:
    @session.acquire
    def sample():
        return {"Time (s)": [0,1,2], "Value": [0.1, 0.2, 0.1]}

    experiment = session.run()
    fig = session.plot(PlotSpec(title="Session Data"))
```

### Oscilloscope: Keysight DSOX1204G
```python
from pytestlab.instruments import AutoInstrument
from pytestlab.plotting import PlotSpec

scope = AutoInstrument.from_config("keysight/DSOX1204G", simulate=True)
scope.connect_backend()

result = scope.read_channels(1, 2)
result.plot(PlotSpec(title="DSOX1204G CH1 & CH2"))

scope.close()
```

### Splitting channel results

`Oscilloscope.read_channels(...)` returns a `ChannelReadingResult` that is indexable by channel number and exposes time:

```python
res = scope.read_channels(1, 2, 3)
ch1 = res[1]        # Channel 1 + time
ch3 = res.for_channel(3)
t = res.time        # numpy array of Time (s)
available = res.channels  # [1, 2, 3]

ch1.plot(title="Channel 1")
```

### Notes
- The plotting backend is optional; if matplotlib is missing, a clear error suggests installing `pytestlab[plot]`.
- Default x-axis detection prefers `"Time (s)"` when present.
- For 1D arrays, `MeasurementResult.plot` uses `sampling_rate` to generate a time axis; otherwise uses index.


