from typing import get_args

from ..config.power_meter_config import PowerMeterConfig
from ..errors import InstrumentDataError
from .instrument import Instrument


class PowerMeter(Instrument[PowerMeterConfig]):
    """Drives a Power Meter instrument for power measurements.

    This class provides a high-level interface for controlling a power meter,
    building upon the base `Instrument` class. It includes methods for
    configuring the power sensor and reading power values.
    """

    def configure_sensor(
        self,
        channel: int = 1,
        freq: float | None = None,
        averaging_count: int | None = None,
        units: str | None = None,
    ) -> None:
        """Configures the settings for a specific power sensor channel.

        This method allows setting the frequency compensation, averaging count,
        and power units for the measurement.

        Args:
            channel: The sensor channel number to configure (default is 1).
            freq: The frequency compensation value in Hz.
            averaging_count: The number of measurements to average.
            units: The desired power units (e.g., "dBm", "W").
        """
        # The specific SCPI commands can vary between power meter models.
        # The following are common examples.

        # Set the frequency compensation for the sensor.
        if freq is not None:
            self._send_command(f"SENS{channel}:FREQ {freq}")
            self.config.frequency_compensation_value = freq  # Update local config state

        # Set the number of readings to average.
        if averaging_count is not None:
            self._send_command(f"SENS{channel}:AVER:COUN {averaging_count}")
            self.config.averaging_count = averaging_count  # Update local config state

        # Set the units for the power measurement.
        if units is not None:
            # Validate against config-declared choices when available; otherwise accept.
            allowed: set[str] = set()
            field = PowerMeterConfig.model_fields.get("power_units")
            ann = getattr(field, "annotation", None)
            if ann is not None:
                try:
                    args = get_args(ann)
                    if args:
                        allowed = {str(x) for x in args}
                except Exception:
                    allowed = set()

            if not allowed or units in allowed:
                self._send_command(f"UNIT:POW {units.upper()}")
                self.config.power_units = units  # type: ignore[assignment]
            else:
                self._logger.warning(
                    f"Invalid power units '{units}' specified. Using config default '{self.config.power_units}'."
                )

        self._logger.info(f"Power meter sensor channel {channel} configured.")

    def read_power(self, channel: int = 1) -> float:
        """Reads the power from a specified sensor channel.

        This method queries the instrument for a power reading.

        Args:
            channel: The sensor channel number to read from (default is 1).

        Returns:
            The measured power as a float. The units depend on the current
            instrument configuration.
        """
        response = self._query(f"FETC{channel}?")
        try:
            return float(response.strip())
        except ValueError as exc:
            raise InstrumentDataError(
                self.config.model,
                f"Could not parse power reading from response {response!r}.",
            ) from exc
