from __future__ import annotations

from dataclasses import dataclass

import pytest
from pydantic import BaseModel
from pydantic import Field
from rich.console import Console

from pytestlab.common.health import HealthReport
from pytestlab.common.health import HealthStatus
from pytestlab.verification import VerificationReport
from pytestlab.verification import VerificationResult
from pytestlab.verification import VerificationStatus
from pytestlab.verification.profile_verify import render_verification_report
from pytestlab.verification.profile_verify import verify_instrument_profile


class DummyFunctionSpec(BaseModel):
    required_scpi_commands: list[str] = Field(default_factory=list)


class DummyMeasurementFunctions(BaseModel):
    required_scpi_commands: list[str] = Field(default_factory=list)
    dc_voltage: DummyFunctionSpec | None = None


class DummyScpiSection(BaseModel):
    feature_mappings: dict[str, dict[str, list[str]]] | None = None


class DummyChannel(BaseModel):
    channel_id: int = 1


class DummyConfig(BaseModel):
    manufacturer: str
    model: str
    device_type: str
    scpi: DummyScpiSection | None = None
    measurement_functions: DummyMeasurementFunctions | None = None
    channels: list[DummyChannel] = Field(default_factory=list)


@dataclass
class FakeMultimeterSnapshot:
    measurement_mode: str = "VOLT:DC"


class FakeScpiEngine:
    def __init__(self):
        self._descriptions = {
            "get_status": {"sequence": ["STAT?"]},
            "measure_voltage": {"sequence": ["MEAS:VOLT?"]},
        }

    def validate_presence(self, names: list[str]) -> dict[str, bool]:
        return {name: name in self._descriptions for name in names}

    def describe(self, name: str) -> dict[str, list[str]]:
        return self._descriptions[name]

    def validate_placeholders(self, name: str) -> dict[str, list[str]]:
        return {"placeholders": []}

    def build(self, name: str) -> list[str]:
        return [self._descriptions[name]["sequence"][0]]

    def parse(self, name: str, raw: str) -> str:
        return f"{name}:{raw}"


class FakeInstrument:
    def __init__(self, *, idn: str = "Keysight,EDU34450A,MY1234,1.0"):
        self._idn = idn
        self.scpi_engine = FakeScpiEngine()
        self.closed = False
        self.connected = False
        self.health_calls = 0
        self.query_calls: list[str] = []
        self.function_writes: list[str] = []

    def connect_backend(self) -> None:
        self.connected = True

    def close(self) -> None:
        self.closed = True

    def id(self) -> str:
        return self._idn

    def health_check(self) -> HealthReport:
        self.health_calls += 1
        return HealthReport(
            status=HealthStatus.OK,
            warnings=["Calibration date not available."],
            supported_features={"basic_measurement": True},
        )

    def _query(self, cmd: str) -> str:
        self.query_calls.append(cmd)
        responses = {"STAT?": "READY", "MEAS:VOLT?": "1.234"}
        return responses[cmd]

    def get_config(self) -> FakeMultimeterSnapshot:
        return FakeMultimeterSnapshot()

    def set_measurement_function(self, function: object) -> None:
        self.function_writes.append(str(function))


class CloseFailingInstrument(FakeInstrument):
    def close(self) -> None:
        raise RuntimeError("close failed")


@dataclass
class FakePowerSupplyChannel:
    voltage: float = 1.25
    current: float = 0.5
    state: str = "OFF"


class FakePowerSupply(FakeInstrument):
    def __init__(self):
        super().__init__(idn="Keysight,EDU36311A,MY1234,1.0")
        self.read_channels: list[int] = []
        self.voltage_calls: list[tuple[int, float]] = []
        self.current_calls: list[tuple[int, float]] = []
        self.output_calls: list[tuple[int, bool]] = []

    def get_configuration(self) -> dict[int, FakePowerSupplyChannel]:
        return {2: FakePowerSupplyChannel()}

    def read_voltage(self, channel: int) -> float:
        self.read_channels.append(channel)
        return 1.25

    def read_current(self, channel: int) -> float:
        self.read_channels.append(channel)
        return 0.5

    def set_voltage(self, channel: int, voltage: float) -> None:
        self.voltage_calls.append((channel, voltage))

    def set_current(self, channel: int, current: float) -> None:
        self.current_calls.append((channel, current))

    def output(self, channel: int, enabled: bool) -> None:
        self.output_calls.append((channel, enabled))


class FakeWaveformGenerator(FakeInstrument):
    def __init__(self):
        super().__init__(idn="Keysight,EDU33212A,MY1234,1.0")
        self.frequency_calls: list[tuple[int, float]] = []
        self.amplitude_calls: list[tuple[int, float]] = []
        self.output_calls: list[tuple[int, bool]] = []

    def get_frequency(self, channel: int) -> float:
        return 1_000.0 + channel

    def get_amplitude(self, channel: int) -> float:
        return 2.5

    def get_output_state(self, channel: int) -> bool:
        return False

    def set_frequency(self, channel: int, frequency: float) -> None:
        self.frequency_calls.append((channel, frequency))

    def set_amplitude(self, channel: int, amplitude: float) -> None:
        self.amplitude_calls.append((channel, amplitude))

    def set_output_state(self, channel: int, enabled: bool) -> None:
        self.output_calls.append((channel, enabled))


def _dummy_config(
    *,
    device_type: str = "multimeter",
    model: str = "EDU34450A",
    channels: list[DummyChannel] | None = None,
) -> DummyConfig:
    return DummyConfig(
        manufacturer="Keysight",
        model=model,
        device_type=device_type,
        scpi=DummyScpiSection(
            feature_mappings={"measurement": {"required_scpi": ["measure_voltage"]}}
        ),
        measurement_functions=DummyMeasurementFunctions(
            required_scpi_commands=["get_status"],
            dc_voltage=DummyFunctionSpec(required_scpi_commands=["measure_voltage"]),
        ),
        channels=channels or [],
    )


def test_verify_instrument_profile_read_only_avoids_health_and_query_smoke(
    monkeypatch: pytest.MonkeyPatch,
):
    instrument = FakeInstrument()
    monkeypatch.setattr(
        "pytestlab.verification.profile_verify.load_profile",
        lambda profile_source: _dummy_config(),
    )
    monkeypatch.setattr(
        "pytestlab.verification.profile_verify.AutoInstrument.from_config",
        lambda **kwargs: instrument,
    )

    report = verify_instrument_profile("keysight/EDU34450A")

    assert report.has_failures is False
    assert {"Schema", "Connection", "Identity", "SCPI", "Plugin"} <= {
        result.category for result in report.results
    }
    assert "Health" not in {result.category for result in report.results}
    assert any(result.id == "plugin.multimeter.get-config" for result in report.results)
    assert not any(result.id.startswith("scpi.query.") for result in report.results)
    assert instrument.health_calls == 0
    assert instrument.query_calls == []
    assert instrument.closed is True


def test_verify_instrument_profile_safe_write_runs_health_queries_and_reapplies_mode(
    monkeypatch: pytest.MonkeyPatch,
):
    instrument = FakeInstrument()
    monkeypatch.setattr(
        "pytestlab.verification.profile_verify.load_profile",
        lambda profile_source: _dummy_config(),
    )
    monkeypatch.setattr(
        "pytestlab.verification.profile_verify.AutoInstrument.from_config",
        lambda **kwargs: instrument,
    )

    report = verify_instrument_profile("keysight/EDU34450A", probe_mode="safe-write")

    assert report.has_failures is False
    assert {"Health", "SCPI", "Plugin"} <= {result.category for result in report.results}
    assert any(result.id == "scpi.query.get_status" for result in report.results)
    assert any(result.id == "scpi.query.measure_voltage" for result in report.results)
    assert instrument.health_calls == 1
    assert instrument.query_calls == ["STAT?", "MEAS:VOLT?"]
    assert instrument.function_writes == ["DMMFunction.VOLTAGE_DC"]
    assert instrument.closed is True


def test_verify_instrument_profile_fail_fast_stops_after_first_failure(
    monkeypatch: pytest.MonkeyPatch,
):
    instrument = FakeInstrument(idn="Rigol,DM3058E,MY0001,1.0")
    monkeypatch.setattr(
        "pytestlab.verification.profile_verify.load_profile",
        lambda profile_source: _dummy_config(),
    )
    monkeypatch.setattr(
        "pytestlab.verification.profile_verify.AutoInstrument.from_config",
        lambda **kwargs: instrument,
    )

    report = verify_instrument_profile("keysight/EDU34450A", fail_fast=True)

    assert report.has_failures is True
    assert [result.category for result in report.results] == [
        "Schema",
        "Connection",
        "Identity",
    ]
    assert instrument.health_calls == 0
    assert instrument.closed is True


def test_verify_instrument_profile_reports_close_failures(
    monkeypatch: pytest.MonkeyPatch,
):
    instrument = CloseFailingInstrument()
    monkeypatch.setattr(
        "pytestlab.verification.profile_verify.load_profile",
        lambda profile_source: _dummy_config(),
    )
    monkeypatch.setattr(
        "pytestlab.verification.profile_verify.AutoInstrument.from_config",
        lambda **kwargs: instrument,
    )

    report = verify_instrument_profile("keysight/EDU34450A")

    cleanup_results = [result for result in report.results if result.id == "cleanup.close"]
    assert len(cleanup_results) == 1
    assert cleanup_results[0].status == VerificationStatus.WARN
    assert cleanup_results[0].details == "close failed"


def test_verify_instrument_profile_rejects_invalid_probe_mode():
    with pytest.raises(ValueError, match="probe_mode"):
        verify_instrument_profile("keysight/EDU34450A", probe_mode="aggressive")  # type: ignore[arg-type]


def test_power_supply_safe_write_uses_profile_channel_and_gates_writes(
    monkeypatch: pytest.MonkeyPatch,
):
    instrument = FakePowerSupply()
    monkeypatch.setattr(
        "pytestlab.verification.profile_verify.load_profile",
        lambda profile_source: _dummy_config(
            device_type="power_supply",
            model="EDU36311A",
            channels=[DummyChannel(channel_id=2)],
        ),
    )
    monkeypatch.setattr(
        "pytestlab.verification.profile_verify.AutoInstrument.from_config",
        lambda **kwargs: instrument,
    )

    report = verify_instrument_profile("keysight/EDU36311A", probe_mode="safe-write")

    assert report.has_failures is False
    assert instrument.read_channels == [2, 2]
    assert instrument.voltage_calls == []
    assert instrument.current_calls == []
    assert instrument.output_calls == []
    assert any(
        result.id == "plugin.psu.output-state" and result.status == VerificationStatus.SKIP
        for result in report.results
    )
    assert any(
        result.id == "plugin.psu.set-voltage" and result.status == VerificationStatus.SKIP
        for result in report.results
    )
    assert any(
        result.id == "plugin.psu.set-current" and result.status == VerificationStatus.SKIP
        for result in report.results
    )


def test_power_supply_safe_write_allows_setpoint_writes_when_explicit(
    monkeypatch: pytest.MonkeyPatch,
):
    instrument = FakePowerSupply()
    monkeypatch.setattr(
        "pytestlab.verification.profile_verify.load_profile",
        lambda profile_source: _dummy_config(
            device_type="power_supply",
            model="EDU36311A",
            channels=[DummyChannel(channel_id=2)],
        ),
    )
    monkeypatch.setattr(
        "pytestlab.verification.profile_verify.AutoInstrument.from_config",
        lambda **kwargs: instrument,
    )

    report = verify_instrument_profile(
        "keysight/EDU36311A",
        probe_mode="safe-write",
        allow_output_enable=True,
    )

    assert report.has_failures is False
    assert instrument.voltage_calls == [(2, 1.25)]
    assert instrument.current_calls == [(2, 0.5)]
    assert instrument.output_calls == [(2, False)]


def test_awg_safe_write_gates_setpoint_writes(
    monkeypatch: pytest.MonkeyPatch,
):
    instrument = FakeWaveformGenerator()
    monkeypatch.setattr(
        "pytestlab.verification.profile_verify.load_profile",
        lambda profile_source: _dummy_config(
            device_type="waveform_generator",
            model="EDU33212A",
            channels=[DummyChannel(channel_id=3)],
        ),
    )
    monkeypatch.setattr(
        "pytestlab.verification.profile_verify.AutoInstrument.from_config",
        lambda **kwargs: instrument,
    )

    report = verify_instrument_profile("keysight/EDU33212A", probe_mode="safe-write")

    assert report.has_failures is False
    assert instrument.frequency_calls == []
    assert instrument.amplitude_calls == []
    assert instrument.output_calls == []
    assert any(
        result.id == "plugin.awg.set-frequency" and result.status == VerificationStatus.SKIP
        for result in report.results
    )
    assert any(
        result.id == "plugin.awg.set-amplitude" and result.status == VerificationStatus.SKIP
        for result in report.results
    )


def test_awg_safe_write_allows_setpoint_writes_when_explicit(
    monkeypatch: pytest.MonkeyPatch,
):
    instrument = FakeWaveformGenerator()
    monkeypatch.setattr(
        "pytestlab.verification.profile_verify.load_profile",
        lambda profile_source: _dummy_config(
            device_type="waveform_generator",
            model="EDU33212A",
            channels=[DummyChannel(channel_id=3)],
        ),
    )
    monkeypatch.setattr(
        "pytestlab.verification.profile_verify.AutoInstrument.from_config",
        lambda **kwargs: instrument,
    )

    report = verify_instrument_profile(
        "keysight/EDU33212A",
        probe_mode="safe-write",
        allow_output_enable=True,
    )

    assert report.has_failures is False
    assert instrument.frequency_calls == [(3, 1_003.0)]
    assert instrument.amplitude_calls == [(3, 2.5)]
    assert instrument.output_calls == [(3, False)]


def test_render_verification_report_outputs_human_readable_summary():
    report = VerificationReport(
        profile_source="keysight/EDU34450A",
        device_type="multimeter",
        manufacturer="Keysight",
        model="EDU34450A",
        probe_mode="read-only",
        address_override="USB0::1",
        results=[
            VerificationResult(
                id="schema.load-profile",
                category="Schema",
                status=VerificationStatus.PASS,
                summary="Profile loaded.",
            ),
            VerificationResult(
                id="identity.idn",
                category="Identity",
                status=VerificationStatus.FAIL,
                summary="IDN mismatch.",
                expected="Keysight / EDU34450A",
                observed="Rigol / DM3058E",
            ),
        ],
    )
    console = Console(record=True, width=120)

    render_verification_report(report, console=console)

    rendered = console.export_text()
    assert "Instrument Profile Verification" in rendered
    assert "Keysight EDU34450A (multimeter)" in rendered
    assert "PASS=1" in rendered
    assert "FAIL=1" in rendered
    assert "identity.idn" in rendered
