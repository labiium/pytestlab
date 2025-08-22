import numpy as np

from pytestlab.experiments import MeasurementResult
from pytestlab.plotting import PlotSpec


def main():
    t = np.linspace(0, 1, 1000)
    y = np.sin(2 * np.pi * 50 * t)

    res = MeasurementResult(
        values=y, instrument="sim", units="V", measurement_type="sine", sampling_rate=1000.0
    )
    fig = res.plot(PlotSpec(title="Sine @ 50 Hz"))
    fig.show()


if __name__ == "__main__":
    main()
