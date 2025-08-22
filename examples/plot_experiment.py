from pytestlab.experiments import Experiment
from pytestlab.plotting import PlotSpec


def main():
    exp = Experiment("Voltage Sweep", "Demo experiment")
    exp.add_trial({"Time (s)": [0, 1, 2, 3], "Voltage (V)": [0.0, 1.1, 2.2, 3.3]})
    exp.add_trial({"Time (s)": [0, 1, 2, 3], "Voltage (V)": [0.0, 1.3, 2.6, 3.9]})

    fig = exp.plot(PlotSpec(title="Experiment Voltage"))
    fig.show()


if __name__ == "__main__":
    main()
