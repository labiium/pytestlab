from __future__ import annotations

from typing import cast

import pytest

from pytestlab.config.dc_active_load_config import DCActiveLoadConfig
from pytestlab.config.dc_active_load_config import OperatingModesSpec
from pytestlab.config.device_config import DeviceRole
from pytestlab.config.instrument_config import SCPICommandSpec
from pytestlab.config.instrument_config import SCPISection
from pytestlab.config.power_meter_config import PowerMeterConfig
from pytestlab.config.spectrum_analyzer_config import SpectrumAnalyzerConfig
from pytestlab.config.vna_config import VNAConfig
from pytestlab.errors import InstrumentCommunicationError
from pytestlab.errors import InstrumentConfigurationError
from pytestlab.instruments.AutoInstrument import AutoInstrument
from pytestlab.instruments.DCActiveLoad import DCActiveLoad
from pytestlab.instruments.PowerMeter import PowerMeter
from pytestlab.instruments.SpectrumAnalyser import SpectrumAnalyser
from pytestlab.instruments.VectorNetworkAnalyser import VectorNetworkAnalyser
from pytestlab.instruments.WaveformGenerator import WaveformGenerator


class NoopBackend:
    def connect(self) -> None:
        return None

    def disconnect(self) -> None:
        return None

    def write(self, cmd: str) -> None:
        return None

    def query(self, cmd: str, delay: float | None = None) -> str:
        return '0,"No error"'

    def query_raw(self, cmd: str, delay: float | None = None) -> bytes:
        return b""

    def close(self) -> None:
        return None

    def set_timeout(self, timeout_ms: int) -> None:
        return None

    def get_timeout(self) -> int:
        return 5000


def _base_config_kwargs(device_type: str):
    return {
        "manufacturer": "PyTestLab",
        "model": "Test",
        "device_type": device_type,
        "role": DeviceRole.MEASUREMENT,
    }


def test_power_meter_read_power_parses_backend_response(monkeypatch):
    meter = PowerMeter(
        PowerMeterConfig(
            **_base_config_kwargs("power_meter"),
            scpi=SCPISection(queries={"fetch_power": SCPICommandSpec(template="READ{channel}?")}),
        ),
        NoopBackend(),
    )
    queries: list[str] = []

    def query(command: str) -> str:
        queries.append(command)
        return "-12.5"

    monkeypatch.setattr(meter, "_query", query)

    assert meter.read_power(channel=2) == pytest.approx(-12.5)
    assert queries == ["READ2?"]


def test_power_meter_read_power_requires_profile_alias():
    meter = PowerMeter(
        PowerMeterConfig(**_base_config_kwargs("power_meter")),
        NoopBackend(),
    )

    with pytest.raises(InstrumentConfigurationError, match="fetch_power"):
        meter.read_power(channel=2)


def test_power_meter_read_power_runs_profile_query_sequence(monkeypatch):
    meter = PowerMeter(
        PowerMeterConfig(
            **_base_config_kwargs("power_meter"),
            scpi=SCPISection(
                queries={"fetch_power": SCPICommandSpec(sequence=["CONF:CHAN {channel}", "READ?"])},
            ),
        ),
        NoopBackend(),
    )
    events: list[tuple[str, str]] = []

    def send(command: str) -> None:
        events.append(("write", command))

    def query(command: str) -> str:
        events.append(("query", command))
        return "-12.5"

    monkeypatch.setattr(meter, "_send_command", send)
    monkeypatch.setattr(meter, "_query", query)

    assert meter.read_power(channel=2) == pytest.approx(-12.5)
    assert events == [("write", "CONF:CHAN 2"), ("query", "READ?")]


def test_spectrum_analyser_get_trace_parses_csv_response(monkeypatch):
    analyser = SpectrumAnalyser(
        SpectrumAnalyzerConfig(
            **_base_config_kwargs("spectrum_analyzer"),
            frequency_center=1_000.0,
            frequency_span=100.0,
            scpi=SCPISection(queries={"trace_data": SCPICommandSpec(template="TRACE? {channel}")}),
        ),
        NoopBackend(),
    )
    queries: list[str] = []

    def query(command: str) -> str:
        queries.append(command)
        return "-20,-21,-22"

    monkeypatch.setattr(analyser, "_query", query)

    trace = analyser.get_trace(channel=1)

    assert queries == ["TRACE? 1"]
    assert trace.x == [950.0, 1000.0, 1050.0]
    assert trace.y == [-20.0, -21.0, -22.0]


def test_spectrum_analyser_get_trace_requires_profile_alias():
    analyser = SpectrumAnalyser(
        SpectrumAnalyzerConfig(
            **_base_config_kwargs("spectrum_analyzer"),
            frequency_center=1_000.0,
            frequency_span=100.0,
        ),
        NoopBackend(),
    )

    with pytest.raises(InstrumentConfigurationError, match="trace_data"):
        analyser.get_trace(channel=1)


def test_vector_network_analyser_get_s_parameter_data_parses_complex_pairs(monkeypatch):
    analyser = VectorNetworkAnalyser(
        VNAConfig(
            **_base_config_kwargs("vna"),
            s_parameters=["S11", "S21"],
            start_frequency=100.0,
            stop_frequency=200.0,
            num_points=2,
            scpi=SCPISection(queries={"sparameter_data": SCPICommandSpec(template="DATA?")}),
        ),
        NoopBackend(),
    )
    queries: list[str] = []

    def query(command: str) -> str:
        queries.append(command)
        return "1,0,0.5,-0.5,0.2,0.1,0,-1"

    monkeypatch.setattr(analyser, "_query", query)

    data = analyser.get_s_parameter_data()

    assert queries == ["DATA?"]
    assert data.frequencies == [100.0, 200.0]
    assert data.param_names == ["S11", "S21"]
    assert data.s_params == [[1 + 0j, 0.5 - 0.5j], [0.2 + 0.1j, -1j]]


def test_vector_network_analyser_get_s_parameter_data_requires_profile_alias():
    analyser = VectorNetworkAnalyser(
        VNAConfig(
            **_base_config_kwargs("vna"),
            s_parameters=["S11"],
            start_frequency=100.0,
            stop_frequency=200.0,
            num_points=2,
        ),
        NoopBackend(),
    )

    with pytest.raises(InstrumentConfigurationError, match="sparameter_data"):
        analyser.get_s_parameter_data()


def test_waveform_generator_binary_write_propagates_backend_errors(monkeypatch):
    awg = cast(WaveformGenerator, AutoInstrument.from_config("keysight/EDU33212A", simulate=True))

    def fail_send(command: str) -> None:
        raise InstrumentCommunicationError(
            instrument=awg.config.model,
            command=command,
            message="backend write failed",
        )

    monkeypatch.setattr(awg, "_send_command", fail_send)

    with pytest.raises(InstrumentCommunicationError, match="backend write failed"):
        awg._write_binary("SOUR1:DATA:ARB:DAC TEST,", b"\x00\x01")


def test_dc_active_load_from_config_does_not_create_noop_backend():
    config = DCActiveLoadConfig(
        **_base_config_kwargs("dc_active_load"),
        operating_modes=OperatingModesSpec(),
    )

    with pytest.raises(NotImplementedError, match="AutoInstrument.from_config"):
        DCActiveLoad.from_config(config)
