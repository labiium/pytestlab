from pytestlab import AutoInstrument


def main():
    scope = AutoInstrument.from_config("keysight/DSOX1204G")
    scope.connect_backend()

    res = scope.reset()

    # Read a single channel; returns MeasurementResult with a Polars DataFrame in .values
    res = scope.read_channels(1, 2)
    print(len(res))
    res.plot().savefig("plot_dsx1204g_channel.png")

    scope.close()


if __name__ == "__main__":
    main()
