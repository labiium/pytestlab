from __future__ import annotations

import pytest

from pytestlab.config.device_config import DeviceConfig
from pytestlab.config.instrument_config import InstrumentConfig
from pytestlab.config.loader import load_device_profile
from pytestlab.config.schema_validator import SchemaValidator
from pytestlab.devices import AutoDevice
from pytestlab.devices import Device
from pytestlab.devices import register_backend
from pytestlab.devices import register_config_model
from pytestlab.devices import register_device_type
from pytestlab.devices.factory import AutoDevice as AutoDeviceFactory
from pytestlab.instruments.AutoInstrument import AutoInstrument
from pytestlab.instruments.DCActiveLoad import DCActiveLoad
from pytestlab.instruments.instrument import Instrument
from pytestlab.instruments.Multimeter import Multimeter
from pytestlab.instruments.Oscilloscope import Oscilloscope
from pytestlab.instruments.PowerMeter import PowerMeter
from pytestlab.instruments.PowerSupply import PowerSupply
from pytestlab.instruments.SpectrumAnalyser import SpectrumAnalyser
from pytestlab.instruments.VectorNetworkAnalyser import VectorNetworkAnalyser
from pytestlab.instruments.VirtualInstrument import VirtualInstrument
from pytestlab.instruments.WaveformGenerator import WaveformGenerator


class WidgetConfig(DeviceConfig):
    gain: float = 1.0


class MemoryBackend:
    def __init__(self):
        self.connected = False
        self.writes: list[str] = []

    def connect(self):
        self.connected = True

    def disconnect(self):
        self.connected = False

    def write(self, cmd: str):
        self.writes.append(cmd)

    def query(self, cmd: str, delay: float | None = None) -> str:
        return f"reply:{cmd}"

    def query_raw(self, cmd: str, delay: float | None = None) -> bytes:
        return f"raw:{cmd}".encode()

    def close(self):
        self.disconnect()

    def set_timeout(self, timeout_ms: int):
        self.timeout_ms = timeout_ms

    def get_timeout(self) -> int:
        return getattr(self, "timeout_ms", 1000)


class WidgetDevice(Device[WidgetConfig]):
    def ping(self) -> str:
        return self.query("PING")


def build_memory_backend(_context):
    return MemoryBackend()


def test_autodevice_creates_registered_custom_device():
    register_config_model("test_widget", WidgetConfig, replace=True)
    register_device_type("test_widget", WidgetDevice, replace=True)
    register_backend("memory", build_memory_backend, replace=True)

    device = AutoDevice.from_config(
        {
            "device_type": "test_widget",
            "role": "fixture",
            "manufacturer": "PyTestLab",
            "model": "Widget",
            "gain": 2.5,
            "backend": {"type": "memory"},
        }
    )

    assert isinstance(device, WidgetDevice)
    assert device.config.gain == 2.5
    assert device.ping() == "reply:PING"


def test_public_hierarchy_is_device_then_instrument_then_concrete_driver():
    assert issubclass(InstrumentConfig, DeviceConfig)
    assert issubclass(Instrument, Device)
    for driver_class in [
        DCActiveLoad,
        Multimeter,
        Oscilloscope,
        PowerMeter,
        PowerSupply,
        SpectrumAnalyser,
        VectorNetworkAnalyser,
        VirtualInstrument,
        WaveformGenerator,
    ]:
        assert issubclass(driver_class, Instrument)
        assert issubclass(driver_class, Device)


def test_autodevice_builtin_instrument_instance_uses_full_hierarchy():
    device = AutoDevice.from_config("keysight/EDU34450A", simulate=True)

    assert isinstance(device, Device)
    assert isinstance(device, Instrument)
    assert isinstance(device, Multimeter)


def test_autodevice_creates_custom_device_from_import_paths():
    device = AutoDevice.from_config(
        {
            "device_type": "import_widget",
            "role": "fixture",
            "manufacturer": "PyTestLab",
            "model": "ImportWidget",
            "driver": "tests.test_device_api:WidgetDevice",
            "config_model": "tests.test_device_api:WidgetConfig",
            "backend": {"import_path": "tests.test_device_api:build_memory_backend"},
        }
    )

    assert isinstance(device, WidgetDevice)
    assert device.ping() == "reply:PING"


def test_load_device_profile_allows_driver_only_generic_custom_config():
    config = load_device_profile(
        {
            "device_type": "generic_widget",
            "role": "fixture",
            "manufacturer": "PyTestLab",
            "model": "GenericWidget",
            "driver": "tests.test_device_api:WidgetDevice",
            "custom_field": "kept",
        }
    )

    assert config.device_type == "generic_widget"
    assert config.custom_field == "kept"


def test_schema_validator_lists_registered_custom_device():
    register_config_model("schema_widget", WidgetConfig, replace=True)

    validator = SchemaValidator()

    assert "schema_widget" in validator.list_supported_devices()
    info = validator.get_schema_info("schema_widget")
    assert info["device_type"] == "schema_widget"
    assert info["model_class"] == "WidgetConfig"


def test_autoinstrument_still_returns_instrument_for_builtin_profile():
    instrument = AutoInstrument.from_config("keysight/EDU34450A", simulate=True)

    assert isinstance(instrument, Multimeter)


def test_autoinstrument_rejects_non_instrument_custom_device():
    register_config_model("instrument_reject_widget", WidgetConfig, replace=True)
    register_device_type("instrument_reject_widget", WidgetDevice, replace=True)
    register_backend("instrument_reject_memory", build_memory_backend, replace=True)

    with pytest.raises(Exception, match="not an Instrument"):
        AutoInstrument.from_config(
            {
                "device_type": "instrument_reject_widget",
                "role": "fixture",
                "manufacturer": "PyTestLab",
                "model": "Widget",
                "backend": {"type": "instrument_reject_memory"},
            }
        )


def test_from_profile_rejects_raw_config_data():
    with pytest.raises(TypeError, match="profile key or path"):
        AutoDevice.from_profile({"device_type": "test_widget"})  # type: ignore[arg-type]


def test_local_config_lookup_precedes_cdn(monkeypatch):
    calls: list[str] = []

    def local(identifier):
        calls.append(f"local:{identifier}")
        return {
            "device_type": "test_widget",
            "role": "fixture",
            "manufacturer": "PyTestLab",
            "model": "Widget",
            "driver": "tests.test_device_api:WidgetDevice",
            "backend": {"type": "memory"},
        }

    def cdn(identifier):
        calls.append(f"cdn:{identifier}")
        raise AssertionError("CDN should not be called when local lookup succeeds.")

    register_config_model("test_widget", WidgetConfig, replace=True)
    register_device_type("test_widget", WidgetDevice, replace=True)
    register_backend("memory", build_memory_backend, replace=True)
    monkeypatch.setattr(AutoDeviceFactory, "get_config_from_local", local)
    monkeypatch.setattr(AutoDeviceFactory, "get_config_from_cdn", cdn)

    device = AutoDevice.from_config("vendor/widget")

    assert isinstance(device, WidgetDevice)
    assert calls == ["local:vendor/widget"]


def test_backend_factory_internal_type_error_is_not_retried():
    def broken_factory(_context):
        raise TypeError("internal bug")

    register_config_model("broken_backend_widget", WidgetConfig, replace=True)
    register_device_type("broken_backend_widget", WidgetDevice, replace=True)
    register_backend("broken_backend", broken_factory, replace=True)

    with pytest.raises(TypeError, match="internal bug"):
        AutoDevice.from_config(
            {
                "device_type": "broken_backend_widget",
                "role": "fixture",
                "manufacturer": "PyTestLab",
                "model": "Widget",
                "backend": {"type": "broken_backend"},
            }
        )


def test_backend_factory_kwargs_convention():
    def kwargs_factory(address=None, timeout_ms=None):
        backend = MemoryBackend()
        backend.address = address
        backend.timeout_ms = timeout_ms
        return backend

    register_config_model("kwargs_backend_widget", WidgetConfig, replace=True)
    register_device_type("kwargs_backend_widget", WidgetDevice, replace=True)
    register_backend("kwargs_backend", kwargs_factory, replace=True)

    device = AutoDevice.from_config(
        {
            "device_type": "kwargs_backend_widget",
            "role": "fixture",
            "manufacturer": "PyTestLab",
            "model": "Widget",
            "address": "MEM::1",
            "backend": {"type": "kwargs_backend", "timeout_ms": 1234},
        }
    )

    assert device._backend.address == "MEM::1"
    assert device._backend.timeout_ms == 1234
