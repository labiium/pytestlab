from pytestlab.experiments import MeasurementResult, Experiment

# Assuming both Experiment and MeasurementResult classes are defined as described above

# Create an experiment
experiment = Experiment("Signal Analysis", "Analysis of electrical signals over time.")

# Add parameters for the experiment
experiment.add_parameter("channel_1", "volts", "Voltage readings from Channel 1")
experiment.add_parameter("sampling_rate", "Hz", "Sampling rate of the signal")

# Create a MeasurementResult for a trial
values = [(0.1, 1.2), (0.2, 1.4), (0.3, 1.1)]  # Example (dimension, value) pairs
measurement_result = MeasurementResult(values, "Oscilloscope", "volts", "VoltageTime", sampling_rate=1000)

# Add a trial to the experiment
experiment.add_trial(measurement_result, channel_1="1.5V", sampling_rate="1000Hz")

# Print out the experiment details and trial data
print(experiment)
print(experiment.trials)