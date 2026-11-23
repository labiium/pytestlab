from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from pytestlab.bench import Bench
from pytestlab.devices.factory import AutoDevice
from pytestlab.instruments.AutoInstrument import AutoInstrument


class Backend:
    pass


@pytest.fixture
def dmm_profile_data() -> dict:
    return AutoDevice.get_config_from_preset("agilent/3458A")


@pytest.mark.parametrize(
    "factory",
    ["from_config", "from_preset", "from_file", "from_dict", "from_model", "from_profile"],
)
def test_auto_instrument_factories_forward_transport_override(
    factory: str, dmm_profile_data: dict, tmp_path: Path
) -> None:
    override = {"min_command_interval_s": 0.5, "read_termination": "\r\n"}
    file_path = tmp_path / "3458A.yaml"
    file_path.write_text(yaml.safe_dump(dmm_profile_data))
    model, _, _ = AutoDevice._load_config_model(dmm_profile_data)
    sources = {
        "from_config": (dmm_profile_data,),
        "from_preset": ("agilent/3458A",),
        "from_file": (file_path,),
        "from_dict": (dmm_profile_data,),
        "from_model": (model,),
        "from_profile": ("agilent/3458A",),
    }
    original = dmm_profile_data.copy()

    device = getattr(AutoInstrument, factory)(
        *sources[factory], backend_override=Backend(), transport_override=override
    )

    assert device.config.transport == {
        "min_command_interval_s": 0.5,
        "read_termination": "\r\n",
    }
    assert dmm_profile_data == original


def test_bench_instrument_entries_apply_transport_without_connecting(tmp_path, monkeypatch):
    import pytestlab.instruments.backends.lamb as lamb_backend

    def no_http_client(*args, **kwargs):
        raise AssertionError("lazy instrument session must not create an HTTP client")

    monkeypatch.setattr(lamb_backend.httpx, "Client", no_http_client)
    bench_path = tmp_path / "bench.yaml"
    bench_path.write_text(
        yaml.safe_dump(
            {
                "bench_name": "Instrument transport override test",
                "simulate": False,
                "instruments": {
                    "dmm": {
                        "profile": "agilent/3458A",
                        "address": "GPIB0::12::INSTR",
                        "simulate": False,
                        "backend": {"type": "lamb", "url": "http://lamb.test"},
                        "transport": {
                            "min_command_interval_s": 0.5,
                            "read_termination": "\r\n",
                        },
                    },
                    "smu": {
                        "profile": "hp/4142B",
                        "address": "GPIB0::23::INSTR",
                        "simulate": False,
                        "backend": {"type": "lamb", "url": "http://lamb.test"},
                        "transport": {"min_command_interval_s": 0.75},
                    },
                },
            }
        )
    )

    bench = Bench.open(bench_path, start_experiment=False)
    try:
        assert bench.devices["dmm"].config.transport == {
            "min_command_interval_s": 0.5,
            "read_termination": "\r\n",
        }
        assert bench.devices["smu"].config.transport == {"min_command_interval_s": 0.75}
    finally:
        bench.close_all()
