import pytest


matplotlib = pytest.importorskip("matplotlib")
matplotlib.use("Agg", force=True)


def test_channel_reading_result_split_and_plot(monkeypatch):
    import numpy as np
    import polars as pl
    from pytestlab.instruments.Oscilloscope import ChannelReadingResult
    from pytestlab.plotting import PlotSpec

    # Build a fake two-channel DataFrame
    t = np.linspace(0, 0.01, 1000)
    df = pl.DataFrame({
        "Time (s)": t,
        "Channel 1 (V)": np.sin(2 * np.pi * 1000 * t),
        "Channel 2 (V)": np.cos(2 * np.pi * 1000 * t),
    })

    res = ChannelReadingResult(
        values=df,
        instrument="sim_scope",
        units="V",
        measurement_type="ChannelVoltageTime",
        sampling_rate=100_000.0,
    )

    # Indexing and helpers
    assert res.channels == [1, 2]
    assert res.time.shape[0] == 1000

    ch1 = res[1]
    assert isinstance(ch1, ChannelReadingResult)
    assert ch1.values.columns == ["Time (s)", "Channel 1 (V)"]

    # Plot both and single channel
    fig_all = res.plot(PlotSpec(title="Both"))
    assert hasattr(fig_all, "savefig")
    fig_ch1 = ch1.plot(PlotSpec(title="CH1"))
    assert hasattr(fig_ch1, "savefig")


