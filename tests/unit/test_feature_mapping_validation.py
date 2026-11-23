from __future__ import annotations

from typing import Any

import pytest

from pytestlab.config.instrument_config import InstrumentConfig
from pytestlab.config.instrument_config import SCPICommandSpec
from pytestlab.config.instrument_config import SCPISection
from pytestlab.errors import InstrumentConfigurationError
from pytestlab.instruments.instrument import Instrument


class DummyBackend:
    def connect(self):
        pass

    def disconnect(self):
        pass

    def write(self, cmd: str):
        pass

    def query(self, cmd: str, delay: float | None = None) -> str:
        return "OK"

    def query_raw(self, cmd: str, delay: float | None = None) -> bytes:
        return b"#10OK"

    def close(self):
        pass

    def set_timeout(self, timeout_ms: int):
        pass

    def get_timeout(self) -> int:
        return 1000


class DummyConfig(InstrumentConfig):
    device_type: str = "dummy"
    scpi: SCPISection | None = None


class DummyInstrument(Instrument[DummyConfig]):
    def __init__(self, config: DummyConfig, **kwargs: Any):
        backend = kwargs.pop("backend", DummyBackend())
        super().__init__(config=config, backend=backend, **kwargs)


def test_feature_mapping_validation_passes_when_present():
    scpi = SCPISection(
        commands={
            "alpha": SCPICommandSpec(template=":ALPH {v}"),
            "beta": SCPICommandSpec(template=":BETA {v}"),
        },
    )
    cfg = DummyConfig(manufacturer="X", model="Y", device_type="dummy", role="custom", scpi=scpi)
    inst = DummyInstrument(cfg, backend=DummyBackend())
    # Should not raise
    inst._validate_features_against_scpi(
        {"myfeat": {"required_scpi": ["alpha"], "optional_scpi": ["beta"]}}, strict=True
    )


def test_feature_mapping_validation_raises_when_missing():
    scpi = SCPISection(commands={"alpha": SCPICommandSpec(template=":ALPH {v}")})
    cfg = DummyConfig(manufacturer="X", model="Y", device_type="dummy", role="custom", scpi=scpi)
    inst = DummyInstrument(cfg, backend=DummyBackend())
    with pytest.raises(RuntimeError):
        inst._validate_features_against_scpi(
            {"myfeat": {"required_scpi": ["missing_cmd"]}}, strict=True
        )


@pytest.mark.parametrize(
    "method",
    ["id", "reset", "run_self_test"],
)
def test_profile_required_lifecycle_aliases_do_not_fall_back_to_commands(method):
    """Lifecycle operations must fail clearly when the profile is incomplete."""

    cfg = DummyConfig(
        manufacturer="X", model="Y", device_type="dummy", role="custom", scpi=SCPISection()
    )
    inst = DummyInstrument(cfg, backend=DummyBackend())
    with pytest.raises(InstrumentConfigurationError) as exc_info:
        getattr(inst, method)()
    assert "Profile does not implement" in str(exc_info.value)


def test_feature_mapping_validation_does_not_swallow_engine_failures(monkeypatch):
    cfg = DummyConfig(
        manufacturer="X", model="Y", device_type="dummy", role="custom", scpi=SCPISection()
    )
    inst = DummyInstrument(cfg, backend=DummyBackend())

    def fail_list_names():
        raise RuntimeError("broken profile metadata")

    monkeypatch.setattr(inst._scpi_engine, "list_names", fail_list_names)
    with pytest.raises(RuntimeError, match="broken profile metadata"):
        inst._validate_features_against_scpi({}, strict=True)
