# Handling Uncertainty

PyTestLab provides first-class support for measurement uncertainty, enabling you to propagate and quantify errors throughout your data analysis workflow. This is essential for scientific rigor and for meeting compliance requirements in regulated environments.

---

## Why Uncertainty Matters

Every measurement has an associated uncertainty, arising from instrument limitations, environmental factors, and other sources of error. Properly tracking and propagating these uncertainties is crucial for:

- Assessing the reliability of your results
- Comparing measurements from different instruments or labs
- Meeting the requirements of standards such as ISO/IEC 17025

---

## How PyTestLab Handles Uncertainty

PyTestLab integrates with the [`uncertainties`](https://pythonhosted.org/uncertainties/) Python package to represent and propagate measurement errors automatically.

### Instrument Profiles and Accuracy

Instrument profiles in PyTestLab can specify accuracy specifications directly in their YAML configuration, typically as a combination of percentage of reading, percentage of range, and absolute offset. These are parsed and used to compute the standard uncertainty for each measurement.

Example excerpt from a DMM profile:

```yaml
accuracy:
  dc_voltage:
    percentage: 0.025   # ±0.025% of reading
    absolute: 0.0005    # ±0.0005 V
```

---

## Automatic Uncertainty Propagation

When you perform a measurement using a PyTestLab instrument driver, the returned value is a [`UFloat`](https://pythonhosted.org/uncertainties/) object (from the `uncertainties` package) if accuracy data is available. This object contains both the nominal value and its standard deviation.

```python
import pytestlab

# Assume 'dmm' is an initialized instrument with accuracy specs
result = await dmm.measure_voltage_dc()
print(result.values)  # e.g., 5.0012+/-0.0025

# The value is a UFloat, so you can do math and propagate errors:
resistor = 1000.0  # Ohms, assumed exact
current = result.values / resistor
print(f"Current: {current}")  # Uncertainty is propagated automatically
```

---

## Working with UFloat Objects

- **Nominal value:** `result.values.nominal_value`
- **Standard deviation:** `result.values.std_dev`
- **String representation:** `str(result.values)` (e.g., `5.0012+/-0.0025`)
- **Math operations:** All standard math operations propagate uncertainty.

For more, see the [uncertainties documentation](https://pythonhosted.org/uncertainties/).

---

## Custom Uncertainty Models

If your instrument or measurement requires a custom uncertainty model (e.g., temperature dependence, non-Gaussian errors), you can:

- Extend the instrument profile with additional fields
- Post-process the returned `UFloat` objects with your own calculations
- Use the `uncertainties.ufloat` constructor to wrap your own values

---

## Best Practices

- **Always check your instrument profile:** Ensure accuracy specs are present and correct.
- **Use the returned `UFloat` objects:** Don’t discard uncertainty information in your analysis.
- **Propagate uncertainty through all calculations:** This is automatic with `uncertainties`, but be careful when converting to plain floats.
- **Document your uncertainty sources:** For compliance and reproducibility.

---

## Further Reading

- [uncertainties package documentation](https://pythonhosted.org/uncertainties/)
- [PyTestLab Configuration Models](../api/config.md)
- [10-Minute Tour: Uncertainty Example](../tutorials/10_minute_tour.ipynb)

---