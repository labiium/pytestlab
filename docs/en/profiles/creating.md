# Creating Profiles

Instrument profiles are YAML files that define an instrument's capabilities and map them to SCPI commands. PyTestLab uses these profiles along with Pydantic models to provide a structured and validated way to control instruments.

## Profile Structure

A profile YAML file has two main sections:

1.  **Metadata:** Fields like `manufacturer`, `model`, `device_type`, and `role`. The `device_type` is crucial as it links the YAML file to a specific Pydantic configuration model (e.g., `PowerSupplyConfig`).
2.  **Configuration Data:** Structured data that matches the fields in the corresponding Pydantic model. This includes channel definitions, supported modes, value ranges, and accuracy specifications.

### Example: Power Supply Profile

This schema-valid example describes a power supply's limits. It does not include
SCPI mappings or simulator responses, so it cannot operate a supply or produce
measurements as written.

```yaml title="my_psu_profile.yaml"
# Metadata
manufacturer: example
model: PSU-101
device_type: power_supply
role: stimulus

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
2.  **Add Metadata:** Fill in the `manufacturer`, `model`, `device_type`, and `role`. The `device_type` must match one of the defined Pydantic config models in `pytestlab.config`.
3.  **Add Configuration Data:** Refer to the corresponding Pydantic model in the [Configuration API Reference](../api/config.md) and fill in the fields with the specifications from your instrument's datasheet.
4.  **Save the Profile:** Save the file in a known location. Load a custom file with `AutoInstrument.from_file()`. Use `AutoInstrument.from_preset()` for a key shipped with PyTestLab.
5.  **Validate:** Use the CLI to validate your new profile: `ptl profile validate path/to/your/profile.yaml`.

For more complex instruments, you may need to define nested structures for triggers, channels, FFT, etc., as seen in the built-in profiles.

### Semantic operation options

Use `operation_options` for profile-specific semantic values that are not
adequately described by a low-level SCPI enum. The option `value` is the public
selection; `transport.value` is private and is used only when building the
profile command:

```yaml
operation_options:
  set_output:
    state:
      kind: bool
      options:
        - value: true
          label: Enabled
          aliases: ["on"]
          transport: {value: "ON"}
        - value: false
          label: Disabled
          aliases: ["off"]
          transport: {value: "OFF"}
```

Declare dependencies on other parameters and provide a finite option list or
explicit numeric `min`/`max` range. Do not use missing metadata to imply an
unrestricted input. The same semantic values are returned by Python operation
discovery and the offline CLI.

For a large profile, an operation may set an optional `group` (for example,
`trigger` or `trace`), `description`, and `references` beside its `parameters`
and `transport`. References should name actual sources such as a manual
section or a test artifact. They do not affect execution or imply hardware
verification. The group overrides the driver's group for this profile only.

## Tips

- **Use the built-in profiles as templates:** Browse the [Profile Gallery](gallery.md) to see real examples.
- **Match the schema:** The YAML structure must match the Pydantic model for your `device_type`. See the [Configuration API Reference](../api/config.md) for details.
- **Simulation logic:** You can add a `simulation` section to provide deterministic responses for testing (see the Simulation Guide).
- **Validation:** Always validate your profile before use to catch schema errors early.

---

For further details, see the [API Reference](../api/config.md) and the [Simulation Guide](../user_guide/simulation.md).
