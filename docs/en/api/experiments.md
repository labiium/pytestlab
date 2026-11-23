# Experiments and results

Native captures can be stored and read without unpacking trial columns:

```python
experiment.add_trial(sweep)
saved = experiment.measurements["result"][0]
print(saved.values)
```

For a named capture, use `experiment.measurements["spectrum_trace"][0]`.
This also works after `database.retrieve_experiment(codename)`.

Passing an existing table-valued `MeasurementResult` directly still adds only
its values. Use a [session](../user_guide/measurement_session.md#store-a-waveform-or-sweep-with-each-trial)
to retain that envelope.

---

::: pytestlab.experiments.results.MeasurementResult

::: pytestlab.experiments.experiments.ExperimentParameter

::: pytestlab.experiments.experiments.Experiment
