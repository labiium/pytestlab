from __future__ import annotations

from pytestlab.devices import AutoDevice


def config() -> dict:
    return {
        "manufacturer": "Fixture",
        "model": "DMM",
        "device_type": "instrument",
        "role": "measurement",
        "address": "GPIB0::12::INSTR",
        "capabilities": {"standard_commands": False, "error_queue": False},
    }


def test_factory_uses_explicit_lamb_url_over_environment(monkeypatch) -> None:
    monkeypatch.setenv("LAMB_SERVER", "http://wrong-default:8000")
    device = AutoDevice.from_dict(
        config(),
        backend_spec_override={"type": "lamb", "url": "http://configured-lamb.example:8000"},
    )
    assert device._backend.base_url == "http://configured-lamb.example:8000"
    assert device._backend.instrument_address == "GPIB0::12::INSTR"


def test_factory_uses_profile_backend_url_and_caller_override() -> None:
    profile = config()
    profile["backend"] = {"type": "lamb", "url": "http://profile:8000"}
    device = AutoDevice.from_dict(profile)
    assert device._backend.base_url == "http://profile:8000"
    override = AutoDevice.from_dict(
        profile,
        backend_spec_override={"url": "http://caller:8000"},
    )
    assert override._backend.base_url == "http://caller:8000"
    assert profile["backend"]["url"] == "http://profile:8000"


def test_factory_retains_environment_fallback(monkeypatch) -> None:
    monkeypatch.setenv("LAMB_SERVER", "http://environment:8000")
    device = AutoDevice.from_dict(config(), backend_type_hint="lamb")
    assert device._backend.base_url == "http://environment:8000"
