from __future__ import annotations

from typing import Any
from typing import Self

from pydantic import validate_call

from ..config import PowerSupplyConfig
from ..errors import InstrumentConfigurationError
from ..errors import InstrumentParameterError
from ..uncertainty import Quantity
from .instrument import Instrument
from .operation_contract import OperationDescriptor
from .scpi_engine import SCPIEngine
from .uncertainty_adapters import nominal_measurement_quantity
from .uncertainty_adapters import nonzero_uncertainty_quantity
from .uncertainty_adapters import psu_measurement_context


class PSUChannelFacade:
    """Provides a simplified, chainable interface for a single PSU channel.

    This facade abstracts the underlying SCPI commands for common channel
    operations, allowing for more readable and fluent test scripts. For example:
    `psu.channel(1).set(voltage=5.0, current_limit=0.1).on()`

    Attributes:
        _psu: The parent `PowerSupply` instance.
        _channel: The channel number (1-based) this facade controls.
    """

    def __init__(self, psu: PowerSupply, channel_num: int):
        self._psu = psu
        self._channel = channel_num

    @validate_call
    def set(self, voltage: float | None = None, current_limit: float | None = None) -> Self:
        """Sets the voltage and/or current limit for this channel.

        Args:
            voltage: The target voltage in Volts.
            current_limit: The current limit in Amperes.

        Returns:
            The `PSUChannelFacade` instance for method chaining.
        """
        self._validate_setpoints(voltage=voltage, current_limit=current_limit)

        if voltage is not None:
            self._psu.set_voltage(self._channel, voltage)
        if current_limit is not None:
            self._psu.set_current(self._channel, current_limit)
        return self

    def _validate_setpoints(
        self, *, voltage: float | None = None, current_limit: float | None = None
    ) -> None:
        """Validate a channel update without writing to the instrument."""
        if voltage is not None:
            self._psu._resolve_operation_arguments(
                "set_voltage", {"channel": self._channel, "voltage": voltage}
            )
            if self._psu._voltage_limit is not None and voltage > self._psu._voltage_limit:
                from ..bench import SafetyLimitError

                raise SafetyLimitError(
                    f"{voltage}V exceeds safety limit {self._psu._voltage_limit}V"
                )
        if current_limit is not None:
            self._psu._resolve_operation_arguments(
                "set_current", {"channel": self._channel, "current": current_limit}
            )
            if self._psu._current_limit is not None and current_limit > self._psu._current_limit:
                from ..bench import SafetyLimitError

                raise SafetyLimitError(
                    f"{current_limit}A exceeds safety limit {self._psu._current_limit}A"
                )

    @validate_call
    def slew(self, duration_s: float | None = None, enabled: bool = True) -> Self:
        """Configures the slew rate (ramp time) for this channel.

        Args:
            duration_s: The time in seconds for the voltage to ramp to its
                        set value. If None, the duration is not changed.
            enabled:    True to enable slew, False to disable.

        Returns:
            The `PSUChannelFacade` instance for method chaining.
        """
        if duration_s is not None:
            self._psu.set_slew_rate(self._channel, duration_s)
        self._psu.enable_slew_rate(self._channel, enabled)
        return self

    @validate_call
    def on(self) -> Self:
        """Enables the output of this channel."""
        self._psu.output(self._channel, True)
        return self

    @validate_call
    def off(self) -> Self:
        """Disables the output of this channel."""
        self._psu.output(self._channel, False)
        return self

    def get_voltage(self) -> Quantity:
        """Read measured channel voltage.

        The result is a PyTestLab :class:`Quantity`; use ``float(result)`` for
        its nominal value or ``result.nominal`` when the explicit property is
        clearer.
        """
        return self._psu.read_voltage(self._channel)

    def get_current(self) -> Quantity:
        """Read measured channel current as a PyTestLab :class:`Quantity`."""
        return self._psu.read_current(self._channel)

    def get_output_state(self) -> bool:
        """Checks if the channel output is enabled (ON).

        Returns:
            True if the output is on, False otherwise.

        Raises:
            InstrumentParameterError: If the instrument returns an unexpected state.
        """
        commands = self._psu._eng().build("get_output_state", channel=self._channel)
        for command in commands[:-1]:
            self._psu._send_command(command)
        state_str = self._psu._eng().parse("get_output_state", self._psu._query(commands[-1]))
        s = str(state_str).strip().upper()
        if s in {"1", "ON", "TRUE"}:
            return True
        if s in {"0", "OFF", "FALSE"}:
            return False
        raise InstrumentParameterError(
            f"Unexpected output state '{state_str}' for channel {self._channel}"
        )


class PSUChannelConfig:
    """A data class to hold the measured configuration of a single PSU channel.

    This class is used to structure the data returned by `get_configuration`,
    providing a snapshot of a channel's state. It is not a Pydantic model for
    loading configurations from files.

    Attributes:
        voltage: The measured voltage of the channel.
        current: The measured current of the channel.
        state: The output state of the channel ("ON" or "OFF").
    """

    def __init__(
        self, voltage: float | Quantity, current: float | Quantity, state: int | str
    ) -> None:
        """Initializes the PSUChannelConfig.

        Args:
            voltage: The voltage value for the channel.
            current: The current value for the channel.
            state: The state of the channel (e.g., 0, 1, "ON", "OFF").
        """
        # Allow native quantities or nominal floats for channel telemetry.
        self.voltage: float | Quantity = voltage
        self.current: float | Quantity = current
        self.state: str  # Store state as string "ON" or "OFF" for consistency
        if isinstance(state, str):
            # Normalize state from various string inputs like "1", "0", "ON", "OFF"
            state_upper = state.upper().strip()
            if state_upper == "ON" or state_upper == "1":
                self.state = "ON"
            elif state_upper == "OFF" or state_upper == "0":
                self.state = "OFF"
            else:
                raise ValueError(f"Invalid string state value: {state}")
        elif isinstance(state, int | float):  # float for query results that might be like 1.0
            self.state = "ON" if int(state) == 1 else "OFF"
        else:
            raise ValueError(f"Invalid state value type: {type(state)}, value: {state}")

    def __repr__(self) -> str:
        return f"PSUChannelConfig(voltage={self.voltage!r}, current={self.current!r}, state='{self.state}')"


class PowerSupply(Instrument[PowerSupplyConfig]):
    """Drives a multi-channel Power Supply Unit (PSU).

    This class provides a high-level interface for controlling a programmable
    power supply. It builds upon the base `Instrument` class and adds methods
    for setting and reading voltage and current on a per-channel basis. It also
    supports incorporating measurement uncertainty if configured.

    A key feature is the `channel()` method, which returns a `PSUChannelFacade`
    for a simplified, chainable programming experience.

    Attributes:
        config: The Pydantic configuration object (`PowerSupplyConfig`)
                containing settings specific to this PSU.
        scpi_engine: The SCPI engine for building and parsing commands.
    """

    model_config = {"arbitrary_types_allowed": True}
    config: PowerSupplyConfig
    _voltage_limit: float | None
    _current_limit: float | None
    _voltage_value: float
    _current_value: float

    OPERATION_CONTRACT: tuple[OperationDescriptor, ...] = (
        OperationDescriptor("identify", public_method="id", safety_class="read"),
        OperationDescriptor("reset", public_method="reset"),
        OperationDescriptor("set_voltage", public_method="set_voltage"),
        OperationDescriptor("set_current", public_method="set_current"),
        OperationDescriptor("set_slew_rate", public_method="set_slew_rate", required=False),
        OperationDescriptor("set_output", public_method="output"),
        OperationDescriptor("set_display", public_method="display", required=False),
        OperationDescriptor("measure_voltage", public_method="read_voltage", safety_class="read"),
        OperationDescriptor("measure_current", public_method="read_current", safety_class="read"),
        OperationDescriptor(
            "get_output_state", public_method="get_output_state", safety_class="read"
        ),
        OperationDescriptor("enable_slew_rate", public_method="enable_slew_rate", required=False),
        OperationDescriptor(
            "get_configuration", public_method="get_configuration", safety_class="read"
        ),
    )

    def __init__(self, config: PowerSupplyConfig, **kwargs: Any):
        super().__init__(config=config, **kwargs)
        # Initialize SCPI engine from the config if available (reusing base if present)
        if getattr(self, "_scpi_engine", None) is None:
            scpi_data = config.scpi.model_dump() if config.scpi else {}
            self._scpi_engine = SCPIEngine(scpi_data, variant=config.scpi_variant)

        # Initialize safety limit properties
        self._voltage_limit = None
        self._current_limit = None
        self._voltage_value = 0.0
        self._current_value = 0.0

    # PowerSupply uses the base Instrument.__init__ method

    def _eng(self) -> SCPIEngine:
        if not self._scpi_engine:
            raise InstrumentConfigurationError(
                self.config.model, "No SCPI mapping configured for this PSU."
            )
        return self._scpi_engine

    @validate_call
    def set_voltage(self, channel: int, voltage: float) -> None:
        """Sets the output voltage for a specific channel.

        Args:
            channel: The channel number (1-based).
            voltage: The target voltage in Volts.

        Raises:
            InstrumentParameterError: If the channel number is invalid or the
                                      voltage is outside the configured range for
                                      that channel.
        """
        resolved = self._resolve_operation_arguments(
            "set_voltage", {"channel": channel, "voltage": voltage}
        ).get("set_voltage", {})
        channel = int(resolved.get("channel", channel))
        voltage = float(resolved.get("voltage", voltage))

        # Enforce safety limit, if any
        from ..bench import SafetyLimitError

        if self._voltage_limit is not None and voltage > self._voltage_limit:
            raise SafetyLimitError(f"{voltage}V exceeds safety limit {self._voltage_limit}V")

        # Build and send the SCPI command using the resolver's private values.
        for cmd in self._eng().build("set_voltage", channel=channel, voltage=voltage):
            self._send_command(cmd)
        # Cache recent set value for safety checks
        if channel == 1:
            self._voltage_value = voltage

    @validate_call
    def set_current(self, channel: int, current: float) -> None:
        """Sets the current limit for a specific channel.

        Args:
            channel: The channel number (1-based).
            current: The current limit in Amperes.

        Raises:
            InstrumentParameterError: If the channel number is invalid or the
                                      current is outside the configured range for
                                      that channel.
        """
        resolved = self._resolve_operation_arguments(
            "set_current", {"channel": channel, "current": current}
        ).get("set_current", {})
        channel = int(resolved.get("channel", channel))
        current = float(resolved.get("current", current))

        from ..bench import SafetyLimitError

        if self._current_limit is not None and current > self._current_limit:
            raise SafetyLimitError(f"{current}A exceeds safety limit {self._current_limit}A")

        for cmd in self._eng().build("set_current", channel=channel, current=current):
            self._send_command(cmd)
        if channel == 1:
            self._current_value = current

    @validate_call
    def set_slew_rate(self, channel: int, duration_s: float) -> None:
        """Sets the slew rate (ramp duration) for a specific channel.

        Args:
            channel: The channel number (1-based).
            duration_s: The time in seconds for the voltage to ramp to the set value.
        """
        resolved = self._resolve_operation_arguments(
            "set_slew_rate", {"channel": channel, "duration_s": duration_s}
        ).get("set_slew_rate", {})
        channel = int(resolved.get("channel", channel))
        duration_s = float(resolved.get("duration_ms", duration_s))
        duration_ms = int(duration_s * 1000)
        for cmd in self._eng().build("set_slew_rate", channel=channel, duration_ms=duration_ms):
            self._send_command(cmd)

    @validate_call
    def enable_slew_rate(self, channel: int, state: bool) -> None:
        """Enables or disables the slew rate feature for a specific channel.

        Args:
            channel: The channel number (1-based).
            state: True to enable slew, False to disable.
        """
        if not self.config.channels or not (1 <= channel <= len(self.config.channels)):
            num_ch = len(self.config.channels) if self.config.channels else 0
            raise InstrumentParameterError(
                f"Channel number {channel} is out of range (1-{num_ch})."
            )

        resolved_channel = self._resolve_operation_parameter("enable_slew_rate", "channel", channel)
        resolved_state = self._resolve_operation_parameter("enable_slew_rate", "state", state)
        operation = self.config.operation_options.operation("enable_slew_rate")
        logical = "enable" if bool(resolved_state.value) else "disable"
        command_name = operation.transport.get(logical) if operation else None
        if command_name is None:
            raise InstrumentConfigurationError(
                self.config.model, "Profile does not implement slew-rate state control."
            )
        self._send_profile_alias(command_name, channel=resolved_channel.transport_value)

    @validate_call
    def output(self, channel: int | list[int], state: bool = True) -> None:
        """Enables or disables the output for one or more channels.

        Args:
            channel: A single channel number (1-based) or a list of channel numbers.
            state: True to enable the output (ON), False to disable (OFF).

        Raises:
            InstrumentParameterError: If any channel number is invalid.
            ValueError: If the `channel` argument is not an int or a list of ints.
        """
        channels_to_process: list[int]
        if isinstance(channel, int):
            channels_to_process = [channel]
        elif isinstance(channel, list):
            # Ensure all elements in the list are integers
            if not all(isinstance(ch, int) for ch in channel):
                raise ValueError("All elements in channel list must be integers.")
            channels_to_process = channel
        else:
            # This case should ideally be caught by validate_call if type hints are precise enough,
            # but an explicit check remains good practice.
            raise ValueError(f"Invalid channel type: {type(channel)}. Expected int or List[int].")

        num_configured_channels = len(self.config.channels) if self.config.channels else 0
        for ch_num in channels_to_process:
            if not (1 <= ch_num <= num_configured_channels):
                raise InstrumentParameterError(
                    f"Channel number {ch_num} is out of range (1-{num_configured_channels})."
                )

        # Resolve all channels and the state before sending any command.
        resolved_state = self._resolve_operation_parameter("set_output", "state", state)
        resolved_channels = [
            int(self._resolve_operation_parameter("set_output", "channel", ch).value)
            for ch in channels_to_process
        ]
        for ch_num in resolved_channels:
            for cmd in self._eng().build(
                "set_output", channel=ch_num, state=resolved_state.transport_value
            ):
                self._send_command(cmd)

    @validate_call
    def display(self, state: bool) -> None:
        """Enables or disables the instrument's front panel display.

        Args:
            state: True to turn the display on, False to turn it off.
        """
        resolved = self._resolve_operation_parameter("set_display", "state", state)
        cmd = self._eng().build("set_display", state=resolved.transport_value)[0]
        self._send_command(cmd)

    @validate_call
    def get_output_state(self, channel: int) -> bool:
        """Read whether a power-supply channel output is enabled."""
        channel = int(
            self._resolve_operation_parameter("get_output_state", "channel", channel).value
        )
        commands = self._eng().build("get_output_state", channel=channel)
        for command in commands[:-1]:
            self._send_command(command)
        state = (
            str(self._eng().parse("get_output_state", self._query(commands[-1]))).strip().upper()
        )
        if state in {"1", "ON", "TRUE"}:
            return True
        if state in {"0", "OFF", "FALSE"}:
            return False
        raise InstrumentParameterError(
            parameter="state", value=state, message="Unexpected output state response."
        )

    @validate_call
    def read_voltage(self, channel: int) -> Quantity:
        """Reads the measured output voltage from a specific channel.

        Args:
            channel: The channel number to measure (1-based).

        Returns:
            The measured voltage as an uncertainty-aware quantity.

        Raises:
            InstrumentParameterError: If the channel number is invalid.
        """
        channel = int(
            self._resolve_operation_parameter("measure_voltage", "channel", channel).value
        )
        commands = self._eng().build("measure_voltage", channel=channel)
        for command in commands[:-1]:
            self._send_command(command)
        reading = float(self._eng().parse("measure_voltage", self._query(commands[-1])))

        value_to_return: Any = nominal_measurement_quantity(
            reading,
            "V",
            function="read_voltage",
            output_name=f"read_voltage_ch{channel}",
            reason=(
                f"{self.config.model} read_voltage channel {channel}: no applied uncertainty "
                "metadata yet; result is nominal-only and non-report-grade."
            ),
        )

        if self.config.measurement_accuracy:
            mode_key = f"read_voltage_ch{channel}"
            self._logger.debug(
                f"Attempting to find accuracy spec for read_voltage on channel {channel} with key: '{mode_key}'"
            )
            spec = self.config.measurement_accuracy.get(mode_key)

            if spec:
                context = psu_measurement_context(
                    self.config,
                    channel=channel,
                    reading=reading,
                    unit="V",
                    function="read_voltage",
                    instrument_key=self._uncertainty_source_key(),
                )
                quantity = nonzero_uncertainty_quantity(
                    spec,
                    context,
                    logger=self._logger,
                    label=f"accuracy spec '{mode_key}'",
                    strict=self.config.uncertainty_strict,
                )
                if quantity is not None:
                    value_to_return = quantity
            else:
                value_to_return = nominal_measurement_quantity(
                    reading,
                    "V",
                    function="read_voltage",
                    output_name=f"read_voltage_ch{channel}",
                    reason=(
                        f"{self.config.model} read_voltage channel {channel}: missing "
                        f"measurement_accuracy key {mode_key!r}; add an accuracy spec."
                    ),
                )
                self._logger.debug(
                    "No accuracy spec found for read_voltage on channel %s with key %r; "
                    "returning nominal-only non-report-grade Quantity.",
                    channel,
                    mode_key,
                )
        else:
            self._logger.debug(
                "No measurement_accuracy configuration in instrument for read_voltage on channel "
                "%s; returning nominal-only non-report-grade Quantity.",
                channel,
            )

        return value_to_return

    @validate_call
    def read_current(self, channel: int) -> Quantity:
        """Reads the measured output current from a specific channel.

        Args:
            channel: The channel number to measure (1-based).

        Returns:
            The measured current as an uncertainty-aware quantity.

        Raises:
            InstrumentParameterError: If the channel number is invalid.
        """
        channel = int(
            self._resolve_operation_parameter("measure_current", "channel", channel).value
        )
        commands = self._eng().build("measure_current", channel=channel)
        for command in commands[:-1]:
            self._send_command(command)
        reading = float(self._eng().parse("measure_current", self._query(commands[-1])))

        value_to_return: Any = nominal_measurement_quantity(
            reading,
            "A",
            function="read_current",
            output_name=f"read_current_ch{channel}",
            reason=(
                f"{self.config.model} read_current channel {channel}: no applied uncertainty "
                "metadata yet; result is nominal-only and non-report-grade."
            ),
        )

        if self.config.measurement_accuracy:
            mode_key = f"read_current_ch{channel}"
            self._logger.debug(
                f"Attempting to find accuracy spec for read_current on channel {channel} with key: '{mode_key}'"
            )
            spec = self.config.measurement_accuracy.get(mode_key)

            if spec:
                context = psu_measurement_context(
                    self.config,
                    channel=channel,
                    reading=reading,
                    unit="A",
                    function="read_current",
                    instrument_key=self._uncertainty_source_key(),
                )
                quantity = nonzero_uncertainty_quantity(
                    spec,
                    context,
                    logger=self._logger,
                    label=f"accuracy spec '{mode_key}'",
                    strict=self.config.uncertainty_strict,
                )
                if quantity is not None:
                    value_to_return = quantity
            else:
                value_to_return = nominal_measurement_quantity(
                    reading,
                    "A",
                    function="read_current",
                    output_name=f"read_current_ch{channel}",
                    reason=(
                        f"{self.config.model} read_current channel {channel}: missing "
                        f"measurement_accuracy key {mode_key!r}; add an accuracy spec."
                    ),
                )
                self._logger.debug(
                    "No accuracy spec found for read_current on channel %s with key %r; "
                    "returning nominal-only non-report-grade Quantity.",
                    channel,
                    mode_key,
                )
        else:
            self._logger.debug(
                "No measurement_accuracy configuration in instrument for read_current on channel "
                "%s; returning nominal-only non-report-grade Quantity.",
                channel,
            )

        return value_to_return

    @validate_call
    def get_configuration(self) -> dict[int, PSUChannelConfig]:
        """Reads the live state of all configured PSU channels.

        This method iterates through all channels defined in the configuration,
        queries their current voltage, current, and output state, and returns
        the collected data.

        Returns:
            A dictionary where keys are channel numbers (1-based) and values are
            `PSUChannelConfig` objects representing the state of each channel.
        """
        results: dict[int, PSUChannelConfig] = {}
        if not self.config.channels:
            self._logger.warning(
                "No channels defined in the PowerSupplyConfig. Cannot get configuration."
            )
            return results

        num_channels = len(self.config.channels)

        for channel_num in range(1, num_channels + 1):  # Iterate 1-indexed channel numbers

            def _nominal(x: Any) -> float:
                return x.nominal if isinstance(x, Quantity) else float(x)

            voltage_val = _nominal(self.read_voltage(channel_num))
            current_val = _nominal(self.read_current(channel_num))
            # Query output state using SCPI engine
            commands = self._eng().build("get_output_state", channel=channel_num)
            for command in commands[:-1]:
                self._send_command(command)
            state_str: str = self._eng().parse("get_output_state", self._query(commands[-1]))

            results[channel_num] = PSUChannelConfig(
                voltage=voltage_val, current=current_val, state=state_str.strip()
            )
        return results

    @validate_call
    def channel(self, ch_num: int) -> PSUChannelFacade:
        """
        Returns a facade for interacting with a specific channel.

        Args:
            ch_num (int): The channel number (1-based).

        Returns:
            PSUChannelFacade: A facade object for the specified channel.

        Raises:
            InstrumentParameterError: If channel number is invalid.
        """
        if not self.config.channels or not (1 <= ch_num <= len(self.config.channels)):
            num_ch = len(self.config.channels) if self.config.channels else 0
            raise InstrumentParameterError(f"Channel number {ch_num} is out of range (1-{num_ch}).")
        return PSUChannelFacade(self, ch_num)

    @validate_call
    def id(self) -> str:
        """
        Queries the instrument identification string.

        Returns:
            str: The instrument identification string.
        """
        cmd = self._eng().build("identify")[0]
        return self._eng().parse("identify", self._query(cmd))

    @validate_call
    def reset(self) -> None:
        """
        Resets the instrument to its factory default settings.
        """
        cmd = self._eng().build("reset")[0]
        self._send_command(cmd)

    @property
    def voltage_limit(self) -> float | None:
        """Get the current voltage safety limit."""
        return self._voltage_limit

    @voltage_limit.setter
    def voltage_limit(self, value: float) -> None:
        """Set the voltage safety limit."""
        from ..bench import SafetyLimitError

        if value < 0:
            raise SafetyLimitError(f"Voltage limit cannot be negative: {value}V")

        # Check against current voltage setting
        if hasattr(self, "_voltage_value") and self._voltage_value > value:
            raise SafetyLimitError(
                f"Cannot set voltage limit {value}V below current voltage setting {self._voltage_value}V"
            )

        self._voltage_limit = value

    @property
    def current_limit(self) -> float | None:
        """Get the current safety limit."""
        return self._current_limit

    @current_limit.setter
    def current_limit(self, value: float) -> None:
        """Set the current safety limit."""
        from ..bench import SafetyLimitError

        if value < 0:
            raise SafetyLimitError(f"Current limit cannot be negative: {value}A")

        # Check against current setting
        if hasattr(self, "_current_value") and self._current_value > value:
            raise SafetyLimitError(
                f"Cannot set current limit {value}A below current setting {self._current_value}A"
            )

        self._current_limit = value

    @property
    def voltage(self) -> float:
        """Get the current voltage value."""
        return self._voltage_value

    @voltage.setter
    def voltage(self, value: float) -> None:
        """Set the voltage value with safety checking."""
        from ..bench import SafetyLimitError

        if self._voltage_limit is not None and value > self._voltage_limit:
            raise SafetyLimitError(
                f"Refusing to set voltage {value}V, which is above the safety limit of {self._voltage_limit}V."
            )

        self._voltage_value = value
        # In a real implementation, this would call set_voltage for channel 1
        # For safety testing, we just store the value

    @property
    def current(self) -> float:
        """Get the current value."""
        return self._current_value

    @current.setter
    def current(self, value: float) -> None:
        """Set the current value with safety checking."""
        from ..bench import SafetyLimitError

        if self._current_limit is not None and value > self._current_limit:
            raise SafetyLimitError(
                f"Refusing to set current {value}A, which is above the safety limit of {self._current_limit}A."
            )

        self._current_value = value
        # In a real implementation, this would call set_current for channel 1
        # For safety testing, we just store the value
