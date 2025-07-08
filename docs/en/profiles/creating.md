# Creating Profiles

Instrument profiles are YAML files that define an instrument's capabilities and map them to SCPI commands. PyTestLab uses these profiles along with Pydantic models to provide a structured and validated way to control instruments.

## Profile Structure

A profile YAML file has two main sections:

1.  **Metadata:** Fields like `manufacturer`, `model`, and `device_type`. The `device_type` is crucial as it links the YAML file to a specific Pydantic configuration model (e.g., `PowerSupplyConfig`).
2.  **Configuration Data:** Structured data that matches the fields in the corresponding Pydantic model. This includes channel definitions, supported modes, value ranges, and accuracy specifications.

### Example: Power Supply Profile

This example shows a simplified profile for a power supply.

```yaml title="my_psu_profile.yaml"
# Metadata
manufacturer: MyBrand
model: PSU-101
device_type: power_supply

# Configuration Data (matches PowerSupplyConfig model)
total_power: 100

channels:
  - channel_id: 1
    description: "Main Output"
    voltage_range:
      min_val: 0.0
      max_val: 30.0
    current_limit_range:
      min_val: 0.0
      max_val: 3.0
```

## Creating a New Profile

1.  **Create a YAML file:** Start a new `.yaml` file for your instrument.
2.  **Add Metadata:** Fill in the `manufacturer`, `model`, and `device_type`. The `device_type` must match one of the defined Pydantic config models in `pytestlab.config`.
3.  **Add Configuration Data:** Refer to the corresponding Pydantic model in the [Configuration API Reference](../api/config.md) and fill in the fields with the specifications from your instrument's datasheet.
4.  **Save the Profile:** Save the file in a known location. You can then load it directly by its path in `AutoInstrument.from_config()` or place it in `pytestlab/profiles/<vendor>/` to load it by key.
5.  **Validate:** Use the CLI to validate your new profile: `pytestlab profile validate path/to/your/profile.yaml`.

For more complex instruments, you may need to define nested structures for triggers, channels, FFT, etc., as seen in the built-in profiles.

## Tips

- **Use the built-in profiles as templates:** Browse the [Profile Gallery](gallery.md) to see real examples.
- **Match the schema:** The YAML structure must match the Pydantic model for your `device_type`. See the [Configuration API Reference](../api/config.md) for details.
- **Simulation logic:** You can add a `simulation` section to provide deterministic responses for testing (see the Simulation Guide).
- **Validation:** Always validate your profile before use to catch schema errors early.

---

For further details, see the [API Reference](../api/config.md) and the [Simulation Guide](../user_guide/simulation.md).