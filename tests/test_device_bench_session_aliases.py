from __future__ import annotations

import pytest

from pytestlab.bench import Bench
from pytestlab.bench import SafetyLimitError
from pytestlab.config.bench_config import BenchConfigExtended
from pytestlab.config.device_config import DeviceConfig
from pytestlab.devices import Device
from pytestlab.errors import InstrumentConfigurationError
from pytestlab.measurements.session import MeasurementSession


class BenchWidgetConfig(DeviceConfig):
    gain: float = 1.0


class BenchMemoryBackend:
    def connect(self):
        pass

    def disconnect(self):
        pass

    def write(self, cmd: str):
        pass

    def query(self, cmd: str, delay: float | None = None) -> str:
        return f"reply:{cmd}"

    def query_raw(self, cmd: str, delay: float | None = None) -> bytes:
        return f"raw:{cmd}".encode()

    def close(self):
        pass

    def set_timeout(self, timeout_ms: int):
        self.timeout_ms = timeout_ms

    def get_timeout(self) -> int:
        return getattr(self, "timeout_ms", 1000)


class BenchWidgetDevice(Device[BenchWidgetConfig]):
    def set_voltage(self, channel, voltage):
        self.voltage = (channel, voltage)

    def set_current(self, channel, current):
        self.current = (channel, current)

    def set_amplitude(self, channel, amplitude):
        self.amplitude = (channel, amplitude)

    def set_frequency(self, channel, frequency):
        self.frequency = (channel, frequency)

    def set_load(self, value):
        self.load = value


def build_bench_memory_backend(_context):
    return BenchMemoryBackend()


def test_bench_config_accepts_devices():
    config = BenchConfigExtended.model_validate(
        {
            "bench_name": "Device Bench",
            "devices": {
                "dmm": {
                    "profile": "keysight/EDU34450A",
                    "simulate": True,
                }
            },
        }
    )

    assert "dmm" in config.devices


def test_bench_config_accepts_instruments_as_semantic_section():
    config = BenchConfigExtended.model_validate(
        {
            "bench_name": "Instrument Bench",
            "instruments": {
                "dmm": {
                    "profile": "keysight/EDU34450A",
                    "simulate": True,
                }
            },
        }
    )

    assert "dmm" in config.instruments
    assert not config.devices


def test_bench_rejects_duplicate_device_and_instrument_alias():
    with pytest.raises(ValueError, match="both devices and instruments"):
        BenchConfigExtended.model_validate(
            {
                "bench_name": "Duplicate Bench",
                "devices": {"dmm": {"profile": "keysight/EDU34450A"}},
                "instruments": {"dmm": {"profile": "keysight/EDU34450A"}},
            }
        )


def test_bench_instruments_section_initializes_only_instruments():
    bench = Bench.open(
        {
            "bench_name": "Instrument Runtime Bench",
            "simulate": True,
            "instruments": {"dmm": {"profile": "keysight/EDU34450A"}},
        }
    )

    try:
        assert "dmm" in bench.resources
        assert "dmm" in bench.instruments
        assert bench.support_devices == {}
        with pytest.warns(DeprecationWarning, match="will return support devices only"):
            assert "dmm" in bench.devices
        session = MeasurementSession(bench=bench, compliance=False)
        assert session.instrument("dmm", "unused") is bench.dmm
    finally:
        bench.close_all()


def test_bench_instruments_section_rejects_non_instrument_device(tmp_path):
    profile = tmp_path / "widget.yaml"
    profile.write_text(
        "\n".join(
            [
                "device_type: bench_widget",
                "role: fixture",
                "manufacturer: PyTestLab",
                "model: Widget",
                "driver: tests.test_device_bench_session_aliases:BenchWidgetDevice",
                "config_model: tests.test_device_bench_session_aliases:BenchWidgetConfig",
                "backend:",
                "  import_path: tests.test_device_bench_session_aliases:build_bench_memory_backend",
            ]
        )
    )

    with pytest.raises(Exception, match="not an Instrument"):
        Bench.open(
            {
                "bench_name": "Invalid Instrument Bench",
                "instruments": {"widget": {"profile": str(profile)}},
            }
        )


def test_measurement_session_device_alias_creates_device():
    session = MeasurementSession(compliance=False)

    device = session.device("dmm", "keysight/EDU34450A", simulate=True)

    assert device.config.device_type == "multimeter"


def _write_widget_profile(tmp_path, *, role: str) -> str:
    profile = tmp_path / f"widget_{role}.yaml"
    profile.write_text(
        "\n".join(
            [
                "device_type: bench_widget",
                f"role: {role}",
                "manufacturer: PyTestLab",
                "model: Widget",
                "driver: tests.test_device_bench_session_aliases:BenchWidgetDevice",
                "config_model: tests.test_device_bench_session_aliases:BenchWidgetConfig",
                "backend:",
                "  import_path: tests.test_device_bench_session_aliases:build_bench_memory_backend",
            ]
        )
    )
    return str(profile)


def test_bench_entry_role_override_takes_precedence(tmp_path):
    profile = _write_widget_profile(tmp_path, role="stimulus")

    bench = Bench.open(
        {
            "bench_name": "Role Override Bench",
            "devices": {"widget": {"profile": profile, "role": "conditioning"}},
        }
    )

    try:
        assert bench.resources["widget"].config.role.value == "conditioning"
        assert "widget" in bench.support_devices
    finally:
        bench.close_all()


def test_bench_entry_omitted_role_inherits_profile_role(tmp_path):
    profile = _write_widget_profile(tmp_path, role="stimulus")

    bench = Bench.open(
        {"bench_name": "Inherited Role Bench", "devices": {"widget": {"profile": profile}}}
    )

    try:
        assert bench.resources["widget"].config.role.value == "stimulus"
    finally:
        bench.close_all()


def test_custom_role_warns_at_bench_initialization(tmp_path):
    profile = _write_widget_profile(tmp_path, role="custom")

    with pytest.warns(UserWarning, match="uses custom role"):
        bench = Bench.open(
            {"bench_name": "Custom Role Bench", "devices": {"widget": {"profile": profile}}}
        )

    bench.close_all()


def test_safety_limits_use_declared_stimulus_role(tmp_path):
    profile = _write_widget_profile(tmp_path, role="stimulus")

    bench = Bench.open(
        {
            "bench_name": "Stimulus Safety Bench",
            "devices": {
                "widget": {
                    "profile": profile,
                    "safety_limits": {
                        "channels": {
                            1: {
                                "amplitude": {"max": 2.0},
                                "frequency": {"max": 1000.0},
                            }
                        }
                    },
                }
            },
        }
    )

    try:
        bench.widget.set_amplitude(1, 1.5)
        bench.widget.set_frequency(1, 500.0)
        with pytest.raises(SafetyLimitError):
            bench.widget.set_amplitude(1, 2.5)
        with pytest.raises(SafetyLimitError):
            bench.widget.set_frequency(1, 1500.0)
    finally:
        bench.close_all()


def test_safety_limits_use_declared_load_role(tmp_path):
    profile = _write_widget_profile(tmp_path, role="load")

    bench = Bench.open(
        {
            "bench_name": "Load Safety Bench",
            "devices": {
                "widget": {
                    "profile": profile,
                    "safety_limits": {"load": {"max": 5.0}},
                }
            },
        }
    )

    try:
        bench.widget.set_load(4.0)
        with pytest.raises(SafetyLimitError):
            bench.widget.set_load(6.0)
    finally:
        bench.close_all()


def test_safety_limits_reject_unsupported_role_even_if_methods_match(tmp_path):
    profile = _write_widget_profile(tmp_path, role="fixture")

    with pytest.raises(
        InstrumentConfigurationError, match="not supported for device role 'fixture'"
    ):
        Bench.open(
            {
                "bench_name": "Fixture Safety Bench",
                "devices": {
                    "widget": {
                        "profile": profile,
                        "safety_limits": {"channels": {1: {"voltage": {"max": 5.0}}}},
                    }
                },
            }
        )
