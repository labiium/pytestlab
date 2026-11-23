from concurrent.futures import ThreadPoolExecutor
from time import sleep
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from pytestlab import AutoInstrument
from pytestlab.cli import app
from pytestlab.devices.factory import AutoDevice
from pytestlab.errors import InstrumentConnectionError
from pytestlab.instruments.backends.sim_backend import SimBackend


class RecordingBackend:
    def __init__(self):
        self.connects = 0
        self.disconnects = 0
        self.closes = 0
        self.commands = []

    def connect(self):
        sleep(0.01)
        self.connects += 1

    def disconnect(self):
        self.disconnects += 1

    def close(self):
        self.closes += 1

    def query(self, command, delay=None):
        self.commands.append(command)
        return '0,"No error"' if "ERR" in command.upper() else "0.5"

    def query_raw(self, command, delay=None):
        return self.query(command, delay).encode()

    def write(self, command):
        self.commands.append(command)

    def get_timeout(self):
        return 1000

    def set_timeout(self, timeout_ms):
        pass


@pytest.mark.parametrize(
    "profile,operation,parameter",
    [
        ("keysight/EDU34450A", "measure", "function"),
        ("keysight/EDU33212A", "set_function", "function_type"),
        ("keysight/HD304MSO", "set_acquisition_type", "acq_type"),
    ],
)
@pytest.mark.parametrize("simulate", [False, True])
def test_normal_construction_discovery_and_unused_close_never_build_backend(
    monkeypatch, profile, operation, parameter, simulate
):
    def forbidden(*args, **kwargs):
        pytest.fail("metadata access attempted backend creation or I/O")

    monkeypatch.setattr(AutoDevice, "_build_backend", forbidden)
    monkeypatch.setattr(SimBackend, "__init__", forbidden)
    instrument = AutoInstrument.from_config(profile, simulate=simulate)
    assert instrument._command_session.instrument is instrument
    assert instrument._logger is not None
    if instrument.config.device_type == "oscilloscope":
        assert instrument.trigger is not None and instrument.acquisition is not None
    if instrument.config.device_type == "waveform_generator":
        assert instrument.channel_count == 2
    assert instrument.list_operation_options(operation, parameter)
    assert instrument.describe_operation(operation)["support"]["supported"]
    instrument.close()


def test_same_instrument_discovers_then_builds_once_on_execution(monkeypatch):
    built = []

    def build(**kwargs):
        backend = RecordingBackend()
        built.append(backend)
        return backend

    monkeypatch.setattr(AutoDevice, "_build_backend", build)
    instrument = AutoInstrument.from_config("keysight/EDU34450A")
    choice = next(
        x
        for x in instrument.list_operation_options("measure", "function")
        if x["value"] == "dc_voltage"
    )
    assert built == []
    assert instrument.measure(choice["value"], uncertainty=False).values == 0.5
    assert instrument.measure(choice["value"], uncertainty=False).values == 0.5
    assert len(built) == 1 and built[0].connects == 1
    assert built[0].commands.count("MEASURE:VOLT:DC? AUTO,DEF") == 2
    assert instrument._backend is built[0]
    instrument.close()
    assert built[0].closes == 1


def test_concurrent_first_connect_allocates_and_connects_once(monkeypatch):
    built = []

    def build(**kwargs):
        sleep(0.01)
        backend = RecordingBackend()
        built.append(backend)
        return backend

    monkeypatch.setattr(AutoDevice, "_build_backend", build)
    instrument = AutoInstrument.from_config("keysight/EDU34450A")
    assert built == []
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: instrument.connect_backend(), range(16)))
    assert len(built) == 1 and built[0].connects == 1
    instrument.close()


def test_allocation_failure_is_not_retried_by_error_cleanup_or_close(monkeypatch):
    attempts = []
    failure = RuntimeError("allocation failed")

    def build(**kwargs):
        attempts.append(1)
        raise failure

    monkeypatch.setattr(AutoDevice, "_build_backend", build)
    instrument = AutoInstrument.from_config("keysight/EDU34450A")
    with pytest.raises(InstrumentConnectionError, match="allocation failed") as exc:
        instrument.connect_backend()
    assert exc.value.__cause__ is failure
    instrument.close()
    assert attempts == [1]


def test_failed_connection_cleans_the_actual_backend_without_rebuilding(monkeypatch):
    backend = RecordingBackend()
    backend.connect = Mock(side_effect=RuntimeError("connect failed"))
    build = Mock(return_value=backend)
    monkeypatch.setattr(AutoDevice, "_build_backend", build)
    instrument = AutoInstrument.from_config("keysight/EDU34450A")
    with pytest.raises(InstrumentConnectionError, match="connect failed"):
        instrument.connect_backend()
    instrument.close()
    assert build.call_count == 1
    assert backend.disconnects == 1 and backend.closes == 1


@pytest.mark.parametrize("callable_override", [False, True])
def test_backend_override_identity_is_not_changed_or_treated_as_factory(
    monkeypatch, callable_override
):
    class FalseyBackend(RecordingBackend):
        def __bool__(self):
            return False

    backend = Mock(spec=RecordingBackend) if callable_override else FalseyBackend()
    build = Mock(side_effect=AssertionError("override was ignored"))
    monkeypatch.setattr(AutoDevice, "_build_backend", build)
    instrument = AutoInstrument.from_config("keysight/EDU34450A", backend_override=backend)
    assert instrument._backend is backend
    build.assert_not_called()
    instrument.close()


def test_cli_discovery_is_local_and_uses_normal_instrument_construction(monkeypatch):
    build = Mock(side_effect=AssertionError("CLI created backend"))
    monkeypatch.setattr(AutoDevice, "_build_backend", build)
    monkeypatch.setattr(
        AutoDevice, "get_config_from_cdn", Mock(side_effect=AssertionError("CLI fetched CDN"))
    )
    runner = CliRunner()
    success = runner.invoke(
        app, ["instrument", "list-options", "keysight/EDU34450A", "measure", "function"]
    )
    assert success.exit_code == 0, success.stdout
    missing = runner.invoke(
        app, ["instrument", "list-options", "missing/no-profile", "measure", "function"]
    )
    assert missing.exit_code == 1
    assert "CLI fetched CDN" not in missing.stdout
    build.assert_not_called()


def test_deferred_allocation_keeps_the_simulation_choice_made_at_construction(monkeypatch):
    observed = []

    def build(**kwargs):
        observed.append(kwargs["simulate"])
        return RecordingBackend()

    monkeypatch.setattr(AutoDevice, "_build_backend", build)
    monkeypatch.setenv("PYTESTLAB_SIMULATE", "true")
    instrument = AutoInstrument.from_config("keysight/EDU34450A")
    monkeypatch.setenv("PYTESTLAB_SIMULATE", "false")
    instrument.connect_backend()
    assert observed == [True]
    instrument.close()


def test_deferred_devices_keep_independent_identity_and_backend_settings(monkeypatch):
    from pytestlab.config.loader import load_device_profile

    observed = []

    def build(**kwargs):
        observed.append(
            (kwargs["config_model"].serial_number, kwargs["backend_spec_override"]["base_url"])
        )
        return RecordingBackend()

    monkeypatch.setattr(AutoDevice, "_build_backend", build)
    profile = load_device_profile("keysight/EDU34450A")
    settings = {"type": "lamb", "base_url": "http://first"}
    first = AutoInstrument.from_config(profile, serial_number="A", backend_spec_override=settings)
    settings["base_url"] = "http://second"
    second = AutoInstrument.from_config(profile, serial_number="B", backend_spec_override=settings)
    assert first.config.serial_number == "A"
    assert second.config.serial_number == "B"
    assert profile.serial_number is None
    first.connect_backend()
    second.connect_backend()
    assert observed == [("A", "http://first"), ("B", "http://second")]
    first.close()
    second.close()
