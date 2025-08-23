from __future__ import annotations

from typing import Any

import pytest

from pytestlab.config.instrument_config import InstrumentConfig
from pytestlab.config.scpi_schema import CommandSpec
from pytestlab.config.scpi_schema import SCPISection
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
    scpi: dict | None = None


class DummyInstrument(Instrument[DummyConfig]):
    def __init__(self, config: DummyConfig, **kwargs: Any):
        backend = kwargs.pop("backend", DummyBackend())
        super().__init__(config=config, backend=backend, **kwargs)


def test_feature_mapping_validation_passes_when_present():
    scpi = SCPISection(
        commands={
            "alpha": CommandSpec(template=":ALPH {v}"),
            "beta": CommandSpec(template=":BETA {v}"),
        },
    )
    cfg = DummyConfig(manufacturer="X", model="Y", device_type="dummy", scpi=scpi.model_dump())
    inst = DummyInstrument(cfg, backend=DummyBackend())
    # Should not raise
    inst._validate_features_against_scpi(
        {"myfeat": {"required_scpi": ["alpha"], "optional_scpi": ["beta"]}}, strict=True
    )


def test_feature_mapping_validation_raises_when_missing():
    scpi = SCPISection(commands={"alpha": CommandSpec(template=":ALPH {v}")})
    cfg = DummyConfig(manufacturer="X", model="Y", device_type="dummy", scpi=scpi.model_dump())
    inst = DummyInstrument(cfg, backend=DummyBackend())
    with pytest.raises(RuntimeError):
        inst._validate_features_against_scpi(
            {"myfeat": {"required_scpi": ["missing_cmd"]}}, strict=True
        )
