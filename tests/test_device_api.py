from __future__ import annotations

from typing import cast

import pytest
import yaml

from pytestlab.config.device_config import DeviceConfig
from pytestlab.config.device_config import DeviceRole
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
        self.address: str | None = None
        self.timeout_ms: int | None = None

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


class CameraConfig(DeviceConfig):
    resolution: tuple[int, int] = (640, 480)


class CameraDevice(Device[CameraConfig]):
    def capture(self, *, label: str = "frame") -> dict[str, object]:
        return {
            "label": label,
            "resolution": self.config.resolution,
            "device": self.config.model,
        }


class GantryConfig(DeviceConfig):
    x_limit_mm: float
    y_limit_mm: float
    z_limit_mm: float


class GantryDevice(Device[GantryConfig]):
    def move_to(self, *, x_mm: float, y_mm: float, z_mm: float) -> tuple[float, float, float]:
        if not (0 <= x_mm <= self.config.x_limit_mm):
            raise ValueError("x_mm outside configured gantry limit")
        if not (0 <= y_mm <= self.config.y_limit_mm):
            raise ValueError("y_mm outside configured gantry limit")
        if not (0 <= z_mm <= self.config.z_limit_mm):
            raise ValueError("z_mm outside configured gantry limit")
        self.position = (x_mm, y_mm, z_mm)
        return self.position

    def wait_until_settled(self) -> bool:
        return True


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
    backend = cast(MemoryBackend, device._backend)
    assert not backend.connected
    assert device.ping() == "reply:PING"
    assert backend.connected


def test_autodevice_connects_lazily_before_backend_operations():
    register_config_model("lazy_widget", WidgetConfig, replace=True)
    register_device_type("lazy_widget", WidgetDevice, replace=True)
    register_backend("lazy_memory", build_memory_backend, replace=True)

    device = AutoDevice.from_config(
        {
            "device_type": "lazy_widget",
            "role": "fixture",
            "manufacturer": "PyTestLab",
            "model": "LazyWidget",
            "backend": {"type": "lazy_memory"},
        }
    )

    backend = cast(MemoryBackend, device._backend)
    assert not backend.connected
    assert device.query("PING") == "reply:PING"
    assert backend.connected


def test_connect_backend_remains_idempotent_for_explicit_lifecycle_control():
    register_config_model("idempotent_widget", WidgetConfig, replace=True)
    register_device_type("idempotent_widget", WidgetDevice, replace=True)
    register_backend("idempotent_memory", build_memory_backend, replace=True)

    device = AutoDevice.from_config(
        {
            "device_type": "idempotent_widget",
            "role": "fixture",
            "manufacturer": "PyTestLab",
            "model": "IdempotentWidget",
            "backend": {"type": "idempotent_memory"},
        }
    )

    device.connect_backend()
    device.connect_backend()

    assert cast(MemoryBackend, device._backend).connected


def test_autodevice_explicit_source_factories_are_unambiguous(tmp_path):
    register_config_model("source_widget", WidgetConfig, replace=True)
    register_device_type("source_widget", WidgetDevice, replace=True)
    register_backend("source_memory", build_memory_backend, replace=True)

    profile = tmp_path / "widget.yaml"
    profile.write_text(
        yaml.safe_dump(
            {
                "device_type": "source_widget",
                "role": "fixture",
                "manufacturer": "PyTestLab",
                "model": "SourceWidget",
                "gain": 3.5,
                "backend": {"type": "source_memory"},
            }
        )
    )

    from_file = AutoDevice.from_file(profile)
    from_dict = AutoDevice.from_dict(
        {
            "device_type": "source_widget",
            "role": "fixture",
            "manufacturer": "PyTestLab",
            "model": "SourceWidget",
            "gain": 4.5,
            "backend": {"type": "source_memory"},
        }
    )
    from_model = AutoDevice.from_model(
        WidgetConfig(
            device_type="source_widget",
            role=DeviceRole.FIXTURE,
            manufacturer="PyTestLab",
            model="SourceWidget",
            gain=5.5,
            backend={"type": "source_memory"},
        )
    )

    assert isinstance(from_file, WidgetDevice)
    assert from_file.config.gain == 3.5
    assert from_dict.config.gain == 4.5
    assert from_model.config.gain == 5.5

    with pytest.raises(ValueError, match="packaged preset keys only"):
        AutoDevice.from_preset(str(profile))
    with pytest.raises(ValueError, match="YAML or JSON file path"):
        AutoDevice.from_file("keysight/EDU34450A")
    with pytest.raises(TypeError, match="configuration mapping"):
        AutoDevice.from_dict("keysight/EDU34450A")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="DeviceConfig"):
        AutoDevice.from_model({"device_type": "source_widget"})  # type: ignore[arg-type]


def test_from_config_string_remains_compatible_without_warning():
    device = AutoDevice.from_config("keysight/EDU34450A", simulate=True)

    assert isinstance(device, Multimeter)


def test_from_preset_ignores_same_named_cwd_paths(tmp_path, monkeypatch):
    shadow = tmp_path / "keysight" / "EDU34450A"
    shadow.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)

    device = AutoDevice.from_preset("keysight/EDU34450A", simulate=True)

    assert isinstance(device, Multimeter)


def test_autoinstrument_explicit_source_factories_and_rejections(tmp_path):
    instrument = AutoInstrument.from_preset("keysight/EDU34450A", simulate=True)
    assert isinstance(instrument, Multimeter)

    with pytest.raises(ValueError, match="from_file"):
        AutoInstrument.from_preset(str(tmp_path / "local.yaml"), simulate=True)

    config = load_device_profile("keysight/EDU34450A")
    assert isinstance(config, InstrumentConfig)
    from_model = AutoInstrument.from_model(config, simulate=True)
    assert isinstance(from_model, Multimeter)

    register_config_model("source_reject_widget", WidgetConfig, replace=True)
    register_device_type("source_reject_widget", WidgetDevice, replace=True)
    register_backend("source_reject_memory", build_memory_backend, replace=True)
    local = tmp_path / "widget.yaml"
    local.write_text(
        yaml.safe_dump(
            {
                "device_type": "source_reject_widget",
                "role": "fixture",
                "manufacturer": "PyTestLab",
                "model": "Widget",
                "backend": {"type": "source_reject_memory"},
            }
        )
    )
    with pytest.raises(Exception, match="not an Instrument"):
        AutoInstrument.from_file(local)


def test_non_scpi_camera_and_gantry_patterns_load_as_devices_from_files(tmp_path):
    register_config_model("camera", CameraConfig, replace=True)
    register_device_type("camera", CameraDevice, replace=True)
    register_config_model("gantry", GantryConfig, replace=True)
    register_device_type("gantry", GantryDevice, replace=True)
    register_backend("non_scpi_memory", build_memory_backend, replace=True)

    camera_profile = tmp_path / "camera.yaml"
    camera_profile.write_text(
        yaml.safe_dump(
            {
                "device_type": "camera",
                "role": "metadata",
                "manufacturer": "PyTestLab",
                "model": "InspectionCam",
                "resolution": [1280, 720],
                "backend": {"type": "non_scpi_memory"},
            }
        )
    )
    gantry_profile = tmp_path / "gantry.yaml"
    gantry_profile.write_text(
        yaml.safe_dump(
            {
                "device_type": "gantry",
                "role": "dut_control",
                "manufacturer": "PyTestLab",
                "model": "XYZStage",
                "x_limit_mm": 100.0,
                "y_limit_mm": 50.0,
                "z_limit_mm": 10.0,
                "backend": {"type": "non_scpi_memory"},
            }
        )
    )

    camera = AutoDevice.from_file(camera_profile)
    gantry = AutoDevice.from_file(gantry_profile)

    assert isinstance(camera, CameraDevice)
    assert camera.capture(label="precheck")["resolution"] == (1280, 720)
    assert isinstance(gantry, GantryDevice)
    assert gantry.move_to(x_mm=12.5, y_mm=3.0, z_mm=1.2) == (12.5, 3.0, 1.2)
    with pytest.raises(ValueError, match="x_mm"):
        gantry.move_to(x_mm=101.0, y_mm=3.0, z_mm=1.2)
    with pytest.raises(Exception, match="not an Instrument"):
        AutoInstrument.from_file(camera_profile)


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
    assert config.model_extra is not None
    assert config.model_extra["custom_field"] == "kept"


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

    backend = cast(MemoryBackend, device._backend)
    assert backend.address == "MEM::1"
    assert backend.timeout_ms == 1234
