from ..config.vna_config import VNAConfig
from ..errors import InstrumentDataError
from .instrument import Instrument
from .operation_contract import OperationDescriptor


class SParameterData:
    def __init__(
        self, frequencies: list[float], s_params: list[list[complex]], param_names: list[str]
    ):
        self.frequencies = frequencies  # List of frequencies
        self.s_params = s_params  # List of lists, each inner list contains complex S-param values for a given S-parameter type
        self.param_names = param_names  # List of S-parameter names, e.g., ["S11", "S21"]


class VectorNetworkAnalyser(Instrument[VNAConfig]):
    model_config = {"arbitrary_types_allowed": True}

    OPERATION_CONTRACT: tuple[OperationDescriptor, ...] = (
        OperationDescriptor(
            "sparameter_sweep_setup",
            required_aliases=(
                "set_start_frequency",
                "set_stop_frequency",
                "set_points",
                "set_if_bandwidth",
                "set_power_level",
            ),
            optional_aliases=("define_sparameter",),
            parameters={
                "s_parameter": {
                    "bindings": [{"alias": "define_sparameter", "parameter": "s_parameter"}]
                },
                "start_frequency": {
                    "bindings": [{"alias": "set_start_frequency", "parameter": "frequency"}]
                },
                "stop_frequency": {
                    "bindings": [{"alias": "set_stop_frequency", "parameter": "frequency"}]
                },
                "num_points": {"bindings": [{"alias": "set_points", "parameter": "points"}]},
                "if_bandwidth": {
                    "bindings": [{"alias": "set_if_bandwidth", "parameter": "bandwidth"}]
                },
                "power_level": {"bindings": [{"alias": "set_power_level", "parameter": "power"}]},
            },
        ),
        OperationDescriptor(
            "sparameter_data",
            required_aliases=("sparameter_data",),
            safety_class="read",
        ),
    )

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
            for index, s_parameter in enumerate(s_params, start=1):
                self.send_scpi_alias("define_sparameter", index=index, s_parameter=s_parameter)
            self.config.s_parameters = s_params
            self._logger.info(f"VNA S-parameters set to: {s_params}")
        if start_freq is not None:
            self.send_scpi_alias("set_start_frequency", frequency=start_freq)
            self.config.start_frequency = start_freq
        if stop_freq is not None:
            self.send_scpi_alias("set_stop_frequency", frequency=stop_freq)
            self.config.stop_frequency = stop_freq
        if num_points is not None:
            self.send_scpi_alias("set_points", points=num_points)
            self.config.num_points = num_points
        if if_bandwidth is not None:
            self.send_scpi_alias("set_if_bandwidth", bandwidth=if_bandwidth)
            self.config.if_bandwidth = if_bandwidth
        if power_level is not None:
            self.send_scpi_alias("set_power_level", power=power_level)
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

        raw_data = self.query_scpi_alias("sparameter_data")
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
