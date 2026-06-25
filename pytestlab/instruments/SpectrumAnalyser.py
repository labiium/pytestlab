from ..config.spectrum_analyzer_config import SpectrumAnalyzerConfig
from ..errors import InstrumentDataError
from .instrument import Instrument
from .operation_contract import OperationDescriptor


class PlaceholderMeasurementResult:
    def __init__(
        self,
        x: list[float],
        y: list[float],
        x_label: str = "Frequency (Hz)",
        y_label: str = "Amplitude (dBm)",
    ):
        self.x = x
        self.y = y
        self.x_label = x_label
        self.y_label = y_label

class SpectrumAnalyser(Instrument[SpectrumAnalyzerConfig]):
    OPERATION_CONTRACT: tuple[OperationDescriptor, ...] = (
        OperationDescriptor(
            "spectrum_measurement_setup",
            required_aliases=("set_center_frequency", "set_span", "set_rbw"),
            parameters={
                "center_frequency": {
                    "bindings": [{"alias": "set_center_frequency", "parameter": "frequency"}]
                },
                "span": {"bindings": [{"alias": "set_span", "parameter": "span"}]},
                "rbw": {"bindings": [{"alias": "set_rbw", "parameter": "bandwidth"}]},
            },
        ),
        OperationDescriptor(
            "trace_readout",
            required_aliases=("trace_data",),
            safety_class="read",
            parameters={"channel": {"bindings": [{"alias": "trace_data", "parameter": "channel"}]}},
        ),
    )

    def configure_measurement(
        self, center_freq: float | None = None, span: float | None = None, rbw: float | None = None
    ) -> None:
        if center_freq is not None:
            self.send_scpi_alias("set_center_frequency", frequency=center_freq)
            self.config.frequency_center = center_freq  # Update config
        if span is not None:
            self.send_scpi_alias("set_span", span=span)
            self.config.frequency_span = span  # Update config
        if rbw is not None:
            self.send_scpi_alias("set_rbw", bandwidth=rbw)
            self.config.resolution_bandwidth = rbw  # Update config
        # Update self.config if these settings are part of it and should reflect runtime changes
        # Or rely on Pydantic models for initial config and these are runtime overrides

    def get_trace(
        self, channel: int = 1
    ) -> PlaceholderMeasurementResult:  # Use actual MeasurementResult later
        raw_data = self.query_scpi_alias("trace_data", channel=channel)
        try:
            amplitudes = [float(part.strip()) for part in raw_data.split(",") if part.strip()]
        except ValueError as exc:
            raise InstrumentDataError(
                self.config.model,
                f"Could not parse spectrum trace response {raw_data!r}.",
            ) from exc

        if not amplitudes:
            raise InstrumentDataError(self.config.model, "Spectrum trace response was empty.")

        center = self.config.frequency_center or 1e9
        span = self.config.frequency_span or 100e6
        if len(amplitudes) == 1:
            frequencies = [center]
        else:
            start = center - span / 2
            step = span / (len(amplitudes) - 1)
            frequencies = [start + i * step for i in range(len(amplitudes))]

        return PlaceholderMeasurementResult(x=frequencies, y=amplitudes)
