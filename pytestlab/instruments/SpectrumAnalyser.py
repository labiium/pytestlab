from ..config.spectrum_analyzer_config import SpectrumAnalyzerConfig
from ..errors import InstrumentDataError
from .instrument import Instrument

# from ..experiments.results import MeasurementResult # If this is the return type for traces
# from .scpi_maps import CommonSCPI, SystemSCPI # And a specific SA SCPI map


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


# SCPI map for a generic SA (can be expanded in scpi_maps.py)
# class GenericSASCPIMap(CommonSCPI, SystemSCPI):
#    FREQ_CENTER = "FREQ:CENT"
#    FREQ_SPAN = "FREQ:SPAN"
#    BAND_RES = "BAND" # RBW
#    TRACE_DATA_QUERY = "TRAC:DATA? TRACE1" # Example


class SpectrumAnalyser(Instrument[SpectrumAnalyzerConfig]):
    # SCPI_MAP = GenericSASCPIMap() # Assign if defined

    def configure_measurement(
        self, center_freq: float | None = None, span: float | None = None, rbw: float | None = None
    ) -> None:
        if center_freq is not None:
            self._send_command(f"FREQ:CENT {center_freq}")  # Use SCPI_MAP later
            self.config.frequency_center = center_freq  # Update config
        if span is not None:
            self._send_command(f"FREQ:SPAN {span}")
            self.config.frequency_span = span  # Update config
        if rbw is not None:
            self._send_command(f"BAND {rbw}")  # RBW command
            self.config.resolution_bandwidth = rbw  # Update config
        # Update self.config if these settings are part of it and should reflect runtime changes
        # Or rely on Pydantic models for initial config and these are runtime overrides

    def get_trace(
        self, channel: int = 1
    ) -> PlaceholderMeasurementResult:  # Use actual MeasurementResult later
        raw_data = self._query(f"TRAC:DATA? TRACE{channel}")
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
