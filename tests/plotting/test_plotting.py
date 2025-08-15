import pytest
import polars as pl


matplotlib = pytest.importorskip("matplotlib")
matplotlib.use("Agg", force=True)
plt = pytest.importorskip("matplotlib.pyplot")


def test_plot_dataframe_basic():
    from pytestlab.plotting import PlotSpec, plot_dataframe

    df = pl.DataFrame({
        "Time (s)": [0.0, 0.1, 0.2, 0.3],
        "A": [0.0, 1.0, 0.0, -1.0],
        "B": [1.0, 0.0, -1.0, 0.0],
    })

    fig = plot_dataframe(df, PlotSpec(title="DF Test"))
    assert hasattr(fig, "savefig")
    assert fig.axes, "Expected at least one axis"
    ax = fig.axes[0]
    assert ax.get_xlabel() == "Time (s)"


def test_plot_ndarray_time_axis():
    import numpy as np
    from pytestlab.plotting import PlotSpec, plot_ndarray

    arr = np.linspace(0, 1, 1000)
    fig = plot_ndarray(arr, PlotSpec(title="Array"), sampling_rate=100.0, units="V")
    ax = fig.axes[0]
    assert ax.get_xlabel() == "Time (s)"
    lines = ax.get_lines()
    assert len(lines) == 1
    xdata = lines[0].get_xdata()
    ydata = lines[0].get_ydata()
    assert len(xdata) == len(ydata) == 1000


def test_experiment_plot():
    from pytestlab.experiments import Experiment
    from pytestlab.plotting import PlotSpec

    exp = Experiment("Voltage Sweep")
    exp.add_trial({"Time (s)": [0, 1, 2], "Voltage (V)": [0.0, 1.2, 2.4]})

    fig = exp.plot(PlotSpec(title="Experiment Plot"))
    ax = fig.axes[0]
    # For single y series, ylabel should default to the series name
    assert ax.get_ylabel() in ("Voltage (V)", "V")


def test_measurement_result_plot_dataframe_and_units():
    from pytestlab.experiments import MeasurementResult
    from pytestlab.plotting import PlotSpec

    df = pl.DataFrame({
        "Time (s)": [0.0, 0.1, 0.2],
        "Voltage (V)": [0.0, 0.5, 1.0],
    })
    res = MeasurementResult(values=df, instrument="sim", units="V", measurement_type="waveform")
    fig = res.plot(PlotSpec(title="MR DF Plot"))
    ax = fig.axes[0]
    # When a single y-series, ylabel should prefer units
    assert ax.get_ylabel() == "V"


def test_session_plot_after_sweep():
    from pytestlab.measurements import MeasurementSession
    from pytestlab.plotting import PlotSpec

    with MeasurementSession("Session Plot Test") as session:
        session.parameter("i", [0, 1, 2])

        @session.acquire
        def acquire(i):
            return {"Time (s)": float(i), "Value": float(i) + 0.5}

        experiment = session.run(show_progress=False)
        assert not experiment.data.is_empty()

        fig = session.plot(PlotSpec(title="Session Data"))
        ax = fig.axes[0]
        assert ax.get_xlabel() == "Time (s)"


