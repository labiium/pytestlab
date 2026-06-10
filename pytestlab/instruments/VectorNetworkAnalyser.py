from ..config.vna_config import VNAConfig
from ..errors import InstrumentDataError
from .instrument import Instrument


class SParameterData:
    def __init__(
        self, frequencies: list[float], s_params: list[list[complex]], param_names: list[str]
    ):
        self.frequencies = frequencies  # List of frequencies
        self.s_params = s_params  # List of lists, each inner list contains complex S-param values for a given S-parameter type
        self.param_names = param_names  # List of S-parameter names, e.g., ["S11", "S21"]


class VectorNetworkAnalyser(Instrument[VNAConfig]):
    model_config = {"arbitrary_types_allowed": True}

    def configure_s_parameter_sweep(
        self,
        s_params: list[str] | None = None,  # e.g. ["S11", "S21"]
        start_freq: float | None = None,
        stop_freq: float | None = None,
        num_points: int | None = None,
        if_bandwidth: float | None = None,
        power_level: float | None = None,
    ) -> None:
        if s_params is not None:
            # SCPI command to select S-parameters might be like: CALC:PAR:DEF "S11"
            # This is highly instrument specific. For now, just update config.
            self.config.s_parameters = s_params
            self._logger.info(f"VNA S-parameters set to: {s_params}")
        if start_freq is not None:
            self._send_command(f"SENS:FREQ:STAR {start_freq}")  # Example SCPI
            self.config.start_frequency = start_freq
        if stop_freq is not None:
            self._send_command(f"SENS:FREQ:STOP {stop_freq}")  # Example SCPI
            self.config.stop_frequency = stop_freq
        if num_points is not None:
            self._send_command(f"SENS:SWE:POIN {num_points}")  # Example SCPI
            self.config.num_points = num_points
        if if_bandwidth is not None:
            self._send_command(f"SENS:BWID {if_bandwidth}")  # Example SCPI for IF bandwidth
            self.config.if_bandwidth = if_bandwidth
        if power_level is not None:
            self._send_command(f"SOUR:POW {power_level}")  # Example SCPI for power
            self.config.power_level = power_level
        self._logger.info("VNA measurement configured (simulated).")

    def get_s_parameter_data(self) -> SParameterData:
        num_points = self.config.num_points or 101
        start_f = self.config.start_frequency or 1e9
        stop_f = self.config.stop_frequency or 2e9
        frequencies = [
            start_f + i * (stop_f - start_f) / (num_points - 1 if num_points > 1 else 1)
            for i in range(num_points)
        ]
        s_params_to_measure = self.config.s_parameters or ["S11"]

        raw_data = self._query("CALC:DATA? SDAT")
        try:
            values = [float(part.strip()) for part in raw_data.split(",") if part.strip()]
        except ValueError as exc:
            raise InstrumentDataError(
                self.config.model,
                f"Could not parse S-parameter response {raw_data!r}.",
            ) from exc

        expected_values = len(s_params_to_measure) * num_points * 2
        if len(values) != expected_values:
            raise InstrumentDataError(
                self.config.model,
                f"Expected {expected_values} S-parameter values, got {len(values)}.",
            )

        s_params_data: list[list[complex]] = []
        cursor = 0
        for _ in s_params_to_measure:
            param_data = []
            for _point_index in range(num_points):
                real_part = values[cursor]
                imag_part = values[cursor + 1]
                cursor += 2
                param_data.append(complex(real_part, imag_part))
            s_params_data.append(param_data)

        return SParameterData(
            frequencies=frequencies, s_params=s_params_data, param_names=s_params_to_measure
        )
