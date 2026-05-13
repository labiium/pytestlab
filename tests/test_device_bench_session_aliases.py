from __future__ import annotations

import pytest

from pytestlab.bench import Bench
from pytestlab.config.bench_config import BenchConfigExtended
from pytestlab.config.device_config import DeviceConfig
from pytestlab.devices import Device
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
    pass


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
            }
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
        assert "dmm" in bench.devices
        assert "dmm" in bench.instruments
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
